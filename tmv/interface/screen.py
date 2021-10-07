# pylint: disable=import-outside-toplevel,protected-access, line-too-long, logging-fstring-interpolation, logging-not-lazy, unused-import
from time import sleep
from random import randrange
import threading
import logging
from datetime import datetime as dt, timedelta
from collections import namedtuple
from socket import gethostname

from gpiozero import Button
from luma.oled.device import sh1106
from luma.core.interface.serial import spi
from pkg_resources import resource_filename
from PIL import Image, ImageFont
from PIL.ImageDraw import Draw

from tmv.config import *  # pylint: disable=wildcard-import, unused-wildcard-import
from tmv.util import wifi_ssid, strike, dt2str, uptime

LOGGER = logging.getLogger("tmv.screen")

class TMVScreen:
    """ Any screen should subclass and implement _init_display and update_display()
    """

    def __init__(self, interface):
        self._display = None
        self._logo_filename = resource_filename(__name__, '../resources/tmv.png')
        self._interface = interface
        self._screen_image = None
        self.shutdown = False
        self._init_display()

    def start(self):
        self.update_thread_ref = threading.Thread(target=self.update_thread)
        self.update_thread_ref.start()
    
    def update_display(self):
        raise NotImplementedError()

    def _init_display(self):
        raise NotImplementedError()
      

    def update_thread(self):
        """
        Display key parameters and image on the screen and react to screen button presses
        """
        next_screen_refresh = dt.now()
        refresh_period = timedelta(seconds=0.1)
        
        while not self.shutdown:
            if dt.now() > next_screen_refresh:
                self.update_display()
                next_screen_refresh = dt.now() + refresh_period
            else:
                sleep(refresh_period.total_seconds())



class OLEDScreen(TMVScreen):
    """SH1106 screen with joystick. Carosel display of status / image via joystick.
       Note On/Off and Speed buttons are handled elsewhere.

    Args:
        TMVScreen ([type]): [description]
    """
    KEY_UP_PIN = 6
    KEY_DOWN_PIN = 19
    KEY_LEFT_PIN = 5
    KEY_RIGHT_PIN = 26
    KEY_PRESS_PIN = 13

    KEY1_PIN = 21
    KEY2_PIN = 20
    KEY3_PIN = 16

    def __init__(self, interface):
        super().__init__(interface)
        self.pages = 2
        self.page = 1

        try:
            # https://stackoverflow.com/questions/42732221/how-can-i-use-the-gpiozero-button-when-pressed-function-to-use-a-function-that-i/44746381
            self.key_right = Button(self.KEY_RIGHT_PIN, hold_repeat=True)
            self.key_right.when_pressed = lambda: self.turn_page(self.key_right, forward=True)
            self.key_left = Button(self.KEY_LEFT_PIN, hold_repeat=True)
            self.key_left.when_pressed = lambda: self.turn_page(self.key_left, backward=True)
        except RuntimeError as e:
            # Probably not on a pi
            print(e)

        self.start()
        

    def turn_page(self, button, forward=False, backward=False):
        #print([self, button, forward, backward, self.page])
        self.page += forward * 1 + backward * -1
        if self.page < 1:
            self.page = self.pages 
        if self.page > self.pages:
            self.page = 1

    def update_display(self):
        from luma.core.render import canvas
        with canvas(self._display) as draw:
            W = draw.im.size[0]
            H = draw.im.size[1]
            fg_colour = "white"
            text_size = 12
            small_text_size = 8
            line_height = text_size + 1
            small_line_height = small_text_size + 1
            font = ImageFont.truetype(FONT_FILE, text_size, encoding='unic')
            small_font = ImageFont.truetype(FONT_FILE, small_text_size, encoding='unic')

            try:
                latest_str = dt2str(self._interface.latest_image_time)
                latest_str_day = latest_str.split("T")[0]
                latest_str_time = latest_str.split("T")[1]
            except Exception:  # pylint: disable=broad-except
                latest_str = ""
                latest_str_day = ""
                latest_str_time = ""
                

            if self.page == 1:
                lines = [
                    f"Mode: {str(self._interface.mode_button.value)}",
                    f"Int : {int(self._interface.interval.total_seconds())}s ({self._interface.speed_button.value})",
                    
                    f"Imgs: {self._interface.n_images()} images",
                    f"Date: {latest_str_day}",
                    f"Time: {latest_str_time}"]
                xy = (0, 0)
                for line in lines:
                    draw.text(xy=xy, text=line, fill="white", font=font)
                    xy = (xy[0], xy[1] + line_height)

                # RHS
                #print ((self._interface.camera_activity.value,self._interface.camera_activity.value==ON))
                if self._interface.camera_activity.value == ON:
                    draw.arc([(W-10,0),(W-1,10-1)],start=0,end=360,fill='white')


            elif self.page == 2:
                lines = [ f"Name  : {gethostname()}",
                          f"Images: {self._interface.n_images()}",
                          f"Wifi  : {wifi_ssid()}",
                          f"Uptime: {uptime():.0f}"]
                xy = (0, 0)
                for line in lines:
                    draw.text(xy=xy, text=line, fill="white", font=font)
                    xy = (xy[0], xy[1] + line_height)

    def _init_display(self):
        try:
            serial = spi(device=0, port=0)
            self._display = sh1106(serial, rotate=2)  # 2 = 180deg
        except (NameError, ImportError) as e:
            LOGGER.error(f"luma library not installed? Exception: {e}")

    def button_update_thread(self):
        pass
        # while True:
        #    if not GPIO.input(self.KEY_RIGHT_PIN)


"""
class FakeOLEDScreen(OLEDScreen):
    def _init_display(self):
        from luma.emulator.device import capture, gifanim
        # gif
        self._gif = ''.join(random.choices(string.ascii_uppercase + string.digits, k=3)) + ".gif"
        self._display = gifanim(filename= self._gif, duration=0.1)#,mode="1")
        # images
        #self._display = capture()
        return
"""


class EInkScreen(TMVScreen):
    """Control an adafruit eink bonnet to show tmv stats, images, etc"""

    def test(self):
        try:
            from adafruit_epd.epd import Adafruit_EPD
            self._display.fill(Adafruit_EPD.WHITE)
            self._display.fill_rect(0, 0, randrange(20, 60), randrange(20, 60), Adafruit_EPD.BLACK)
            self._display.hline(randrange(20, 60), randrange(20, 60), randrange(20, 60), Adafruit_EPD.BLACK)
            self._display.vline(randrange(20, 60), randrange(20, 60), randrange(20, 60), Adafruit_EPD.BLACK)
            self._display.display()
        except (NameError, ImportError) as e:
            LOGGER.error(f"Could not create a screen: {e}")
            LOGGER.debug("Could not create a screen", exc_info=e)

    def update_display(self):
        self.update_image()
        self._display.image(self._screen_image)
        self._display.display()

    def update_image(self):
        """ Read latest image and stats, and display 
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
            photo_image = photo_image.convert('1')  # convert image to black and white
        else:
            # show logo on first refresh
            photo_image = Image.open(str(self._logo_filename))
            # threshold
            photo_image = photo_image.point(lambda x: 0 if x < 128 else 255, '1')

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
    screen = EInkScreen(None)
    screen.update_image()
    screen.update_display()
    sleep(5)
