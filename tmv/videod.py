# pylint: disable=logging-fstring-interpolation
import argparse
import logging
import sys
from pathlib import Path
import shutil
import os

import toml
from pkg_resources import resource_filename
from _signal import signal, SIGINT, SIGTERM
from _datetime import datetime as dt, timedelta

from tmv.exceptions import ConfigError, SignalException
from tmv.util import LOG_FORMAT_DETAILED, LOG_LEVEL_STRINGS, Tomlable, dt2str, log_level_string_to_int, next_mark, sleep_until, slugify, str2dt
from tmv.video import VideoMakerDiagonal, VideoMaker, VideoMakerDay, ffmpeg_run, video_join, strptimedelta
import tmv


LOGGER = logging.getLogger(__name__)


class Task(Tomlable):
    """
    todo: Add 'period' to enable some tasks to run more or less frequently than others?
    """

    def __init__(self, src_path, dest_path):
        self.src_path = Path(src_path)
        self.dest_path = Path(dest_path)
        self.priority = 100  # 1-100 or so, smallest first

    def __str__(self):
        return f"{__name__}:: src: {self.src_path} dest: {self.dest_path}"

    def __repr__(self):
        return self.__str__()  # + " at " + str(id(self))

    def run(self):
        raise NotImplementedError

    def configd(self, config_dict):
        """ Parse common Task config items """
        # overwrite default specified in constructor
        self.src_path = Path(config_dict.get("src_path", self.src_path))
        self.dest_path = Path(config_dict.get("dest_path", self.dest_path))
        # to consider: try to avoid as the "run()" method would sometimes not run
        # probably need a "ready()" method in this class
        # self.interval = config_dict.get("interval",self.dest_path)


class DailyVideosTask(Task):
    """
    Make daylong videos from daily dirs of files. Only make if necessary.
    src:
    ./daily-photos/YYYY-MM-DD/*.jpg
    dest:
    ./daily-videos/YYYY-MM-DD.mp4
    """

    def __init__(self, src_path, dest_path):
        super().__init__(src_path, dest_path)
        self.minterpolate = False
        self.fps = 25
        self.speedup = None
        self.priority = 10

    def run(self):
        self.dest_path.mkdir(parents=True, exist_ok=True)
        if not os.path.isdir(self.src_path):
            LOGGER.warning(f"Ignoring directory {os.getcwd()}: no daily-photos dir")
            return

        for day_dir in sorted([x for x in self.src_path.iterdir() if x.is_dir()]):
            try:
                day = str2dt(str(day_dir.name)).date()
                mtime_images_dir = dt.fromtimestamp(day_dir.stat().st_mtime)
                day_video_filename = dt2str(day) + VideoMaker.VIDEO_SUFFIX
                day_video_path = self.dest_path / day_video_filename
                if day_video_path.is_file() and dt.fromtimestamp(day_video_path.stat().st_mtime) >= mtime_images_dir:
                    # video file is newer than images : no update
                    pass
                else:
                    # make a video
                    vm = VideoMakerDay()
                    # configure with toml
                    vm.file_list = list(day_dir.glob("*.jpg")) + list(day_dir.glob("*.JPG")) + list(day_dir.glob("*.jpeg")) + list(day_dir.glob("*.JPEG"))
                    if len(vm.file_list) > 1:
                        vm.load_videos()
                        filename = self.dest_path / day_video_filename
                        LOGGER.info("Creating daily-video: {}".format(filename.absolute()))
                        # ?? touch the preview file so that if we fail, we don't keep trying later runs?
                        filename.touch()
                        vm.write_videos(str(filename), fps=self.fps, force=True, speedup=self.speedup)

            except ValueError as exc:
                LOGGER.warning(f"Ignoring directory {os.path.abspath(day_dir)}: not a date format: {exc}")
        
    def configd(self, config_dict):
        super().configd(config_dict)
        self.setattr_from_dict("minterpolate", config_dict)
        self.setattr_from_dict("speedup", config_dict)
        self.setattr_from_dict("fps", config_dict)


class RecapVideosTask(Task):
    """
    Concat videos together to recap from past to now.
    """

    def __init__(self, src_path, dest_path):
        super().__init__(src_path, dest_path)
        self.priority = 20
        # fps is the output rate
        # speed is relative (i.e. 1 = speed of existing daily-videos)
        #                       input           output
        # dur_real  dur_video   frames          frames
        #                       @60spf_real     @25fps_video
        # 7 days    1 min       5040            1500               keep 30% of frames
        # 30 days   2 min       43200           3000               keep 7%
        # 1 year    5 min       525600          15000              keep 3%
        self.recaps = [
            {'label': "Last 7 days", 'days': 7, 'speed': 3.4, 'fps': 25},
            {'label': "Last 30 days", 'days': 30, 'speed': 7.2, 'fps': 25},
            {'label': "Complete", 'days': 0, 'speed': 35.0, 'fps': 25}
        ]

    def configd(self, config_dict):
        """
        Override default with config_dict['create'] settings.
        """
        super().configd(config_dict)
        if 'create' in config_dict:
            for label_days_pair in config_dict['create']:
                if not all(k in label_days_pair for k in ('label', 'days')):
                    raise ConfigError(f"Need 'label' and 'days' for each item in {config_dict['create']}")
            self.recaps = config_dict['create']

    def run(self):
        # Check if our recap video already exists and is equal/newer than the daily-videos *dir*.
        # Recall that the *dir* mtime is only changes when entries (i.e. new daily video) is added.
        # So we only re-create videos the following day - when a new daily video is added.
        # The end date is taken as the last video's time (e.g 2020-01-01.mp4). We don't
        # use now() as "the last week" really means "the last week of the videos" and would be
        # blank a week after no new images are added.
        self.dest_path.mkdir(parents=True, exist_ok=True)
        daily_videos = [str(p) for p in self.src_path.glob("*") if str2dt(Path(p).stem, throw=False) is not None]
        if not daily_videos:
            return

        last_video = max(daily_videos, key=lambda x: str2dt(Path(x).stem, throw=False))
        end = str2dt(Path(last_video).stem)
        # daily_video_dates
        for recap in self.recaps:
            speed = recap.get('speed', 1)
            fps = recap.get('fps', 25)
            if recap['days'] > 0:
                start = end - timedelta(days=recap['days'])
            else:
                start = dt.min

            video_path = self.dest_path / (slugify(recap['label']) + VideoMaker.VIDEO_SUFFIX)
            if video_path.is_file() and dt.fromtimestamp(video_path.stat().st_mtime) >= dt.fromtimestamp(self.src_path.stat().st_mtime):
                # exists, newer: no update
                pass
            else:
                LOGGER.info("Creating recap-video: {}".format(video_path.absolute()))
                # ?? touch the preview file so that if we fail, we don't keep trying later runs?
                video_path.touch()
                video_join(src_videos=daily_videos, dest_video=str(video_path),
                           start_datetime=start, end_datetime=end, speed_rel=speed, fps=fps)


class DiagonalVideosTask(Task):
    """ Make one video from all the images using DayHourVideoMaker to create a "diagonal" video""
    # src_path / 2001-01-01/*.jpg
    #          / 2001-01-02/*.jpg
    #           ...
    # dest_path = diagonal-AUTO-NAME.jpg
    """

    def __init__(self, src_path, dest_path):
        super().__init__(src_path, dest_path)
        self.minterpolate = False
        self.fps = 25
        self.speedup = None
        self.priority = 50
        self.sliceage = None

    def configd(self, config_dict):
        super().configd(config_dict)
        if 'sliceage' in config_dict:
            self.sliceage = strptimedelta(config_dict['sliceage'])

    def run(self):
        """
        Diagonal videos should only be made irregularly
        Hence check daily-photos (src_path) and add a day 
        """
        self.dest_path.mkdir(parents=True, exist_ok=True)
        vm = VideoMakerDiagonal()
        video_filename = "diagonal-all" + VideoMaker.VIDEO_SUFFIX
        video_path = self.dest_path / video_filename
        if video_path.is_file() and \
                dt.fromtimestamp(video_path.stat().st_mtime) + timedelta(hours=24) >= dt.fromtimestamp(self.src_path.stat().st_mtime):
            # exists, newer: no update
            pass
        else:
            vm.sliceage = self.sliceage
            vm.file_list = list(self.src_path.glob("**/*.jpg"))
            if len(vm.file_list) > 1:
                vm.load_videos()
                LOGGER.debug("Creating diagonal-video: {}".format(video_path.absolute()))
                # ?? touch the preview file so that if we fail, we don't keep trying later runs?
                video_path.touch()
                vm.write_videos(str(video_path), fps=self.fps, force=True, speedup=self.speedup)


class PreviewVideosTask(Task):
    """
    Apply ffmpeg -i 2020-05-06.mp4 -vf "scale=128:-1, fps=fps=10, setpts=0.25*PTS" 2020-05-06-preview.mp4
    to src_path and put them in dest_path with the same name.
    Examples:
    # put ./bob.mp4 in ./previews/bob.mp4
    PreviewVideosTask(".","previews")
    # will fail as will not overwrite
    PreviewVideosTask(".",".")
    """

    def __init__(self, src_path, dest_path):
        super().__init__(src_path, dest_path)
        if src_path == dest_path:
            raise ConfigError(f"src_path and dest_path cannot be the same (both were {src_path})")
        self.filters = {}
        self.filters['scale'] = "128:-1"
        self.filters['fps'] = "fps=5"
        self.filters['setpts'] = "0.25*PTS"
        self.priority = 70

    def configd(self, config_dict):
        """
        [preview-videos]
        filters.scale="128:-1"
        filters.fps = "fps=10"
        filters.setpts = "0.25*PTS"
        dest_path = "previews"
        """
        super().configd(config_dict)
        if 'filters' in config_dict:
            for k, v in config_dict['filters'].items():
                self.filters[k] = v

    def run(self):
        # Check (recursive) all videos to see if our thumbnail is out of date and replace it
        # Careful not to preview the previews (remove via if ...)
        videos = [p for p in self.src_path.glob("**/*.mp4") if p.parent.name != self.dest_path.name]
        for v in videos:
            preview_filename = v.parent / self.dest_path / v.name
            preview_filename.parent.mkdir(exist_ok=True, parents=True)
            if preview_filename.is_file() and preview_filename.stat().st_mtime >= v.stat().st_mtime:
                pass
            else:
                LOGGER.info(f"Creating preview at {Path(preview_filename).absolute()} with vf={self.filters}")
                # touch the preview file so that if we fail, we don't keep trying later runs
                preview_filename.touch()
                ffmpeg_run(str(v), str(preview_filename), vf=self.filters)


class MostRecent(Tomlable):
    """
    Add symlinks in root to the latest photo, daily-video
    """

    def __init__(self, src_path, dest_path):
        self.src_path = Path(src_path)
        self.dest_path = Path(dest_path)
        self.priority = 80  # 1-100 or so, smallest first

    def __str__(self):
        return f"MostRecent:: src: {self.src_path} dest: {self.dest_path}"

    def __repr__(self):
        return self.__str__()  # + " at " + str(id(self))

    def run(self):
        # find latest photo in 'daily-images'
        dated_dirs = sorted((Path(d) for d in Path('daily-photos').glob("????-??-??") if d.is_dir()), reverse=True)
        last_dir = next(iter(dated_dirs), None)
        if last_dir:
            dated_images = sorted((Path(f) for f in last_dir.glob("*.jpg") if f.is_file()), reverse=True)
            last_image = next(iter(dated_images))
            if last_image:
                link_name = f"most-recent-{last_image.name}"
                for link in Path(".").glob("most-recent-*.jpg"):
                    link.unlink()
                os.symlink(str(last_image), link_name)
    # find latest video  in 'daily-videos'
        dated_videos = sorted((Path(v) for v in Path('daily-videos').glob("*.mp4") if v.is_file()), reverse=True)
        last_video = next(iter(dated_videos), None)
        if last_video:
            link_name = f"most-recent-{last_video.name}"
            for link in Path(".").glob("most-recent-*.mp4"):
                link.unlink()
            os.symlink(str(last_video), link_name)

    def configd(self, config_dict):
        pass

    # def configd(self, config_dict):
    #    super().configd(config_dict)


class TaskRunner(Tomlable):
    """
    Scan directories in cwd and calls VideoMaker to create videos. Various tasks can be performed.
    """

    def __init__(self):
        self.tasks = {}
        self.raise_task_exceptions = False

    def __str__(self):
        return f"TaskRunner: tasks={self.tasks}"

    def __repr__(self):
        return f"TaskRunner: tasks={self.tasks}"

    def configd(self, config_dict):
        if 'log_level' in config_dict:
            LOGGER.setLevel(config_dict['log_level'])
        if 'most-recent' in config_dict:
            self.tasks['MostRecentTask'] = MostRecent(".", ".")
            self.tasks['MostRecentTask'].configd(config_dict['most-recent'])
        if 'recap-videos' in config_dict:
            self.tasks['RecapVideosTask'] = RecapVideosTask("daily-videos", "recap-videos")
            self.tasks['RecapVideosTask'].configd(config_dict['recap-videos'])
        if 'daily-videos' in config_dict:
            self.tasks['DailyVideosTask'] = DailyVideosTask("daily-photos", "daily-videos")
            self.tasks['DailyVideosTask'].configd(config_dict['daily-videos'])
        if 'preview-videos' in config_dict:
            self.tasks['PreviewVideosTask'] = PreviewVideosTask(".", "previews")  # default
            self.tasks['PreviewVideosTask'].configd(config_dict['preview-videos'])
        if 'diagonal-videos' in config_dict:
            self.tasks['DiagonalVideosTask'] = DiagonalVideosTask("daily-photos", "diagonal-videos")
            self.tasks['DiagonalVideosTask'].configd(config_dict['diagonal-videos'])
        if 'on-demand-videos' in config_dict:
            raise NotImplementedError

    def run_tasks(self):  # , runs = sys.maxsize):

        if not self.tasks:
            raise ConfigError("No tasks configured")

        ordered_tasks = {k: v for k, v in sorted(self.tasks.items(), key=lambda t: t[1].priority)}
        failed = 0

        for (taskname, task) in ordered_tasks.items():
            try:
                LOGGER.debug(f"Running {taskname} in cwd {os.getcwd()}")
                task.run()
            except BaseException as exc:
                # one failed task shouldn't stop others - handle locally
                if self.raise_task_exceptions:
                    raise
                else:
                    LOGGER.debug(f"Continuing other tasks after exception in task: {taskname}, cwd: {os.getcwd()}: {exc}", exc_info=exc)
                    failed += 1

        succeded = len(ordered_tasks) - failed
        return succeded, failed


class TaskRunnerManager(Tomlable):
    """
    In a single directory run a list of tasks to make videos, etc.
    """

    DEFAULT_INTERVAL = timedelta(seconds=60)

    def __init__(self):
        self.locations = ["."]
        self.tmv_root = "."
        self.vds = {}
        self.interval = self.DEFAULT_INTERVAL

    def __str__(self):
        return f"TaskRunnerManager: locations={self.vds} tmv_root={self.tmv_root} interval:{self.interval}"

    def __repr__(self):
        return f"TaskRunnerManager: locations={self.locations} tmv_root={self.tmv_root}"

    def configd(self, config_dict):
        self.setattr_from_dict('tmv_root', config_dict)

        if 'interval' in config_dict:
            # interval specified as seconds: convert to timedelta
            self.interval = timedelta(seconds=config_dict['interval'])

        self.setattr_from_dict('locations', config_dict)
        # Make instances for each location
        # Pass the same config to each daemon (they will ignore our  keys)
        # They can override if they want
        for l in self.locations:
            self.vds[l] = TaskRunner()
            self.vds[l].configd(config_dict)

    def run(self, runs):
        # start in the specified directory and run forever
        if not Path(self.tmv_root).is_dir():
            LOGGER.error(f"No such dir to start in: {Path(self.tmv_root).absolute()}")

        original_cwd = os.getcwd()
        tmv_root_path = Path(self.tmv_root).absolute()
        LOGGER.debug(f"Starting TaskRunner: {str(self)}")

        for run in range(0, runs):
            s_total = 0
            # run immediately, then sleep between runs
            if run > 0:
                sleep_until(next_mark(self.interval, dt.now()), dt.now())
            # run each TaskRunner in sequence 
            for l, vd in self.vds.items():
                try:
                    if (tmv_root_path / l).is_dir():
                        os.chdir(tmv_root_path / l)
                        LOGGER.debug(f"running tasks in cwd:{os.getcwd()}")
                        s, f = vd.run_tasks()
                        s_total += s
                        if s_total == 0 or f > 0:
                            LOGGER.warning(f"TaskRunner at {Path(l).absolute()} failed {f} tasks and succeeded in {s} tasks")
                except BaseException as exc:
                    LOGGER.warning(exc)
                    LOGGER.debug(exc, exc_info=exc)

            LOGGER.debug(f"Finished all tasks under {tmv_root_path}")
            os.chdir(original_cwd)


def sig_handler(signal_received, frame):
    raise SignalException


def videod_console(cl_args=sys.argv[1:]):
    """
    Manage single or multiple videod processes
    """
    #
    # Parse config file here, then setup and launch other processes with necessary arguments.
    #
    signal(SIGINT, sig_handler)
    signal(SIGTERM, sig_handler)

    parser = argparse.ArgumentParser("A daemon to make timelapse videos, on multiple locations.")
    parser.add_argument('--log-level', default='INFO', dest='log_level',
                        type=log_level_string_to_int, nargs='?',
                        help='level: {0}'.format(LOG_LEVEL_STRINGS))
    parser.add_argument('--config-file', default="./videod.toml")
    parser.add_argument('--runs', nargs="?", type=int, default=sys.maxsize)

    args = (parser.parse_args(cl_args))

    # Set up logger - used detailed to get processes' PIDs
    logging.getLogger("tmv.videod").setLevel(args.log_level)
    logging.basicConfig(format=LOG_FORMAT_DETAILED,
                        level=args.log_level, datefmt='%Y-%m-%dT%H:%M:%S')
    # Pulls all logs back to parent from other sub processes
    # multiprocessing_logging.install_mp_handler()
    LOGGER.info(f"Starting videod app. config file:{args.config_file} cwd:{os.getcwd()}")
    try:
        if not Path(args.config_file).is_file():
            shutil.copy(resource_filename(__name__, 'resources/videod.toml'), args.config_file)
            LOGGER.warning("Writing default config file to {}.".format(args.config_file))

        print(LOGGER.getEffectiveLevel())
        manager = TaskRunnerManager()
        manager.config(args.config_file)
        LOGGER.setLevel(args.log_level) # args override
        #tmv.video.LOGGER.setLevel(LOGGER.getEffectiveLevel() + 10)  # less logging for video when running as daemon
        manager.run(args.runs)

    except SignalException as e:
        LOGGER.info('SIGTERM, SIGINT or CTRL-C detected. Exiting gracefully.')
    except toml.decoder.TomlDecodeError as e:
        LOGGER.error("Error in {}:{} ".format(args.config_file, e), exc_info=e)
        sys.exit(1)
    except BaseException as e:
        LOGGER.debug(e, exc_info=e)
        LOGGER.error(e)
        sys.exit(2)

    sys.exit(0)
