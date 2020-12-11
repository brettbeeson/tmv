# pylint: disable=broad-except,logging-fstring-interpolation,logging-not-lazy, dangerous-default-value
""" 
File-underlied 2- and 3-value buttones with hardware buttons and LEDs
"""
from sys import stderr
from enum import Enum
import logging
#from  debugpy import breakpoint
from pathlib import Path
from datetime import timedelta
from _datetime import datetime as dt
from time import sleep 
# to enable monkeypatching, don't import "from tmv.util", but instead:
from tmv.util import SoftHard, SOFTWARE, HARDWARE, Tomlable, LOG_FORMAT

try:
    from gpiozero import Button
    from gpiozero import LED
except (ImportError, NameError) as exc:
    print(exc)

LOGGER = logging.getLogger("tmv.button")


class Speed(Enum):
    """ Trimatic """
    SLOW = 'slow'
    MEDIUM = 'medium'
    FAST = 'fast'

    def __str__(self):
        return str(self.value)


# Shortcuts
SLOW = Speed.SLOW
MEDIUM = Speed.MEDIUM
FAST = Speed.FAST


class AdvancedButton(Tomlable):
    """ 
    mode is controlled by file and/or pushbutton, with optional LED indicator
    - if unlit, the first push will just illuminate (not change state)
    - pushes when illuminated change state
    - it will return to unlit after a time
    """

    def __init__(self, firmness: SoftHard):
        super().__init__()
        self.button_path = None
        self.button = None
        self.led = None
        self.lit_for = timedelta(seconds=20)  # seconds to display status for. 0 for always
        self.last_pressed = dt.min
        self.firmness = firmness

    def ready(self):
        return self.button_path is not None

   
    def set(self, button_path=None, button_pin=None, led_pin=None):
        if button_path:
            self.button_path = Path(button_path)
        try:
            # only works on raspi
            if button_pin and self.firmness==HARDWARE:
                self.button = Button(button_pin)
                self.button.when_pressed = self.push
            if led_pin and self.firmness==HARDWARE:
                self.led = LED(led_pin)
        except Exception as e:
            print(f"Exception but continuing:{e}", file=stderr)

        self.push()          # first push will illuminate, not change

    def push(self) -> bool:
        """
        Call with super().push() before your implementation
        Resets the dormancy counter. 
        Returns True if push was active (act upon) or False if it was dormant (ignore via return)
        """
        LOGGER.debug(f"{self}: pushed")
        if self.lit_for is None:
            # always on
            LOGGER.debug(f"{self}: always on")
            return True
        was_lit = dt.now() < self.last_pressed + self.lit_for
        self.last_pressed = dt.now()
        return was_lit

    def led_on(self):
        if self.lit_for is None:
            self.led.on()
        else:
            self.led.blink(1,0,int(self.lit_for.total_seconds()))

    def led_off(self):
        self.led.off()

    def led_blink(self,led_on_time: float, led_off_time: float):

        if self.lit_for is None:
            self.led.blink(on_time=led_on_time,off_time=led_off_time)
        else:
            one_n = led_on_time + led_off_time
            led_n = int(self.lit_for.total_seconds() / one_n)
            self.led.blink(on_time=led_on_time,off_time=led_off_time, n = led_n)

    def __str__(self):
        return f"AdvancedButton ({self.button_path}): {self.value}"

    def __repr__(self):
        return f"AdvancedButton ({self.button_path}): {self.value}"

    def configd(self, config_dict):
        if 'button' in config_dict:
            c = config_dict['button']
        else:
            c = config_dict
        LOGGER.debug(f"button config: {c}")
        if 'file' in c:
            self.button_path = Path(c['file'])
        if 'buttonpin' in c:
            self.button = Button(c['pin'])
            self.button.when_pressed = self.push
        if 'ledpin' in c:
            self.led = LED['ledpin']
        LOGGER.debug(f"button configd: {self.button_path}, button: {self.button}, led: {self.led}")

    @property
    def value(self):
        """
        Get button state. If no file exists, create it and default.
        """
        raise NotImplementedError

    @value.setter
    def value(self, state):
        raise NotImplementedError


class OnOffAuto(Enum):
    """ Like a machine button toggle  """
    ON = 'on'
    OFF = 'off'
    AUTO = 'auto'

    def __str__(self):
        return str(self.value)


# Shortcuts
ON = OnOffAuto.ON
OFF = OnOffAuto.OFF
AUTO = OnOffAuto.AUTO


class ModeButton(AdvancedButton):
    """ ON/OFF/AUTO controlled by file and/or pushbutton, with optional LED indicator """

    def __init__(self, firmness):
        super().__init__(firmness)
        self.value = OFF

    def push(self):
        if super().push():
            # was lit : change mode
            if self.value == ON:
                self.value = OFF
            elif self.value == OFF:
                self.value = AUTO
            elif self.value == AUTO:
                self.value = ON

        
        if self.led:
            LOGGER.debug(f"{self}: set led {self.led} to {self.value}")
            if self.value == ON:
                self.led_blink(led_on_time=2, led_off_time=0.01)
            elif self.value == OFF:
                self.led_blink(led_on_time=0.01, led_off_time=2)
            elif self.value == AUTO:
                self.led_blink(led_on_time=0.25, led_off_time=0.25)

    def __str__(self):
        return f"OnOffAutoButton ({self.button_path}): {self.value}"

    def __repr__(self):
        return f"OnOffAutoButton ({self.button_path}): {self.value}"

    @property
    def value(self) -> OnOffAuto:
        """
        Get button state. If no file exists, create it and default it.
        """
        try:
            if self.button_path is None:
                LOGGER.warning("No button_path set for ModeButton")
                raise FileNotFoundError("No button_path set for ModeButton.")
            if not self.button_path.exists():
                LOGGER.info(f"Creating {str(self.button_path)}")
                self.button_path.write_text(AUTO.name)
            return OnOffAuto[self.button_path.read_text(encoding='UTF-8').strip('\n').upper()]
        except (FileNotFoundError, KeyError) as exc:
            LOGGER.warning(f"Cannot read {self.button_path}. Returning MEDIUM",exc_info=exc) 
            return MEDIUM

    @value.setter
    def value(self, state):
        if self.button_path:
            with self.button_path.open(mode="w") as f:
                f.write(state.name)


class SpeedButton(AdvancedButton):
    """ Discrete speeds controlled by file and/or pushbutton, with optional LED indicator """

    def __init__(self, firmness):
        super().__init__(firmness)
        self.value = MEDIUM

    def push(self):
        if super().push():
            if self.value == SLOW:
                self.value = MEDIUM
            elif self.value == MEDIUM:
                self.value = FAST
            elif self.value == FAST:
                self.value = SLOW

        if self.led:
            LOGGER.debug(f"{self}: set led {self.led} to {self.value}")
            if self.value == SLOW:
                self.led_blink(.1, 1)
            elif self.value == MEDIUM:
                self.led_blink(.1, .5)
            elif self.value == FAST:
                self.led_blink(.1, .1)

    def __str__(self):
        return f"SpeedButton ({self.button_path}): {self.value}"

    def __repr__(self):
        return f"SpeedButton ({self.button_path}): {self.value}"

    @property
    def value(self) -> Speed:
        """
        Get button state. If no file exists, create it and default it.
        """
        try:
            if self.button_path is None:
                raise FileNotFoundError("No button_path set for SpeedButton.")
            if not self.button_path.exists():
                LOGGER.info(f"Creating {str(self.button_path)}")
                self.button_path.write_text(MEDIUM.name)
            return Speed[self.button_path.read_text(encoding='UTF-8').strip('\n').upper()]
        except (FileNotFoundError, KeyError) as exc:
            LOGGER.warning(f"Cannot read {self.button_path}. Returning MEDIUM",exc_info=exc) 
            return MEDIUM

    @value.setter
    def value(self, state):
        if self.button_path:
            with self.button_path.open(mode="w") as f:
                f.write(state.name)

def button_test():
    speed = SpeedButton(SOFTWARE)
    speed.lit_for = timedelta(seconds=5)
    speed.set("speed", 27, 10)
    mode = ModeButton(SOFTWARE)
    mode.lit_for = timedelta(seconds=5)
    mode.set("mode", 17, 4)
    print("lit: 5s")
    LOGGER.debug("debug")
    sleep(60)

    speed.lit_for = None
    mode.lit_for = None
    print("lit: inf")
    sleep(60)

    print("done")


if __name__ == "__main__":
    #breakpoint()
    LOGGER.setLevel(logging.DEBUG)
    logging.basicConfig(format=LOG_FORMAT, level=logging.DEBUG)
    button_test()
    
