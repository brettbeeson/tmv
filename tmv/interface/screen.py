# pylint: disable=import-outside-toplevel,protected-access, line-too-long, logging-fstring-interpolation, logging-not-lazy, unused-import
from os import system
from time import sleep
import threading
import logging
from sys import stderr
from datetime import datetime as dt, timedelta
from socket import gethostname

from tmv.interface.app import shutdown_hw

LOGGER = logging.getLogger("tmv.screen")

from pkg_resources import resource_filename
from PIL import Image, ImageFont
from PIL.ImageDraw import Draw
try:
    from tmv.tmvpijuice import TMVPiJuice, pj_call
except ModuleNotFoundError as e:
    LOGGER.warning(f"pijuice not available: {e}")
try:
    from gpiozero import Button
    from luma.oled.device import sh1106  # pylint: disable=no-name-in-module, import-error
    from luma.core.interface.serial import spi
except ModuleNotFoundError as e:
    LOGGER.warning(f"luma or gpiozero not installed: {e}")

from tmv.config import *  # pylint: disable=wildcard-import, unused-wildcard-import
from tmv.exceptions import PiJuiceError
from tmv.util import shutdown, wifi_ssid, strike, dt2str, uptime


class TMVScreen:
    """ Any screen should subclass and implement _init_display and update_display()
    """

    def __init__(self, interface):
        self._display = None
        self._logo_filename = resource_filename(__name__, '../resources/tmv.png')
        self._interface = interface
        self._screen_image = None
        self.shutdown = False
        self.update_thread_ref = None
        self.last_button_press = dt.now()  # used to determine auto-dim
        self.auto_off_interval = timedelta(seconds=60)
        self._init_display()
        self.hidden = False

    def start(self):
        self.update_thread_ref = threading.Thread(target=self.update_thread, daemon=True)
        self.update_thread_ref.start()

    def stop(self):
        self.shutdown = True
        self.update_thread_ref.join()
        self.update_thread_ref = None

    def update_display(self):
        raise NotImplementedError()

    def _init_display(self):
        raise NotImplementedError()

    def update_thread(self):
        """
        Display key parameters and image on the screen and react to screen button presses
        We're not updating on 'mark' but sleeping fixed amount: prioritize low CPU
        """

        while not self.shutdown:

            if dt.now() < self.last_button_press + self.auto_off_interval:
                # button recently pressed: wakeup if required; show screen
                if self.hidden:
                    self._display.show()
                    self.hidden = False
                try:
                    self.update_display()
                except RuntimeError as exc:
                    LOGGER.warning(exc)    
            else:
                # sleep mode
                if not self.hidden:
                    self.hidden = True
                    self._display.hide()
            sleep(1.0)
        LOGGER.debug("update_thread received shutdown: stopping ")


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

            #self.key_up = Button(self.KEY_UP_PIN)
            #self.key_up.when_pressed = self._display.hide
            self.key_down = Button(self.KEY_DOWN_PIN)
            self.key_down.hold_time = 3
            self.key_down.when_held = shutdown

        except RuntimeError as ex:
            # Probably not on a pi
            LOGGER.error(ex)

        self.start()

    def stop(self):
        # unless we manually cleanup Buttons (gpiozero), we can a 'reusing pin' error
        super().stop()
        LOGGER.debug("OLEDScreen stopped")
        #self._display.cleanup()  # redundant accortding to https://luma-oled.readthedocs.io/en/latest/api-documentation.html#luma.oled.device.ssd1306.cleanup
        # redundant too?
        #self.key_right.close()
        #self.key_left.close()

    def turn_page(self, __button, forward=False, backward=False):
        self.page += forward * 1 + backward * -1
        if self.page < 1:
            self.page = self.pages
        if self.page > self.pages:
            self.page = 1
        self.last_button_press = dt.now()

    def update_display(self):
        # todo: add a _display.hide() when not in use
        from luma.core.render import canvas
        with canvas(self._display) as draw:
            W = draw.im.size[0]
            #H = draw.im.size[1]
            text_size = 12
            #small_text_size = 8
            line_height = text_size + 1

            font = ImageFont.truetype(FONT_FILE_SCREEN, text_size, encoding='unic')

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
                if self._interface.activity.value == ON:
                    draw.arc([(W - 10, 0), (W - 1, 10 - 1)], start=0, end=360, fill='white')

            elif self.page == 2:
                lines = [f"Name  : {gethostname()}",
                         f"Wifi  : {wifi_ssid()}",
                         f"Uptime: {uptime()/60:.0f}m"]
                if self._interface.has_pijuice:
                    try:
                        tmv_pj = TMVPiJuice()
                        s = pj_call(tmv_pj.status.GetStatus)
                        s['chargeLevel'] = pj_call(tmv_pj.status.GetChargeLevel)
                        lines.append(f"Batt  : {s['chargeLevel']}")
                        lines.append(f"Juice : {s['battery']}")
                    except (NameError, PiJuiceError) as ex:
                        LOGGER.warning(ex, exc_info=ex)

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
