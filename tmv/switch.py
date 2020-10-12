# pylint: disable=broad-except,logging-fstring-interpolation,logging-not-lazy, dangerous-default-value

#
# Abstract hardware/software switches
#

from enum import Enum
import logging
import argparse
import sys
from subprocess import CalledProcessError
from pathlib import Path
# to enable monkeypatching, don't import "from tmv.util", but instead:
#import tmv.util
import toml
from tmv.systemd import Unit
from tmv.util import Tomlable, ensure_config_exists
from tmv.exceptions import ConfigError, SwitchError
from tmv.config import *

try:
    import RPi.GPIO as GPIO  # Import GPIO library
except (ImportError, NameError) as exc:
    print(exc)


LOGGER = logging.getLogger("tmv.switch")

class OnOffAuto(Enum):
    """ Like a machine switch toggle or slider """
    ON = 'on'
    OFF = 'off'
    AUTO = 'auto'

    def __str__(self):
        return str(self.value)


ON = OnOffAuto.ON
OFF = OnOffAuto.OFF
AUTO = OnOffAuto.AUTO


def get_switch(o):
    """
     Convenience method for SwitchFactory Pass toml as string or dict with [switch] and get a Switch.
     """
    if isinstance(o,str):
        sf = SwitchFactory()
        sf.configs(o)
        return sf.get_switch()
    elif isinstance(o,dict):
        sf = SwitchFactory()
        sf.configd(o)
        return sf.get_switch()
    else:
        raise TypeError("Unable to make switch from type '" + o.__class__.__name__ + "'")


class SwitchFactory(Tomlable):
    """ On/Off/Auto switch. Software/hardware based"""

    def __init__(self):
        self.switch = None

    def configd(self, config_dict):
        """
        Pass is dict of items with root [switch]
        e.g. {'file="/etc/file"} or {'pins'={1,2}}
        """
        if 'switch' not in config_dict:
            raise ConfigError(f"No switch configured in {config_dict}")
        c = config_dict['switch']
        if 'log_level' in c:
            LOGGER.setLevel(c['log_level'])
        if 'file' in c:
            self.switch = SoftwareSwitch(c['file'])
        elif 'pins' in c:
            self.switch = HardwareSwitch(c['pins'])
        else:
            raise ConfigError("switch ({config_dict})is mis-configured")

    def get_switch(self):
        return self.switch

class Switch():
    """ Abstrast switch """
    

class HardwareSwitch(Switch):
    """ ON/OFF (one pin) or ON/OFF/AUTO (two pins) """

    def __init__(self, pins: list):
        # will fail unless on RPi
        GPIO.setmode(GPIO.BCM)  # Use GPIO/BCM pin numbering
        self.pins = pins

        if len(pins) == 1:
            # on/off: 1 pin
            GPIO.setup(pins[0], GPIO.IN, pull_up_down=GPIO.PUD_UP)
            self.on = lambda: GPIO.input(pins[0]) == GPIO.HIGH
            self.off = lambda: GPIO.input(pins[0]) == GPIO.LOW
        elif len(pins) == 2:
            # on/off/auto: 2 pins
            GPIO.setup(pins[0], GPIO.IN, pull_up_down=GPIO.PUD_UP)
            self.on = lambda: GPIO.input(pins[0]) == GPIO.HIGH
            GPIO.setup(pins[1], GPIO.IN, pull_up_down=GPIO.PUD_UP)
            self.off = lambda: GPIO.input(pins[1]) == GPIO.HIGH
        else:
            raise ConfigError(f"Switches need 1 or 2 pins. Got: {pins}")
        
        

    def __str__(self):
        return f"HardwareSwitch: on={self.on()} off={self.off()} pos={self.position}"
        

    def __repr__(self):
        return f"HardwareSwitch: on={self.on()} off={self.off()} pos={self.position}"

    @property
    def position(self) -> OnOffAuto:
        if self.on() and not self.off():
            return ON
        if not self.on() and not self.off():
            return AUTO
        if not self.on() and self.off():
            return OFF
        if self.on() and self.off():
            LOGGER.warning("camera_switch ON and OFF are both high, ya moose")
            return AUTO
        raise RuntimeError("Logic error")

    @position.setter
    def position(self, state :OnOffAuto):
        raise SwitchError(f"Can't set hardware switch (on pins {self.pins}) in software. Try IRL!")

class SoftwareSwitch(Switch):
    """ Three way switch ON/OFF/AUTO based on a file """

    def __init__(self, switch_file: str):
        self.switch_path = Path(switch_file)

    def __str__(self):
        return f"SoftwareSwitch ({self.switch_path}): {self.position}"

    def __repr__(self):
        return f"SoftwareSwitch ({self.switch_path}): {self.position}"

    @property
    def position(self) -> OnOffAuto:
        """
        Get switch state. If no file exists, create it and default to AUTO.
        """
        try:
            return OnOffAuto[self.switch_path.read_text(encoding='UTF-8').strip('\n').upper()]
        except (FileNotFoundError, KeyError):
            LOGGER.info(f"Creating {str(self.switch_path)}")
            self.switch_path.write_text(AUTO.name)
            return AUTO

    @position.setter
    def position(self, state: OnOffAuto):
        with self.switch_path.open(mode="w") as f:
            f.write(state.name)



def switches_console(cl_args=sys.argv[1:]):
    try:
        parser = argparse.ArgumentParser(
            "Check and control software camera/upload switches.")
        parser.add_argument('-c', '--config-file',default=DFLT_CAMERA_CONFIG_FILE)
        parser.add_argument('-v', '--verbose', action="store_true")
        parser.add_argument('-r', '--restart', action="store_true", help="restart service to (e.g.) re-read config")
        parser.add_argument('camera', type=OnOffAuto, choices=list(OnOffAuto), nargs="?")
        parser.add_argument('upload', type=OnOffAuto, choices=list(OnOffAuto), nargs="?")
        args = (parser.parse_args(cl_args))

        if args.verbose:
            print(args)

        ensure_config_exists(args.config_file)
        config_dict = toml.load(args.config_file)

        if 'switch' in config_dict['camera']:
            c = get_switch(config_dict['camera'])
        else:
            c = get_switch(DLFT_CAMERA_SW_SWITCH_TOML)

        if 'switch' in config_dict['upload']:
            u = get_switch(config_dict['upload'])
        else:
            u = get_switch(DFLT_UPLOAD_SW_SWITCH_TOML)

        if args.verbose: 
            print(c)
            print(u)
        
        if args.camera:
            try:
                c.position = args.camera
            except SwitchError as e:
                print(e)
        if args.upload:
            try:
                u.position = args.upload
            except SwitchError as e:
                print(e)
        if not args.camera and not args.upload:
            print(c.position)
            print(u.position)
        if args.restart:
            if args.verbose:
                print("Restarting services")
            ctlr = Unit("tmv-camera.service")
            ctlr.restart()
            ctlr = Unit("tmv-upload.service")
            ctlr.restart()
        sys.exit(0)

    except PermissionError as exc:
        print(f"{exc}: check your file access  permissions. Try root.", file=sys.stderr)
        if args.verbose:
            raise  # to get stack trace
        sys.exit(10)
    except CalledProcessError as exc:
        print(f"{exc}: check your execute systemd permissions. Try root.", file=sys.stderr)
        if args.verbose:
            raise  # to get stack trace
        sys.exit(20)
    except Exception as exc:
        print(exc, file=sys.stderr)
        if args.verbose:
            raise  # to get stack trace
        sys.exit(30)


