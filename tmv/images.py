""" Stuff to generate and modify images """
# pylint: disable=line-too-long, logging-fstring-interpolation, dangerous-default-value, logging-not-lazy
from datetime import timedelta, datetime as dt
import sys
import logging
import argparse
from pathlib import Path
import os
from pkg_resources import resource_filename
from PIL import Image, ImageColor, ImageDraw, ImageFont
from tmv.video import VideoMakerConcat
from tmv.util import LOG_FORMAT, LOG_LEVELS, dt2str, HH_MM

LOGGER = logging.getLogger(__name__)

try:
    from datetimerange import DateTimeRange  # optional, for 'gen'
except ImportError as exc:
    LOGGER.debug(exc)


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
        font_path = resource_filename(__name__, 'resources/FreeSans.ttf')
        LOGGER.debug(f"font_path={font_path}")
        font = ImageFont.truetype(font_path, text_size, encoding='unic')
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


def generate_cal_images(period=timedelta(days=365), step=timedelta(hours=1)):
    """ One per hour with a "x" and label"""
    start = dt(2000, 1, 1, 0, 0, 0)
    end = start + period
    time_range = DateTimeRange(start, end)
    for instant in time_range.range(step):
        f = Path(dt2str(instant) + ".jpg")
        im = Image.new("RGB", (320, 200))
        overlay = CalenderOverlay(im, instant)
        overlay.apply()
        overlay = Label(im, str(f))
        overlay.apply()
        im.save(f)
        im.close()

# pylint: disable=dangerous-default-value,
def image_tools_console(cl_args=sys.argv[1:]):
    parser = argparse.ArgumentParser("TMV Image Tools", description="Manipulate and get information about timelapse images.")
    parser.add_argument("command", choices=['rename', 'addexif', 'stamp', 'graph', 'cal', 'rm'])
    parser.add_argument("file_glob", nargs='?')
    parser.add_argument('--log-level', '-ll', default='WARNING', type=lambda s: LOG_LEVELS(s).name, nargs='?', choices=LOG_LEVELS.choices())
    parser.add_argument("--start-time", type=lambda s: dt.strptime(s, HH_MM).time(), default="00:00")
    parser.add_argument("--end-time", type=lambda s: dt.strptime(s, HH_MM).time(), default="23:59")
    parser.add_argument("--output", type=str)
    parser.add_argument("--graph-interval", default=10, type=int, help="Using wih graph command. In minutes.")
    parser.add_argument('--start', default=dt.min, type=lambda s: dt.strptime(s, '%Y-%m-%dT%H:%M:%S'),
                        help="First image to consider. Format: 2010-12-01T13:00:01")
    parser.add_argument('--end', default=dt.max, type=lambda s: dt.strptime(s, '%Y-%m-%dT%H:%M:%S'),
                        help="Last image to consider. Format: 2010-12-01T13:00:01")

    args = (parser.parse_args(cl_args))
    LOGGER.setLevel(args.log_level)
    logging.basicConfig(format=LOG_FORMAT)

    try:

        if args.command == "cal":
            if args.output:
                Path(args.output).mkdir(exist_ok=True)
                os.chdir(args.output)
            generate_cal_images()
        else:
            mm = VideoMakerConcat()
            mm.configure(args)
            mm.load_videos()
            if args.command == "rename":
                mm.rename_images()
            elif args.command == "addexif":
                raise NotImplementedError()
            elif args.command == "stamp":
                mm.stamp_images()
            elif args.command == "graph":
                mm.graph_intervals(timedelta(minutes=args.graphinterval))
            else:
                pass
    # pylint: disable=broad-except
    except BaseException as exc:
        LOGGER.error(exc)
        LOGGER.debug(exc, exc_info=exc)
        sys.exit(1)

    sys.exit(0)
