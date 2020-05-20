"""
Tools for working with videos
"""

# pylint: disable=line-too-long, logging-fstring-interpolation, dangerous-default-value

from os import getcwd
import sys
from sys import stderr
import logging
from subprocess import CalledProcessError
from json import loads
import argparse
from pprint import pprint
from pathlib import Path
import shutil
import re

from PIL import Image, ImageOps
from nptime import nptime
from _datetime import timedelta, datetime as dt
from tmv.util import cpe2str, HH_MM, LOG_FORMAT, LOG_LEVELS, dt2str, run_and_capture, str2dt

LOGGER = logging.getLogger(__name__)

try:
    from pytesseract import image_to_string
except ImportError as exc:
    LOGGER.debug(exc)


def fps(filename):
    i = VideoInfo(filename)
    return i.fps


def valid(filename):
    i = VideoInfo(filename)
    return i.valid


def duration(filename):
    i = VideoInfo(filename)
    return i.duration


def frames(filename):
    i = VideoInfo(filename)
    return i.frames


def real_duration(filename):
    i = VideoInfo(filename)
    return i.real_duration


def real_start(filename):
    i = VideoInfo(filename)
    return i.real_start


class VideoInfo():
    """ Use ffprobe to return info about videos """

    def __init__(self, filename):
        self.filename = str(filename)
        self._info_dict = None
        self.stream = 0
        self._real_timestamps = []

    def __str__(self):
        return f"Filename:{self.filename} Stream:{self.stream} Info:{self.info_dict}"

    @property
    def info_dict(self):
        if not self._info_dict:
            try:
                cl = "ffprobe -hide_banner -v error -show_format -show_streams -print_format json".split()
                cl.append(self.filename)
                out, _ = run_and_capture(cl)
                self._info_dict = loads(out)  # json -> dict
            except:
                LOGGER.debug(f"ffprobe failed (bubbled up) in cwd: {getcwd()}")
                raise
        return self._info_dict

    @property
    def fps(self):
        nom, dom = self.info_dict['streams'][0]['avg_frame_rate'].split("/")
        return float(nom) / float(dom)

    @property
    def duration(self) -> timedelta:
        secs = float(self.info_dict['streams'][self.stream]['duration'])
        return timedelta(seconds=secs)

    @property
    def valid(self):
        try:
            return self.frames > 0
        except OSError:
            return False
        except CalledProcessError:
            return False

    @property
    def frames(self):
        return int(self.info_dict['streams'][self.stream]['nb_frames'])

    @property
    def real_duration(self) -> timedelta:
        description = self.info_dict['format']['tags']['description']  # couple with videod.py!
        _, seconds = description.split(",")
        return timedelta(seconds=int(seconds))

    @property
    def real_start(self) -> dt:
        description = self.info_dict['format']['tags']['description']  # couple with videod.py!
        dt_str, _ = description.split(",")
        return str2dt(dt_str)

    @property
    def real_timestamps(self):
        if not self._real_timestamps:
            cl = ["ffprobe", "-i", self.filename]
            cl = cl + "-show_frames -show_entries frame=pkt_pts_time -of json".split()

            out, _ = run_and_capture(cl)
            json = loads(out)
            video_frames = [float(f['pkt_pts_time']) for f in json['frames']]  # list of frame timestamps as seconds
            LOGGER.debug(f"frames:{len(video_frames)} real_start={self.real_start} real_duration={str(self.real_duration)}")

            if video_frames[0] != 0.0:
                raise NotImplementedError(f"Cannot handle non-zero start time in {self.filename}.")

            for ts_video in video_frames:
                ts_real = self.real_start + (timedelta(seconds=ts_video) / self.duration) * self.real_duration
                #LOGGER.debug(f"ts_video={ts_video:.2f} ts_real={ts_real}")
                self._real_timestamps.append(ts_real)

        return self._real_timestamps


class ManualTimes(VideoInfo):
    """ Specify the start and end time, instead of reading from the video file """

    def __init__(self, filename, real_start_time, real_interval=None, real_end_time=None, real_date=None):
        super().__init__(filename)
        if (real_interval and real_end_time) or (not real_interval and not real_end_time):
            raise RuntimeError("Use real_interval or real_end_time, not both")
        self._real_start_time = real_start_time
        self._real_interval = real_interval
        self._real_end_time = real_end_time
        if not real_date:
            self._real_date = str2dt(Path(filename).stem).date()

    @property
    def real_start(self) -> dt:
        return dt.combine(self._real_date, self._real_start_time)

    @property
    def real_duration(self) -> timedelta:
        if self._real_interval:
            return self._real_interval * self.frames
        else:
            # self._real_end_time:
            return nptime.from_time(self._real_end_time) - nptime.from_time(self._real_start_time)


def extract_dated_images(filename, output, start_time=None, end_time=None, interval=None, ocr=False):
    """
     Read a video, check metadata to understand real time and then extract images into dated files
     """
    if start_time:
        vi = ManualTimes(filename, real_start_time=start_time, real_interval=interval, real_end_time=end_time)
    else:
        vi = VideoInfo(filename)
    the_call = ["ffmpeg", "-hide_banner", "-loglevel", "verbose", "-y"]  # -y : overwrite
    the_call.extend(["-i", filename])
    # frame_pts is new and unavailable - use real_timestamps instead of:
    # the_call.extend(['-frame_pts', 'true'])
    the_call.extend(['-qscale:v', '2'])  # jpeg quality: 2-5 is good : https://stackoverflow.com/questions/10225403/how-can-i-extract-a-good-quality-jpeg-image-from-an-h264-video-file-with-ffmpeg
    the_call.extend(['%06d.jpg'])
    run_and_capture(the_call)  # throw on fail
    rx = re.compile(r'\d\d\d\d\d\d\.jpg')  # glob can't match this properly
    image_filenames = [f for f in Path(".").glob("*.jpg") if rx.match(str(f)) is not None]
    last_ts = vi.real_start
    try:
        for f in sorted(image_filenames):
            if ocr:
                im = Image.open(f)
                im_iv = ImageOps.grayscale(im)
                im_iv = ImageOps.invert(im_iv)
                im_iv = im_iv.crop((50, im.height - 100, 300, im.height))
                im_iv.save("invert.jpg")
                text = image_to_string(im_iv, config="digits")
                text = image_to_string(im_iv, lang='eng', config="-c tessedit_char_whitelist=0123456789 -oem 0")
                ts = str2dt(text, throw=False) or (last_ts + interval)
                LOGGER.debug(f"file: {f} text:{text} ts:{ts}")
                raise NotImplementedError("tesseract cannot see digits")
            else:
                ts = vi.real_timestamps[int(f.stem) - 1]

            day_dir = Path(output) / Path(dt2str(ts.date()))
            day_dir.mkdir(exist_ok=True)
            new_filename = dt2str(ts) + f.suffix
            new_path = day_dir / new_filename
            LOGGER.debug(f"file: {f} ts:{ts} new:{new_path}")
            shutil.move(str(f), str(new_path))
            last_ts = ts
    except KeyError as exc:
        KeyError(f"{exc}: cannot find metadata in {filename}?")

# pylint: disable=line-too-long, broad-except


def video_info_console():
    parser = argparse.ArgumentParser("")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument('command',
                        choices=['metadata', 'valid', 'frames', 'duration', 'fps', 'all'])
    parser.add_argument("filenames", nargs="+")

    args = (parser.parse_args())
    for filename in args.filenames:
        try:
            LOGGER.info(filename)
            vi = VideoInfo(filename)
            if args.command == 'all':
                pprint(vi.info_dict)
            else:
                if args.verbose:
                    print(f"{filename}: ", end="")
                print(getattr(vi, args.command))
        except CalledProcessError as exc:
            print(f"Exception: {exc} stdout: {exc.output} stderr: {exc.stderr}", file=stderr)
            sys.exit(2)
        except Exception as exc:
            print(f"Exception: {exc}", file=stderr)
            sys.exit(1)

    sys.exit(0)


def video_decompile_console(cl=sys.argv[1:]):
    parser = argparse.ArgumentParser("Video Decompiler", description="Extract time-stamped images from a video file.")
    parser.add_argument("filenames", nargs="+")
    parser.add_argument("--output", type=str, default=".")

    parser.add_argument('--log-level', '-ll', default='WARNING', type=lambda s: LOG_LEVELS(s).name, nargs='?', choices=LOG_LEVELS.choices())

    # parser.add_argument('--log-level', default='WARNING', dest='log_level', type=log_level_string_to_int, nargs='?',
    # help='Set the logging output level', choices=[l.name from l in list(LOG_LEVELS)]
    parser.add_argument("--start", type=lambda s: dt.strptime(s, HH_MM).time(), help="Assume video starts at this time.")
    parser.add_argument("--end", type=lambda s: dt.strptime(s, HH_MM).time(), help="Assume video ends at this time.")
    parser.add_argument("--interval", type=lambda s: timedelta(seconds=float(s)), help="Assume shutter interval of this many seconds.")
    parser.add_argument("--ocr", action='store_true')
    args = (parser.parse_args(cl))

    if args.start and not (args.interval or args.end):
        parser.error("Specify --start and --interval / --end.")
    logging.basicConfig(format=LOG_FORMAT)
    LOGGER.setLevel(args.log_level)

    for filename in args.filenames:
        try:
            LOGGER.info(filename)
            extract_dated_images(filename, args.output, start_time=args.start, end_time=args.end, interval=args.interval, ocr=args.ocr)
        except CalledProcessError as exc:
            print(f"Exception calling another process: {exc}", file=stderr)
            LOGGER.debug(cpe2str(exc), exc_info=exc)
            sys.exit(2)
        except Exception as exc:
            print(f"Exception: {exc}", file=stderr)
            LOGGER.debug(exc, exc_info=exc)
            sys.exit(1)

    sys.exit(0)
