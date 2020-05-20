#!/usr/bin/env python3
"""
 Module "tmv.video" (Time Lapse Video)  Details
 -------------------------------
 TLVideos are collections of TLFiles. Each TLFile is a photo with a timestamp and duration.
 Duration is the timedelta to the next frame.

 _real suffix is the original images, in real time
 _video suffix is the ... video.

 Each video has the following constant values
 - duration_real : end-start frame
 - n_frames : number of frames
 - fps_real_avg : duration_real / n_frames
 - fps_real_max :  1/min(frame_duration)

 fps_real_avg is the average. The maximum (fps_real_max) could be higher, as frame intervals can
 be non-homogenous. Imagine photo intervals:
 +    +    +    ++++++    +    +    +    +
 The maximum will be within the +++++, while the average will be +   + (i.e. slightly smaller than typical internal)

 Each video has a speedup factor set. This determines the fps_video. This encompasses VFR and CFR video speedup.
 - speedup = length_real / length_video
           = duration_real * fps_video / nframes

 VFR: This is a "compressed" version of the real.
              : Determined by duration of frames / speedup factor.
              : fps_video = varies

 CFR: This is an idealised version of the real.
 - CFR-EVEN: each frame duration = duration_video / nframes
             : this evenly spaces frames
             : fps_video (avg) = speedup * duration_real / n_frames
 - CFR-PADDED    : runs at the maximum frame rate, and pads 'slower' areas with frames
             : fps_video (max) = speedup * fps_real_max = speedup * 1/min[frame_duration]
"""


# pylint: disable=logging-fstring-interpolation,logging-not-lazy, dangerous-default-value

import os
import os.path
import argparse
import glob
import subprocess
from subprocess import CalledProcessError
from enum import Enum
import sys
import itertools
import logging
import imghdr

from collections import OrderedDict
from pathlib import Path
from datetime import datetime as dt, timedelta, time
from nptime import nptime
from dateutil.parser import parse
from PIL import ImageFont
from PIL import Image
from PIL import ImageDraw

from tmv.videotools import valid
from tmv.util import LOG_FORMAT, LOG_LEVEL_STRINGS, add_stem_suffix, dt2str, DATETIME_FORMAT, prev_mark, HH_MM
from tmv.util import LOG_LEVELS, cpe2str, log_level_string_to_int, run_and_capture, str2dt, strptimedelta, subprocess_stdout, unlink_safe
from tmv.exceptions import VideoMakerError


LOGGER = logging.getLogger(__name__)

# following imports are optional for extra functionality

try:
    import exifread
except ImportError as e:
    LOGGER.debug(e)

try:
    from ascii_graph import Pyasciigraph    # graph command
except ImportError as e:
    LOGGER.debug(e)


def exif_datetime_taken(filename) -> dt:
    f = open(filename, 'rb')
    tags = exifread.process_file(f, details=False)
    f.close()
    datetime_taken_exif_str = tags["EXIF DateTimeOriginal"]
    return dt.strptime(
        str(datetime_taken_exif_str), r'%Y:%m:%d %H:%M:%S')


def str_to_class(classname):
    return getattr(sys.modules[__name__], classname)


def neighborhood(iterable):
    iterator = iter(iterable)
    prev = None
    item = next(iterator)  # throws StopIteration if empty.
    for nextone in iterator:
        yield (prev, item, nextone)
        prev = item
        item = nextone
    yield (prev, item, None)


class VSyncType(Enum):
    """ ffmpeg vsync selections """
    vfr = 1
    cfr_pad = 2
    cfr_even = 3

    @staticmethod
    def fromStr(name):
        return getattr(VSyncType, name)

    @staticmethod
    def names():
        return list(map(lambda x: x.name, list(VSyncType)))


class SliceType(Enum):
    """ refactor - it's crappy """
    Day = 1
    Hour = 2
    Diagonal = 3
    Concat = 4

    @staticmethod
    def fromStr(name):
        return getattr(SliceType, name)

    @staticmethod
    def names():
        return list(map(lambda x: x.name, list(SliceType)))


class VideoMaker:
    """
     Abstract base class for further makers. Maybe a composite or adaptor pattern would be better?
     Some kind of 'arranger' is passed in
     Filters too passed in?
     """

    VIDEO_SUFFIX = ".mp4"

    def __init__(self):
        self.tl_videos = []
        self.speedup = 60
        self.fps_requested = None
        self.file_glob = ""
        self._file_list = []
        self.tl_files = []
        self.motion = False
        self.start_time = time.min
        self.end_time = time.max
        self.sliceage = timedelta(hours=1)
        self.start = dt.min
        self.end = dt.max

    def __str__(self):
        return f"{type(self).__name__}: tl_videos:{self.tl_videos}  speedup:{self.speedup}" + \
               f"fps_requested:{self.fps_requested} sliceage:{self.sliceage,} _file_list:{len(self._file_list)}"

    @property
    def file_list(self):
        return self._file_list

    @file_list.setter
    def file_list(self, new_file_list):
        """ Any iterable with str() to make paths. Converts to a nice list of str """
        self._file_list = list(str(p) for p in new_file_list)

    def ls(self):
        s = ""
        for m in self.tl_videos:
            s = s & m.ls()
        return s

    def read_image_times(self):
        self.tl_files = []
        n_errors = 0
        LOGGER.debug(f"Reading dates of {len(self._file_list)} files...")
        if not self._file_list:
            raise VideoMakerError("No image files found")

        for fn in self._file_list:
            # Using second resolution can lead to *variable* intervals. For instance, if the interval is 4.1s,
            # the durations with be 4/300 (0.0133) but then each 10 frames 5/300
            # It's therefore better to use constant frame rate, or to adjust this function
            # to millisecond resolution and/or round
            try:
                try:
                    # Filename date
                    datetime_taken = str2dt(fn)
                except ValueError:
                    # Try to get EXIF
                    datetime_taken = exif_datetime_taken(fn)

                if (self.end_time >= datetime_taken.time() >= self.start_time and
                        self.end >= datetime_taken >= self.start):
                    tlf = TLFile(fn, datetime_taken)
                    if tlf.valid():
                        self.tl_files.append(tlf)
                    else:
                        raise Exception("Ignoring invalid image: {}".format(tlf))

            except Exception as exc:
                n_errors += 1
                LOGGER.warning(f"Exception getting image's datetime: {exc})")

        LOGGER.debug(f"Got images for {len(self.tl_files)}/{len(self._file_list)} files, and {n_errors} failures")
        if n_errors:
            LOGGER.warning(f"No dates available for {n_errors}/{len(self._file_list)} files. Ignoring them.")
        return self.tl_files.sort()

    def files_from_glob(self, file_glob: (str, list)):
        """
         from a glob-string or list of them, return a list of filenames matching the globs
         """
        if not isinstance(file_glob, list):
            file_glob = [file_glob]
        file_glob = [str(f) for f in file_glob]

        self._file_list = []
        self.file_glob = file_glob
        for fg in file_glob:
            self._file_list.extend(glob.glob(fg))
        self._file_list.sort()
        LOGGER.debug("Processing %d files" % (len(self._file_list)))

    def load_videos(self):
        del self.tl_videos[:]
        self.read_image_times()

    def write_videos(self, filename=None, vsync="cfr-even", speedup=None, fps=None,
                     force=False, motion_blur=False, dry_run=False):

        i = 0
        written_filenames = []
        filename = str(filename)
        for m in self.tl_videos:
            # if multiple videos and fixed filename, add a suffix
            i = i + 1
            if len(self.tl_videos) > 1 and filename is not None:
                fn = add_stem_suffix(m.default_video_filename(), str(i).zfill(len(str(self.tl_videos))))
            else:
                fn = filename

            fn = m.write_video(filename=fn, vsync=vsync, fps=fps, speedup=speedup,
                               motion_blur=motion_blur,
                               dry_run=dry_run, force=force, )
            written_filenames.append(fn)
        return written_filenames

    def delete_images(self):
        n = 0
        for m in self.tl_videos:
            if m.written:
                for tlf in m.tl_files:
                    os.unlink(tlf.filename)
                    n += 1
        return n

    def stamp_images(self):
        n = 0
        for m in self.tl_videos:
            for tlf in m.tl_files:
                tlf.stamp()
                n += 1
        return n

    def graph_intervals(self, interval):
        for m in self.tl_videos:
            m.graph_intervals(interval)
        return

    def rename_images(self):
        n = 0
        for m in self.tl_videos:
            for tlf in m.tl_files:
                tlf.rename()
                n += 1
        return n


class VideoMakerConcat(VideoMaker):
    """
    Join all the images together!
    """

    def load_videos(self):
        VideoMaker.load_videos(self)
        self.tl_videos.append(TLVideo(self.tl_files))


class VideoMakerHour(VideoMaker):
    """
    Make one video per hour
    """

    def __str__(self):
        return f"{type(self).__name__}: videos:{len(self.tl_videos)}  SpeedUp:{self.speedup}" + \
               f"file_list:{len(self._file_list)} range={self.start_time} to {self.end_time}"

    def ls(self):
        s = ""
        for m in self.tl_videos:
            s += m.ls()
        return s

    def video_duration_real_expected(self):
        return timedelta(hours=1)

    def load_videos(self):
        VideoMaker.load_videos(self)
        groupedByTimeTLFiles = self.group_by_time(self.tl_files)
        # @todo remove out-of-time hours???
        for h in groupedByTimeTLFiles:
            LOGGER.debug("VideoMakerHourly: Loading video for {} with {} files from {} total files ".format(h, len(
                groupedByTimeTLFiles[h]), len(self.tl_files)))

            tlm = TLVideo(groupedByTimeTLFiles[h])
            self.tl_videos.append(tlm)
            # pprint.pprint(grouped_tl_files)

    @staticmethod
    def group_by_time(localTLFiles):
        grouped_tl_files = OrderedDict()
        for day_hour, day_files in itertools.groupby(localTLFiles,
                                                     lambda x: dt.combine(x.taken.date(),
                                                                          time(x.taken.hour, 0, 0, 0))):
            LOGGER.debug("Hour {day_hour}")
            grouped_tl_files[day_hour] = []
            for tlf in sorted(day_files):
                grouped_tl_files[day_hour].append(tlf)
            #    print ("\t{}".format(tlf.filename))
            # grouped_tl_files = sorted(grouped_tl_files)
        return grouped_tl_files


class VideoMakerDay(VideoMaker):
    """ Seperate video for each day """

    def __str__(self):
        return f"{type(self).__name__}: tl_videos:{self.tl_videos}  speedup:{self.speedup}" + \
            f"fps_requested:{self.fps_requested} sliceage:{self.sliceage,} _file_list:{len(self._file_list)}"

    def ls(self):
        s = ""
        for m in self.tl_videos:
            s += m.ls()
        return s

    def load_videos(self):
        VideoMaker.load_videos(self)
        grouped_by_day_tl_files = self.group_by_day(self.tl_files)
        for day in grouped_by_day_tl_files:
            LOGGER.debug("Loading video for {} with {} files".format(
                day, len(grouped_by_day_tl_files[day])))
            self.tl_videos.append(TLVideo(grouped_by_day_tl_files[day]))

    @staticmethod
    def group_by_day(localTLFiles):
        grouped_tl_files = OrderedDict()
        for day, dayFiles in itertools.groupby(
                localTLFiles, lambda x: x.taken.date()):
            # print ("Day {}".format(day))
            grouped_tl_files[day] = []
            for tlf in sorted(dayFiles):
                grouped_tl_files[day].append(tlf)
            #    print ("\t{}".format(tlf.filename))
        # grouped_tl_files = sorted(grouped_tl_files)
        return grouped_tl_files


class VideoMakerDiagonal(VideoMakerDay):
    """ Diagonal slice through a chart of X-axis days and Y-axis hours
        e.g. over a year and 01:00 to 12:00, video has Jan @ 1:00, Feb @ 2:00 ... Dec @ 12:00
        """

    def load_videos(self):
        VideoMaker.load_videos(self)

        daily = self.group_by_day(self.tl_files)

        start_time = nptime.from_time(min([s.taken.time() for s in self.tl_files]))
        end_time = nptime.from_time(max([s.taken.time() for s in self.tl_files]))
        day_length = end_time - start_time
        start_date = min([s.taken.date() for s in self.tl_files])
        end_date = max([s.taken.date() for s in self.tl_files])

        # Note that len (daily) = end_date - start_date + 1, iff continuous

        # daily_advance is how much to advance the clock each day
        # like the 'descent angle' on the time v hours graph.
        daily_advance = day_length / len(daily)
        LOGGER.debug(f"start_time={start_time} end_time={end_time}")
        LOGGER.debug(f"start_date={start_date} end_date={end_date}")
        LOGGER.debug(f"days={len(daily)} sliceage={self.sliceage} daily_advance={daily_advance}")

        TIME_FORMAT = "%H:%M"  # %S
        mark = start_time
        sliced_tl_files = []
        for day in sorted(daily.keys()):
            day_slice = [tlf for tlf in daily[day] if mark < tlf.taken.time() < mark + self.sliceage]
            sliced_tl_files.extend(day_slice)
            LOGGER.debug(f"Day:{day} Slice:{ mark.strftime(TIME_FORMAT)}->{(mark+self.sliceage).strftime(TIME_FORMAT)}" + f" {len(day_slice)}/{len(daily[day])} files")
            mark += daily_advance
        sliced_tl_files.sort()
        self.tl_videos.append(TLVideo(sliced_tl_files))


class TLVideo:
    """
    A video is a collection of images for writing, with associated fps, etc.
    """
    # minutes. Gaps greater than this are considered disjoint
    disjointThreshold = timedelta(hours=1)
    # self.motionTimeDeltaMax = datetime.timedelta(hours=1)  # if longer than
    # this, cannot really compute motion

    def __init__(self, tl_files):
        self.tl_files = tl_files
        self.calc_gaps()

    def __str__(self):
        return "TLVideo: filename:{} frames:{} spfReal:{:.1f}".format(
            self.default_video_filename(), len(self.tl_files), self.spf_real_avg())

    def ls(self):
        s = ""
        for tlf in self.tl_files:
            s += str(tlf) + "\n"
        return s

    # Plot ascii frequency of photos per bin (defaults: 1 hour)
    def graph_intervals(self, interval):
        freq = {}
        for tlf in self.tl_files:
            rounded = prev_mark(tlf.taken, interval.total_seconds())
            if rounded not in freq:
                freq[rounded] = 0
            freq[rounded] += 1
            # print("{}:{}".format(hour,tlf.taken))
        graphable = []
        for h in sorted(freq):
            # print("{}:{}".format(h,freq[h]))
            graphable.append(tuple((h.isoformat(), freq[h])))
            # print (graphable)
        graph = Pyasciigraph()

        for line in graph.graph('Frequency per {}'.format(interval), graphable):
            print(line)

    # Set duration_real for each frame. This is the time difference between this and the next's frame timeTaken
    # Gaps are used for VFR videos
    def calc_gaps(self):
        if len(self.tl_files) <= 1:
            return
        for prev, item, next_item in neighborhood(self.tl_files):
            if next_item is not None:
                item.duration_real = next_item.taken - item.taken

            if next_item is None:
                # last item's duration is unknown. assume is equal to
                # penultimates's duration
                item.is_last = True
                item.duration_real = prev.duration_real

            if item.duration_real > self.disjointThreshold:
                # if there is a massive disjoint in the images' datetakens, skip this in the video
                # (ie. set duration_real from BIG to a small value)
                item.duration_real = timedelta(
                    milliseconds=1000)  # (seconds=666)

    # Since frames' time may be disjoint, add the gaps between all frames; see
    # "calc_gaps"
    def duration_real(self):
        dr = timedelta()
        for tlf in self.tl_files:
            dr += tlf.duration_real
        return dr

    def first(self):
        if len(self.tl_files) < 1:
            return None
        return self.tl_files[0].taken

    def last(self):
        if len(self.tl_files) < 1:
            return None
        return self.tl_files[-1].taken

    def duration_video(self, speedup):
        # Run-around to avoid "TypeError: unsupported operand type(s) for /:
        # 'datetime.timedelta' and 'int'"
        return timedelta(
            seconds=self.duration_real().total_seconds() / speedup)

    def fps_video_max(self, speedup):
        return self.fps_real_max() * speedup

    def fps_video_avg(self, speedup):
        return self.fps_real_avg() * speedup

    def fps_real_avg(self):
        if len(self.tl_files) == 0:
            return 0
        if self.duration_real().total_seconds() == 0:
            return 0
        return len(self.tl_files) / self.duration_real().total_seconds()

    def fps_real_max(self):
        if len(self.tl_files) == 0:
            return 0
        if self.duration_real().total_seconds() == 0:
            return 0
        min_frame_duration = min(
            self.tl_files,
            key=lambda x: x.duration_real).duration_real.total_seconds()
        return 1 / min_frame_duration

    def spf_real_avg(self):
        if self.fps_real_avg() == 0:
            return 0
        return 1 / self.fps_real_avg()

    def write_video(self, filename=None, force=False, vsync="cfr-even", motion_blur=False,
                    dry_run=False, fps=None, speedup=None):
        pts_factor = 1
        if len(self.tl_files) <= 1:
            raise VideoMakerError(f"Less than one image to write for {filename}")
        if not filename:
            filename = self.default_video_filename()
        if not force and os.path.isfile(filename):
            LOGGER.info("Not overwriting {}".format(filename))
            return False
        if vsync == 'vfr':
            # input frame rate is defined by the duration of each frame
            if fps:
                raise VideoMakerError("Cannot specify fps *and* vfr")
            if not speedup:
                raise VideoMakerError("Must specify speed for vfr")
            list_filename = self.write_images_list_vfr(filename, speedup)
            # set to the maximum
            fps = self.fps_video_max(speedup)
            input_parameters = []
        elif vsync == 'cfr-even':
            # assume frames are equally spaced between start and end time
            vsync = 'cfr'
            list_filename = self.write_images_list_cfr(filename)
            # if fps(output) is specified:
            # - and if speedup is not specified, find the implied speedup (= duration_real / duration_video)
            # - and speed is specified, change the video playback speed (via PTS). PTS factor = desired_speedup / implied_speedup
            # if speed is specified:
            # - and nothing else, set output fps to achieve the desired speedup
            if fps:
                if speedup:
                    implied_speedup = self.duration_real().total_seconds() / \
                        len(self.tl_files) * fps
                    pts_factor = implied_speedup / speedup
                    if not 1000 > pts_factor > 0.001:
                        raise VideoMakerError(f"pts of {pts_factor} is out of a sane range")
                else:
                    # use this fps value. calc speedup for reporting only
                    speedup = self.duration_real().total_seconds() / len(self.tl_files) * fps
            elif speedup:
                fps = self.fps_video_avg(speedup)
            else:
                raise VideoMakerError("Specify fps and/or speedup. (Using vsync=cfr-even)")
            input_parameters = ["-r", str(round(fps, 0))]
        elif vsync == 'cfr-padded':
            # use a constant framerate, but pad 'slow' sections to reproduce original intervals
            # use max framerate for fastest section, pad other bits
            vsync = 'cfr'
            list_filename = self.write_images_list_vfr(filename, speedup)
            fps = self.fps_video_max(speedup)
            # set the input-frame-rate (images) and output-frame-rate (video) to be the same
            # otherwise defaults to 25 (?)
            # input_parameters = ["-r", str(round(fps,0))]
            input_parameters = []
            raise NotImplementedError()
        else:
            raise VideoMakerError("Unknown type of vsync: {}".format(vsync))
        LOGGER.debug("creating video: {} src-frames: {} speedup:{} fps_video:{} video:{}s real:{}s pts:{:.3f}".format(
            filename, len(self.tl_files), speedup, fps, self.duration_video(speedup).total_seconds(), self.duration_real().total_seconds(), pts_factor))

        # dfs = max(5, int(fps / 2.0))  # deflicker size. smooth across 0.5s

        # filter to add 2 seconds to end
        # tpad=stop_mode=clone:stop_duration=2,
        if motion_blur:
            # output_parameters = ["-vf", "deflicker,minterpolate,setpts=PTS*"+pts_factor]
            output_parameters = [
                "-vf", "deflicker,minterpolate", "-preset", "veryfast", ]
            fps *= 2
        else:
            output_parameters = [
                "-vf", "deflicker,setpts=PTS*{:.3f}".format(pts_factor), "-preset", "veryfast"]

        safe = "0"  # 0 = disable safe 1 = enable safe filenames
        start_date = min([s.taken for s in self.tl_files])
        metadata1 = "comment=description has real start as str and real duration in seconds"
        metadata2 = "author=TimeMakeVisible"
        metadata3 = f"description={dt2str(start_date)},{self.duration_real().total_seconds():.0f}"
        the_call = ["ffmpeg", "-hide_banner", "-loglevel", "verbose", "-y", "-f", "concat", "-vsync", vsync, "-safe", safe]
        the_call.extend(input_parameters)
        the_call.extend(["-i", list_filename])
        the_call.extend(["-metadata", metadata1])
        the_call.extend(["-metadata", metadata2])
        the_call.extend(["-metadata", metadata3])
        the_call.extend(output_parameters)
        the_call.extend(["-vcodec", "libx264", "-r", str(round(fps, 0)), filename])

        if dry_run:
            LOGGER.info("Dryrun: {}\n".format(' '.join(the_call)))
            return

        log_path = Path(Path(filename).stem + ".ffmpeg")
        try:
            run_and_capture(the_call, log_path)
            Path(list_filename).unlink()
        except CalledProcessError:
            LOGGER.warning(f"failed subprocess call logged to {log_path.absolute()}")
            raise

        # other exception - no command was run - leave log with only the call

    def write_images_list_vfr(self, filename, speedup):
        f = open(os.path.basename(filename) + ".images", 'w')
        for tlf in self.tl_files:
            f.write("file '" + tlf.filename + "'\n")
            f.write(
                "duration " + str(timedelta(seconds=tlf.duration_real.total_seconds() / speedup)) + "\n")
        f.close()
        return os.path.basename(filename) + ".images"

    #
    # List of filenames only, without duration. Duration of each frame constant and defined by FPS
    #
    def write_images_list_cfr(self, video_filename):
        f = open(os.path.basename(video_filename) + ".images", 'w')
        for tlf in self.tl_files:
            f.write("file '" + tlf.filename + "'\n")
        f.close()
        return os.path.basename(video_filename) + ".images"

    def default_video_filename(self):
        if len(self.tl_files) == 0:
            return ""
            # bn = "empty"
        else:
            bn = self.tl_files[0].taken.strftime("%Y-%m-%dT%H") + "_to_" + self.tl_files[
                -1].taken.strftime("%Y-%m-%dT%H")
        return bn + ".mp4"


class TLFile:
    """
    Time-aware image
    """
    i = 0  # Simple counter, static

    def stamp(self):
        """ Draw a moving circle on the image for continuity in video checking """
        assert os.path.exists(self.filename)
        img = Image.open(self.filename)
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/freefont/FreeMono.ttf", 20)

        draw.pieslice([(0, 0), (100, 100)], self.ith %
                      360, self.ith %
                      360, fill=None, outline=None)
        draw.arc([(0, 0), (100, 100)], 0, 360)
        w, h = img.size
        # draw.text((  (self.ith*10) % w, h - 10), "*", (255, 255, 255), font=font)
        draw.text((w - 40, h - 40), str(self.ith), (255, 255, 255), font=font)
        draw.text((w - 300, h - 60), self.filename, (255, 255, 255), font=font)
        LOGGER.debug("Stamping: {} : {}x{}".format(self.filename, w, h))
        img.save(self.filename, )

    # Get the exif date and rename the file to that
    def rename(self, pattern="%Y-%m-%dT%H-%M-%S"):
        assert os.path.exists(self.filename)
        dtt = exif_datetime_taken(self.filename)
        date_filename = os.path.join(os.path.dirname(self.filename),
                                     dtt.strftime(pattern) + os.path.splitext(self.filename)[1])
        LOGGER.debug("Renaming {} to {}".format(self.filename, date_filename))
        os.rename(self.filename, date_filename)

    # Quick header check to see if valid
    def valid(self):
        image_header = imghdr.what(self.filename)
        return image_header  # i.e. not None and not ""

    def __repr__(self):
        return '{}\t\t{}\t\t{}\t{}'.format(self.taken, self.duration_real, self.filename,
                                           self.is_first if self.is_first else "    ")

    def __str__(self):
        return '{}\t\t{}\t\t{}\t{}'.format(self.taken, self.duration_real, self.filename,
                                           self.is_first if self.is_first else "    ")

    def __init__(self, filename, taken, tags=None):
        self.filename = filename
        self.taken = taken
        self.tags = tags
        TLFile.i += 1
        self.ith = TLFile.i
        self.duration_real = timedelta()
        self.is_first = False  # of a sequence
        # of a sequence - there will be gap after (or end)
        self.is_last = False
        self.motion = 0  # 0 to 1

    def __gt__(self, o2):
        return self.taken > o2.taken

    def __eq__(self, o2):
        return self.taken == o2.taken

    def __add__(self, other):
        return self.duration_real + other.duration_real

    def sense_motion(self, prevTLF):
        pass


def find_matching_files(date_list, video_files):
    matches = []
    for d in date_list:
        try:
            # match if filename starts with the date
            match = next(video for video in video_files if
                         d == str2dt(video).date())
            matches.append(match)
        except BaseException:
            LOGGER.info("No video for {}".format(d))  # not found

    return matches


def ffmpeg_run(input_path, output_path, vf=None):
    """ Run ffmpeg on an input file, save to output and use specified filters
        Throws on fail
    """
    the_call = ["ffmpeg", "-hide_banner", "-loglevel", "verbose", "-y"]  # -y : overwrite
    the_call.extend(["-i", input_path])
    if vf:
        the_call.extend(['-vf'])
        # god in the quotes
        the_call.extend([",".join(['{}={}'.format(k, v) for k, v in vf.items()])])
    the_call.extend([output_path])
    subprocess_stdout(the_call)  # throw on fail


def video_join(src_videos: list, dest_video: str, start_datetime, end_datetime, speed_rel, fps):

    LOGGER.debug("Searching {} to {}".format(start_datetime.isoformat(), end_datetime.isoformat()))
    invalid_videos = []
    for v in src_videos:
        if not valid(v) or str2dt(v, throw=False) is None:
            invalid_videos.append(v)

    if len(invalid_videos) > 0:
        LOGGER.warning("Ignoring {} invalid video(s) : {}".format(
            len(invalid_videos), invalid_videos))

    video_files = list(set(src_videos) - set(invalid_videos))

    video_files_in_range = [v for v in video_files if start_datetime.date(
    ) <= str2dt(v).date() <= end_datetime.date()]

    if len(video_files_in_range) < 1:
        raise VideoMakerError("No videos found to concat")

    video_files_in_range.sort()  # probably redundant as ls returns in alphabetical order
    # logger.info("concat'ing: {}".format('\n'.join(video_files_in_range)))
    videos_filename = 'filelist.txt'
    with open(videos_filename, 'w') as f:
        f.write("# Auto-generated\n")
        for video in video_files_in_range:
            f.write("file '%s'\n" % str(video))

    ffmpeg_concat_rel_speed(
        video_files_in_range, videos_filename, dest_video, speed_rel, fps)
    unlink_safe(videos_filename)


def ffmpeg_concat_rel_speed(filenames, filenames_file, output_file, rel_speed, fps):
    # Auto name FIRST_to_LAST
    if output_file is None:
        first_date = str2dt(filenames[0]).date()
        last_date = str2dt(filenames[-1]).date()
        output_file = first_date.isoformat() + "_to_" + last_date.isoformat()

    if rel_speed == 1:
        cl = "ffmpeg -hide_banner -y -f concat -safe 0 -i " + \
            filenames_file + " -c copy " + f"-r {fps} {output_file}"
    else:
        # output_file += "_xoutput_file" + "{0:.1f}".format(rel_speed)
        factor = 1 / rel_speed
        cl = "ffmpeg -hide_banner -y -f concat -safe 0 -i " + filenames_file + " -preset veryfast -filter:v setpts=" + str(
            factor) + "*PTS " + f"-r {fps} {output_file}"
    the_call = cl.split(" ")
    # use abs path to easily report errors directing user to log
    log_filename = os.path.abspath(os.path.basename(output_file) + ".ffmpeg")
    p_log = open(log_filename, "w")
    p_log.write("called: {}\n".format(' '.join(the_call)))  # ignored? overwriten
    LOGGER.debug("calling: {}\n".format(' '.join(the_call)))

    r = subprocess.call(
        the_call,
        stdout=p_log,
        stderr=subprocess.STDOUT)
    if r == 0:
        #  print(output_file)
        unlink_safe(log_filename)
    else:
        raise RuntimeError(
            "Failed on ffmpeg concat. Check log:{} Called:'{}' Return:{}".format(log_filename, ' '.join(the_call), r))


def video_compile_console(cl_args=sys.argv[1:]):
    parser = argparse.ArgumentParser("TMV Compiler", description="Compile timelapse videos from images. Outputs filename(s) of resultant video(s).")
    parser.add_argument("file_glob", nargs='+', help="Multiple image files or glob strings. e.g. 1.jpg '2*.jpg' 3.jpg")
    parser.add_argument("--start", "-s",type=parse, default=dt.min, help="eg. \"2 days ago\", 2000-01-20T16:00:00")
    parser.add_argument("--end", "-e",type=parse, default=dt.max, help="eg. Today, 2000-01-20T16:00:00")
    parser.add_argument("--start-time", "-st", type=lambda s: dt.strptime(s, HH_MM).time(), default=time.min, help="Consider only images after HH:MM each day")
    parser.add_argument("--end-time", "-se", type=lambda s: dt.strptime(s, HH_MM).time(), default=time.max, help="Consider images before HH:MM each day")
    parser.add_argument('--log-level', '-ll', default='WARNING', type=lambda s: LOG_LEVELS(s).name, choices=LOG_LEVELS.choices())
    parser.add_argument("--force", "-f", action='store_true', default=False, help="Force overwrite of existing videos")
    parser.add_argument("--slice", choices=SliceType.names(), default="Concat")
    parser.add_argument("--fps", "-fps", default=25, type=int, help="Output images at this Frames Per Second. (Implies --vsync cfr).")
    parser.add_argument("--speedup", "-su", default=None, type=int, help="Speed up video by this much: it's the ratio of real:video duration")
    parser.add_argument("--vsync", default="cfr-even", choices=['cfr-even', 'cfr-padded', 'vfr'], type=str, help="cfr-even uses start and end time, and makes frames are equally spaced. cfr-padded uses maximum framerate and pads slow bits. vfr uses exact time of each frame (less robust)")
    parser.add_argument("--sliceage", default=timedelta(hours=1), type=strptimedelta, help="For Diagonal slice types, HH:MM to show each day")
    parser.add_argument("--motion-blur","-mb", action='store_true', default=False, help="FFMPEG Filter to motion-blur video to reduce jerkiness. Ya jerk.")
    parser.add_argument("--output", "-o",type=str, help="Output here. Create this file (an extension is added) or folder (if multiple files are written)")
    parser.add_argument('--filenames', action="store_true", help="Write the videos created to stdout")
    parser.add_argument("--dry-run", action='store_true', default=False)
    # parser.add_argument("--filter-motion", action='store_true', default=False,    #                    help="Image selection to include only motiony images")

    try:
        args = (parser.parse_args(cl_args))
        LOGGER.setLevel(args.log_level)
        logging.basicConfig(format=LOG_FORMAT)

        mm = str_to_class("VideoMaker" + args.slice.title())()  # gutsy or stupid?
        mm.files_from_glob(args.file_glob)
        mm.start_time = args.start_time
        mm.end_time = args.end_time
        mm.sliceage = args.sliceage
        mm.start = args.start
        mm.end = args.end

        mm.load_videos()

        written_videos = mm.write_videos(filename=args.output,
                                         speedup=args.speedup, vsync=args.vsync, fps=args.fps,
                                         force=args.force, motion_blur=args.motion_blur, dry_run=args.dry_run)
        if args.filenames:
            print("\n".join(written_videos))

    except CalledProcessError as exc:
        print(cpe2str(exc), file=sys.stderr)
        LOGGER.debug(cpe2str(exc), exc_info=exc)
        sys.exit(2)
    # pylint:disable=broad-except
    except Exception as exc:
        print(f"Exception: {exc}", file=sys.stderr)
        LOGGER.debug(f"Exception: {exc}", exc_info=exc)
        sys.exit(1)

    sys.exit(0)


def video_join_console():
    parser = argparse.ArgumentParser("Combine timelapse videos")
    parser.add_argument("start", "-s",type=parse, default=dt.min, help="eg. \"2 days ago\", 2000-01-20T16:00:00")
    parser.add_argument("end", "-e",type=parse, default=dt.max, help="eg. Today, 2000-01-20T16:00:00")
    parser.add_argument('--log-level', '-ll', default='WARNING', type=lambda s: LOG_LEVELS(s).name, nargs='?', choices=LOG_LEVELS.choices())
    parser.add_argument("input_movies", nargs="+", help="All possible movie files to search")
    parser.add_argument("--output", help="Force the output filename, instead of automatically assigned based on dates.")
    speed_group = parser.add_mutually_exclusive_group()
    speed_group.add_argument("--speed-rel", default=1, help="Relative speed multipler. e.g. 1 is no change, 2 is twice as fast, 0.5 is twice as slow.")
    speed_group.add_argument("--speed-abs", default=None, help="Absolute speed (real time / video time)")

    args = (parser.parse_args())

    try:
        logging.basicConfig(format=LOG_FORMAT)
        LOGGER.setLevel(args.log_level)
        if args.start is None or args.end is None:
            raise SyntaxError("Couldn't understand dates: {}, {}".format(args.start, args.end))
        LOGGER.debug("Searching {} to {}".format(args.start.isoformat(), args.end.isoformat()))

        video_files = args.input_movies
        invalid_videos = []
        for v in video_files:
            if not valid(v) or str2dt(v, throw=False) is None:
                invalid_videos.append(v)

        if len(invalid_videos) > 0:
            LOGGER.warning("Ignoring {} invalid videos: {}".format(
                len(invalid_videos), invalid_videos))

        video_files = list(set(video_files) - set(invalid_videos))

        video_files_in_range = [v for v in video_files if
                                args.start.date() <= str2dt(v).date() <= args.end.date()]

        if len(video_files_in_range) < 1:
            LOGGER.debug(f"No videos found. video_files: {','.join(video_files)}")
            raise RuntimeError("No videos found to concat")
        video_files_in_range.sort()  # probably redundant as ls returns in alphabetical order
        LOGGER.debug("concat'ing: {}".format('\n'.join(video_files_in_range)))
        videos_filename = 'filelist.txt'
        with open(videos_filename, 'w') as f:
            f.write("# Auto-generated by TMV\n")
            for video in video_files_in_range:
                f.write("file '%s'\n" % str(video))

        if args.speed_abs is not None:
            raise NotImplementedError
            # ffmpeg_concat_abs_speed(
            #  videos_filename, args.output, float(args.speed_abs))
        else:
            ffmpeg_concat_rel_speed(
                video_files_in_range, videos_filename, args.output, float(args.speed_rel), 25)
        unlink_safe(videos_filename)
        exit(0)
    except Exception as exc:
        print(e, file=sys.stderr)
        LOGGER.error(e)
        LOGGER.debug(f"Exception: {exc}", exc_info=exc)
        exit(1)
