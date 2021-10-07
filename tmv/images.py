""" Stuff to generate and modify images """
# pylint: disable=line-too-long, logging-fstring-interpolation, dangerous-default-value, logging-not-lazy
from datetime import timedelta, datetime as dt
import sys
import glob
import logging
import argparse
from pathlib import Path
import os
from dateutil.rrule import rrule, SECONDLY
from PIL import Image, ImageColor, ImageDraw, ImageFont
from tmv.video import SliceType, VideoMaker
from tmv.util import LOG_FORMAT, LOG_LEVELS, dt2str, next_mark, prev_mark, strptimedelta
from tmv.config import FONT_FILE, HH_MM

LOGGER = logging.getLogger("tmv.images")

try:
    from ascii_graph import Pyasciigraph  # optional, for 'graph'
except ImportError as exc:
    # print(exc)
    pass


def stamp(filename, ith):
    """ Draw a moving circle on the image for continuity in video checking """
    assert os.path.exists(filename)
    img = Image.open(filename)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_FILE, 20)
    draw.pieslice([(0, 0), (100, 100)], ith % 360, ith % 360, fill=None, outline=None)
    draw.arc([(0, 0), (100, 100)], 0, 360)
    w, h = img.size
    # draw.text((  (self.ith*10) % w, h - 10), "*", (255, 255, 255), font=font)
    draw.text((w - 40, h - 40), str(ith), (255, 255, 255), font=font)
    draw.text((w - 300, h - 60), filename, (255, 255, 255), font=font)
    LOGGER.debug("Stamping: {} : {}x{}".format(filename, w, h))
    img.save(filename, )


def rename_to_exif_datetime(filename, pattern="%Y-%m-%dT%H-%M-%S"):
    """ Get the exif date and rename the file to a pattern based on that

    Args:
        filename (str): [description]
        pattern (str, optional): Rename to this pattern with exif date
    """
    dtt = exif_datetime_taken(filename)
    date_filename = os.path.join(os.path.dirname(filename),
                                 dtt.strftime(pattern) + os.path.splitext(filename)[1])
    LOGGER.debug("Renaming {} to {}".format(filename, date_filename))
    os.rename(filename, date_filename)


def graph_intervals(tl_videos, interval=timedelta(hours=1)):
    """
     Plot ascii frequency of photos per bin
    """
    bins = {}
    for video in tl_videos:
        # round bin start
        start = prev_mark(interval, video.start)
        end = next_mark(interval, video.end)

        # generate a list of marks
        video_extents = list(rrule(SECONDLY, dtstart=start, until=end, interval=int(interval.total_seconds())))

        for bin_start in video_extents:
            images_in_slice = [im for im in video.images if bin_start <= im.taken < bin_start + interval]
            bins[bin_start] = len(images_in_slice)

        graphable = []
        for h in sorted(bins):
            # print("{}:{}".format(h,freq[h]))
            graphable.append(tuple((h.isoformat(), bins[h])))
            # print (graphable)
        graph = Pyasciigraph()

    for line in graph.graph('Frequency per {}'.format(interval), graphable):
        print(line)


class Overlay():
    """ Put pixels on an image """

    def __init__(self, im: Image):
        self.im = im


class Label(Overlay):
    """ Write name of image on the bottom """

    def __init__(self, im: Image, label: str):
        super().__init__(im)
        self.label = label

    def apply(self):
        draw = ImageDraw.Draw(self.im)
        text = self.label
        text_size = 10
        font = ImageFont.truetype(FONT_FILE, text_size, encoding='unic')
        # Get the size of the time to write, so we can correctly place it
        text_box_size = draw.textsize(text=text, font=font)
        # centre text
        x = int((self.im.width / 2) - (text_box_size[0] / 2))
        # place one line above bottom
        y = (self.im.height - text_box_size[1] * 2)
        draw.text(xy=(x, y), text=text, font=font)


class CalenderOverlay(Overlay):
    """
    Add an "+" on a 'calendar' graph:

        D1, D2, D3 ... D365
    H0
    H1       +
    H2
    ...
    H23
    """

    def __init__(self, im: Image, instant):
        super().__init__(im)
        self.instant = instant

    def apply(self):
        # X axis: 0-365, Y axis 0-24
        julian_day = self.instant.timetuple().tm_yday
        day_fraction = self.instant.time().hour / 24 + self.instant.time().minute / 3600
        x = (julian_day - 1) / 365.0 + day_fraction / 365
        y = day_fraction
        # map this [0,1] to image
        x *= self.im.width
        y *= self.im.height
        draw = ImageDraw.Draw(self.im)
        ch = self.im.width // 50

        color = ImageColor.getrgb('red')
        width = max(1, ch // 10)
        draw.line([x - ch / 2, y, x + ch / 2, y], width=width, fill=color)
        draw.line([x, y - ch / 2, x, y + ch / 2], width=width, fill=color)
        draw.rectangle([0, 0, self.im.width - 1, self.im.height - 1])


def generate_cal_cross_images(output=Path("."), period=timedelta(days=365), step=timedelta(hours=1)):
    """ One per hour with a "x" and label"""
    start = dt(2000, 1, 1, 0, 0, 0)
    end = start + period
    # generate marks at regular intervals
    time_range = list(rrule(SECONDLY, dtstart=start, until=end, interval=int(step.total_seconds())))
    for instant in time_range:
        f = output / Path(dt2str(instant) + ".jpg")
        im = Image.new("RGB", (320, 200))
        overlay = CalenderOverlay(im, instant)
        overlay.apply()
        overlay = Label(im, str(f))
        overlay.apply()
        im.save(f)
        im.close()


def cal_cross_images(rootpath: Path) -> Path:
    d = rootpath / "cal-cross-365days1h"
    if not (d / "2000-01-01T00-00-00.jpg").is_file():
        d.mkdir(exist_ok=True)
        generate_cal_cross_images(d)
    return d


def exif_datetime_taken(fn):
    """returns the image date from image (if available)
      https://orthallelous.wordpress.com/2015/04/19/extracting-date-and-time-from-images-with-python/"""
    std_fmt = '%Y:%m:%d %H:%M:%S.%f'
    # for subsecond prec, see doi.org/10.3189/2013JoG12J126 , sect. 2.2, 2.3
    tags = [(36867, 37521),  # (DateTimeOriginal, SubsecTimeOriginal)
            (36868, 37522),  # (DateTimeDigitized, SubsecTimeDigitized)
            (306, 37520), ]  # (DateTime, SubsecTime)
    exif = Image.open(fn)._getexif()  # pylint: disable=protected-access
    print(exif)
    for t in tags:
        dat = exif.get(t[0])
        subsub = exif.get(t[1], 0)
        
        # PIL.PILLOW_VERSION >= 3.0 returns a tuple
        dat = dat[0] if isinstance(dat,tuple) else dat
        subsub = subsub[0] if isinstance(subsub, tuple) else subsub
        if dat is not None:
            break

    if dat is None:
        return None
    full = '{}.{}'.format(dat, subsub)
    T = dt.strptime(full, std_fmt)
    #T = time.mktime(time.strptime(dat, '%Y:%m:%d %H:%M:%S')) + float('0.%s' % sub)
    return T


# pylint: disable=dangerous-default-value,
def image_tools_console(cl_args=sys.argv[1:]):
    parser = argparse.ArgumentParser("TMV Image Tools", description="Manipulate and query timelapse images.")
    parser.add_argument("command", choices=['rename', 'addexif', 'stamp', 'graph', 'cal', 'rm'])

    parser.add_argument('--log-level', '-ll', default='WARNING', type=lambda s: LOG_LEVELS(s).name, nargs='?', choices=LOG_LEVELS.choices())
    parser.add_argument("--start-time", type=lambda s: dt.strptime(s, HH_MM).time(), default="00:00")
    parser.add_argument("--end-time", type=lambda s: dt.strptime(s, HH_MM).time(), default="23:59")
    #parser.add_argument("--output", type=str)
    parser.add_argument("--slice", choices=SliceType.names(), default="Concat")

    parser.add_argument("--bin", default=timedelta(hours=1), type=strptimedelta, help="Using wih graph command. e.g '1 day', 1 hour'")
    parser.add_argument('--start', default=dt.min, type=lambda s: dt.strptime(s, '%Y-%m-%dT%H:%M:%S'), help="First image to consider. Format: 2010-12-01T13:00:01")
    parser.add_argument('--end', default=dt.max, type=lambda s: dt.strptime(s, '%Y-%m-%dT%H:%M:%S'),
                        help="Last image to consider. Format: 2010-12-01T13:00:01")
    parser.add_argument("file_glob")
    args = (parser.parse_args(cl_args))
    logging.getLogger("tmv").setLevel(args.log_level)
    logging.basicConfig(format=LOG_FORMAT)

    try:

        if args.command == "cal":
            # if args.output:
            #    Path(args.output).mkdir(exist_ok=True)
            #    os.chdir(args.output)
            generate_cal_cross_images()
        elif args.command == "rename":
            for f in glob.glob(args.file_glob):
                rename_to_exif_datetime(f)
        else:
            #mm = VideoMakerConcat()
            mm = VideoMaker.Factory(args.slice.title())

            mm.files_from_glob(args.file_glob)
            mm.start = args.start
            mm.end = args.end
            mm.start_time = args.start_time
            mm.end_time = args.end_time

            mm.load_videos()

#            if args.command == "rename":
#                mm.rename_images()
            if args.command == "addexif":
                raise NotImplementedError()
            elif args.command == "stamp":
                mm.stamp_images()
            elif args.command == "graph":
                graph_intervals(mm.videos, args.bin)
            else:
                pass
    # pylint: disable=broad-except
    except BaseException as exc:
        LOGGER.error(exc)
        LOGGER.debug(exc, exc_info=exc)
        sys.exit(1)

    sys.exit(0)
