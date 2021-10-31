# pylint: disable=broad-except,logging-fstring-interpolation,logging-not-lazy, dangerous-default-value
"""
File-underlied 2- and 3-value buttones with hardware buttons and LEDs
"""
from sys import stderr
import sys
import logging
from time import sleep
from pathlib import Path
from datetime import timedelta
from _datetime import datetime as dt

import toml
# to enable monkeypatching, don't import "from tmv.util", but instead:
from tmv.util import Tomlable, LOG_FORMAT
from tmv.exceptions import ButtonError
from tmv.circstates import StatesCircle
from tmv.config import *  # pylint: disable=wildcard-import, unused-wildcard-import

try:
    from gpiozero import Button
    from gpiozero import LED
except (ImportError, NameError) as exc:
    print(exc)

LOGGER = logging.getLogger("tmv.button")


class StatefulButton(StatesCircle, Tomlable):
    """
    mode is controlled by file and/or pushbutton, with optional LED indicator
    - if unlit, the first push will just illuminate (not change state)
    - pushes when illuminated change state
    - it will return to unlit after a time
    """

    def __str__(self):
        return f"StatefulButton: {vars(self)}"

    def __repr__(self):
        return f"StatefulButton: {vars(self)}"

    def ready(self):
        return self.path is not None

    def illuminate(self):
        pass
    
    def configd(self, config_dict):
        if 'button' in config_dict:
            c = config_dict['button']
        else:
            c = config_dict
        LOGGER.debug(f"button config: {c}")
        if 'file' in c:
            self.path = Path(c['file'])


class StatefulHWButton(StatefulButton):
    """Cycling mode button with an LED and button

    Args:
        StatefulHWButton ([type]): [description]
    """

    def __init__(self, path, states, led_pin=None, button_pin=None, fallback=None):
        super().__init__(path, states, fallback)
        self.button = None
        self.led = None
        self.lit_for = None
        self.last_pressed = dt.min
        self.button = None
        self.led = None
        try:
            # only works on raspi
            if button_pin:
                self.button = Button(button_pin)
                self.button.when_pressed = self.push
            if led_pin:
                self.led = LED(led_pin)

        except Exception as e:
            LOGGER.warning(f"Exception but continuing:{e}")
            LOGGER.debug(f"Exception but continuing:{e}", exc_info=True)

    def __str__(self):
        return f"StatefulHWButton: {vars(self)}"

    def __repr__(self):
        return f"StatefulHWButton: {vars(self)}"

    def illuminate(self):
        """ Don't change, just illuminate """
        self.last_pressed = dt.now()
        self.set_LED()

    def push(self):
        """
        Resets the dormancy counter.
        """
        #LOGGER.debug("button pushed!")

        moment = dt.now()

        if self.lit_for is None or moment < self.last_pressed + self.lit_for:
            # active: change state
            next(self)
        self.set_LED()
        self.last_pressed = dt.now()

    def set_LED(self):
        if not self.led:
            return
        current = self.value
        try:
            led_on_time = current.on_time
            led_off_time = current.off_time
            one_n = led_on_time + led_off_time
            # LOGGER.debug(f"set_LED; {vars(self)}")
            if self.lit_for is None:
                self.led.blink(on_time=led_on_time, off_time=led_off_time)
            else:
                led_n = int(self.lit_for.total_seconds() / one_n)
                self.led.blink(on_time=led_on_time, off_time=led_off_time, n=led_n)
        except KeyError as exc:
            raise ButtonError("check set_LED") from exc

    def configd(self, config_dict):
        if 'button' in config_dict:
            c = config_dict['button']
        else:
            c = config_dict
        LOGGER.debug(f"button config: {c}")
        self.path = Path(c['file'])
        self.button = Button(c['button'])
        self.button.when_pressed = self.push
        self.led = LED['led']
        LOGGER.debug(f"button configd: {self.path}, button: {self.button}, led: {self.led}")
        # self.value() # update from new file
        self.set_LED()


def button_test(i):
    global MODE_LED  # pylint: disable= global-statement

    print (f"Test {i}")

    if i == 1:
        speed = StatefulHWButton(SPEED_FILE, SPEED_BUTTON_STATES, SPEED_LED, SPEED_BUTTON)
        speed.lit_for = timedelta(seconds=5)
        speed.push()

        mode = StatefulHWButton(MODE_FILE, MODE_BUTTON_STATES, MODE_LED, MODE_BUTTON)
        mode.lit_for = timedelta(seconds=5)
        mode.push()

        print("lit: 5s")
        sleep(60)

        speed.lit_for = None
        speed.set_LED()
        mode.lit_for = None
        mode.set_LED()
        print("lit: inf")
        sleep(60)

    elif i == 2:

        MODE_LED = 18
        button_test(1)

    elif i == 3:

        camera = toml.load("camera.toml")['camera']
        print(Path("camera.toml").absolute())
        speed = StatefulHWButton(SPEED_FILE, SPEED_BUTTON_STATES, SPEED_LED, SPEED_BUTTON)
        speed.configd(camera['mode_button'])
        speed.lit_for = timedelta(seconds=5)
        mode = StatefulHWButton(MODE_FILE, MODE_BUTTON_STATES, MODE_LED, MODE_BUTTON)
        mode.configd(camera['speed-button'])
        mode.lit_for = timedelta(seconds=5)
        print("lit: 5s")

    print("done")


if __name__ == "__main__":
    # breakpoint()
    logging.getLogger("tmv").setLevel(logging.DEBUG)
    logging.basicConfig(format=LOG_FORMAT, level=logging.DEBUG)
    button_test(int(sys.argv[1]))
