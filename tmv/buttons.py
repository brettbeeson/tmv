# pylint: disable=broad-except,logging-fstring-interpolation,logging-not-lazy, dangerous-default-value

#
# File-underlied 2- and 3-value buttones with hardware buttons and LEDs
#

from enum import Enum
import logging
from pathlib import Path
# to enable monkeypatching, don't import "from tmv.util", but instead:
import tmv.util

try:
    from gpiozero import Button
    from gpiozero import LED
except (ImportError, NameError) as exc:
    print(exc)

LOGGER = logging.getLogger("tmv.button")


class Speed(Enum):
    """ Trimatic """
    SLOW = 'fast'
    MEDIUM = 'medium'
    FAST = 'fast'

    def __str__(self):
        return str(self.value)


# Shortcuts
SLOW = Speed.SLOW
MEDIUM = Speed.MEDIUM
FAST = Speed.FAST


class AdvancedButton(tmv.util.Tomlable):
    """ mode controlled by file and/or pushbutton, with optional LED indicator """

    def __init__(self):
        self.value = None
        self.button_path = None
        self.button = None
        self.led = None

    def set(self, button_path=None, button_pin=None, led_pin=None):
        if button_path:
            self.button_path = Path(button_path)
        if button_pin:
            self.button = Button(button_pin)
            self.button.when_pressed = self.push
        if led_pin:
            self.led = LED(led_pin)

    def push(self):
        raise NotImplementedError

    def __str__(self):
        return f"ModeButton ({self.button_path}): {self.value}"

    def __repr__(self):
        return f"ModeButton ({self.button_path}): {self.value}"

    def configd(self, config_dict):
        if 'button' in config_dict:
            c = config_dict['button']
            if 'file' in c:
                self.button_path = Path(c['file'])
            if 'buttonpin' in c:
                self.button = Button(c['pin'])
                self.button.when_pressed = self.push
            if 'ledpin' in c:
                self.led = LED['ledpin']

    @property
    def value(self):
        """
        Get button state. If no file exists, create it and default.
        """
        raise NotImplementedError

    @value.setter
    def value(self, state):
        with self.button_path.open(mode="w") as f:
            f.write(state.name)


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

    def __init__(self):
        super().__init__()
        self.value = OFF

    def push(self):
        if self.value == ON:
            self.value = OFF
        elif self.value == OFF:
            self.value = AUTO
        elif self.value == AUTO:
            self.value = ON

        if self.led:
            if self.value == ON:
                self.led.on()
            elif self.value == OFF:
                self.led.off()
            elif self.value == AUTO:
                self.led.blink()

    def __str__(self):
        return f"OnOffAutoButton ({self.button_path}): {self.value}"

    def __repr__(self):
        return f"OnOffAutoButton ({self.button_path}): {self.value}"

    @property
    def value(self) -> OnOffAuto:
        """
        Get button state. If no file exists, create it and default to AUTO.
        """
        try:
            return OnOffAuto[self.button_path.read_text(encoding='UTF-8').strip('\n').upper()]
        except (FileNotFoundError, KeyError):
            LOGGER.info(f"Creating {str(self.button_path)}")
            self.button_path.write_text(AUTO.name)
            return AUTO



class SpeedButton(AdvancedButton):
    """ Discrete speeds controlled by file and/or pushbutton, with optional LED indicator """

    def __init__(self):
        super().__init__()
        self.value = MEDIUM

    def push(self):
        if self.value == SLOW:
            self.value = MEDIUM
        elif self.value == MEDIUM:
            self.value = FAST
        elif self.value == FAST:
            self.value = SLOW

        if self.led:
            if self.value == SLOW:
                self.led.blink(.1, 1)
            elif self.value == MEDIUM:
                self.led.blink(.1, .5)
            elif self.value == FAST:
                self.led.blink(.1, .1)

    def __str__(self):
        return f"SpeedButton ({self.button_path}): {self.value}"

    def __repr__(self):
        return f"SpeedButton ({self.button_path}): {self.value}"

    @property
    def value(self) -> Speed:
        """
        Get button state. If no file exists, create it and default to AUTO.
        """
        try:
            return Speed[self.button_path.read_text(encoding='UTF-8').strip('\n').upper()]
        except (FileNotFoundError, KeyError):
            LOGGER.info(f"Creating {str(self.button_path)}")
            self.button_path.write_text(MEDIUM.name)
            return MEDIUM

    @value.setter
    def value(self, state: OnOffAuto):
        with self.button_path.open(mode="w") as f:
            f.write(state.name)
