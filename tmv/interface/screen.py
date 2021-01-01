# pylint: disable=import-outside-toplevel,protected-access, line-too-long, logging-fstring-interpolation, logging-not-lazy, unused-import
from time import sleep
from random import randrange
import logging
from collections import namedtuple
from socket import gethostname
from _datetime import datetime as dt
from pkg_resources import resource_filename
from PIL import Image, ImageFont
from PIL.ImageDraw import Draw
from tmv.config import *  # pylint: disable=wildcard-import, unused-wildcard-import
from tmv.util import wifi_ssid, strike, dt2str


LOGGER = logging.getLogger("tmv.screen")


class TMVScreen:
    """Control an adafruit eink bonnet to show tmv stats, images, etc"""

    def __init__(self, interface):
        self._display = None
        self._init_display()
        self._logo_filename = resource_filename(__name__, '../resources/tmv.png')
        self._interface = interface
        self._screen_image = None

    def test(self):
        from adafruit_epd.epd import Adafruit_EPD
        self._display.fill(Adafruit_EPD.WHITE)
        self._display.fill_rect(0, 0, randrange(20, 60), randrange(20, 60), Adafruit_EPD.BLACK)
        self._display.hline(randrange(20, 60), randrange(20, 60), randrange(20, 60), Adafruit_EPD.BLACK)
        self._display.vline(randrange(20, 60), randrange(20, 60), randrange(20, 60), Adafruit_EPD.BLACK)
        self._display.display()

    def update_display(self):
        self.update_image()
        self._display.image(self._screen_image)
        self._display.display()

    def update_image(self):
        """ Read latest image and stats, and display """
        """
                              |->     w/2            <-|
           ------------------------------------------------
           | name
           | on/off/auto
        h  | interval                   PHOTO IMAGE
           | apname
           | wifiname
           ------------------------------------------------

        """

        # make photo image
        if self._screen_image:
            # get latest image generally
            photo_image = Image.open(str(self._interface.latest_image))
            # dither
            photo_image = photo_image.convert('1') # convert image to black and white
        else:
            # show logo on first refresh
            photo_image = Image.open(str(self._logo_filename))
            # threshold
            photo_image = photo_image.point(lambda x: 0 if x<128 else 255, '1')
        
        photo_image.thumbnail((self._display.width // 2, self._display.height))
        

        # make full screen size image
        self._screen_image = Image.new('RGB', (self._display.width, self._display.height))
        self._screen_image.paste(photo_image, (self._display.width // 2, (self._display.height - photo_image.height) // 2))

        # make LHS info bit
        fg_colour = (0, 0, 0)
        bg_colour = (255, 255, 255)
        info_image = Image.new('RGB', (self._display.width - photo_image.width, self._display.height), color=bg_colour)
        info_image_draw = Draw(info_image)
        text_size = 22
        small_text_size = 13
        line_height = text_size + 1
        small_line_height = small_text_size + 1
        font = ImageFont.truetype(FONT_FILE, text_size, encoding='unic')
        small_font = ImageFont.truetype(FONT_FILE, small_text_size, encoding='unic')

        lines = [gethostname(),
                 str(self._interface.mode_button.value),
                 f"{int(self._interface.interval.total_seconds())}s",
                 f"{self._interface.n_images()} images"]

        xy = (0, 0)
        for line in lines:
            info_image_draw.text(xy=xy, text=line, fill=fg_colour, font=font)
            xy = (xy[0], xy[1] + line_height)

        try:
            latest_str = dt2str(self._interface.latest_image_time)
        except Exception:  # pylint: disable=broad-except
            latest_str = ""

        lines = [wifi_ssid() or "no wifi",
                 latest_str]
        for line in lines:
            info_image_draw.text(xy=xy, text=line, fill=fg_colour, font=small_font)
            xy = (xy[0], xy[1] + small_line_height)

        self._screen_image.paste(info_image, (0, 0))

    def screen_image_save(self):
        fn = "screen_image.png"
        self._screen_image.save(fn)
        return fn

    def _init_display(self):
        try:
            import digitalio
            import busio
            import board
            from adafruit_epd.epd import Adafruit_EPD
            from adafruit_epd.ssd1675 import Adafruit_SSD1675

            spi = busio.SPI(board.SCK, MOSI=board.MOSI, MISO=board.MISO)
            ecs = digitalio.DigitalInOut(board.CE0)
            dc = digitalio.DigitalInOut(board.D22)
            rst = digitalio.DigitalInOut(board.D27)
            busy = digitalio.DigitalInOut(board.D17)
            srcs = None
            # 2.13" HD mono display
            self._display = Adafruit_SSD1675(122, 250, spi, cs_pin=ecs, dc_pin=dc, sramcs_pin=srcs, rst_pin=rst, busy_pin=busy,)
            self._display.rotation = 1
            LOGGER.debug("Adafruit_SSD1675 screen ready")
        except (NameError, ImportError) as e:
            LOGGER.error(f"Could not create a screen: {e}")
            LOGGER.debug("Could not create a screen", exc_info=e)


if __name__ == '__main__':
    print("h1")
    screen = TMVScreen(None)
    screen.update_image()
    screen.update_display()
    sleep(5)
