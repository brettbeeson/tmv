import sys
from sys import stderr
from enum import Enum
from signal import signal, SIGINT, SIGTERM
import argparse
import logging
from pathlib import Path
from time import sleep
from shutil import which
from posix import geteuid
# to enable monkeypatching, don't import "from tmv.util", but instead:
import tmv.util
from tmv.util import Tomlable, service_details, LOG_FORMAT
from tmv.exceptions import ConfigError, SignalException
from subprocess import CalledProcessError
import shutil
from pkg_resources import resource_filename


try:
    import RPi.GPIO as GPIO  # Import GPIO library
except (ImportError, NameError) as exc:
    print(exc)


LOGGER = logging.getLogger("tmv.controller")


class Unit:
    """
    subprocess/systemdctl based control of systemd units, with the same interface as psytemd.systemd1.Unit
    Unit("tmv-camera.service")
    """

    def __init__(self, service_full_name):
        self._service = service_full_name

    def __str__(self):
        return self._service

    def Load(self):
        pass

    @staticmethod
    def can_systemd():
        if not which("systemctl"):
            LOGGER.warning("Cannot find systemctl to run services")
            return False
        if geteuid() != 0:
            LOGGER.warning(
                f"Running as non-root (euid {geteuid()}): may not be able to run systemd!")
            return False
        return True

    def Active(self):
        """
        true if status is 'active (...)'
        false otherwise or non-existant
        """
        try:
            return service_details(self._service)['status'].startswith('active')
        except (CalledProcessError, KeyError):
            return False

    def Start(self, s=None):
        # must be authorised. will throw
        LOGGER.info(f"execute: systemctl start {self._service}")
        tmv.util.run_and_capture(["systemctl", "start", self._service])

    def Stop(self, s=None):
        LOGGER.info(f"execute: systemctl stop {self._service}")
        tmv.util.run_and_capture(["systemctl", "stop", self._service])

    def Restart(self, s=None):
        LOGGER.info(f"execute: systemctl restart {self._service}")
        tmv.util.run_and_capture(["systemctl", "restart", self._service])


class OnOffAuto(Enum):
    """ Like a machine switch toggle or slider """
    ON = 'on'
    OFF = 'off'
    AUTO = 'auto'

    def __str__(self):
        return self.value


ON = OnOffAuto.ON
OFF = OnOffAuto.OFF
AUTO = OnOffAuto.AUTO


class HardwareSwitch():
    """ ON/OFF (one pin) or ON/OFF/AUTO (two pins) """

    def __init__(self, pins: list):
        # will fail unless on RPi
        GPIO.setmode(GPIO.BOARD)  # Use physical pin numbering
        GPIO.setup(pins[0], GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        self.on = lambda: GPIO.input(pins[0]) == GPIO.HIGH
        if len(pins) > 0:
            GPIO.setup(pins[1], GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
            self.off = lambda: GPIO.input(pins[1]) == GPIO.HIGH
        else:
            self.off = lambda: GPIO.LOW

    def __str__(self):
        return str(vars(self))

    def __repr__(self):
        return str(vars(self))

    def position(self) -> OnOffAuto:
        if self.on() and not self.off():
            return ON
        if not self.on and not self.off:
            return AUTO
        if not self.on and self.off:
            return OFF
        if self.on and self.off:
            LOGGER.warning("camera_switch ON and OFF are both high, ya moose")
            return AUTO
        raise RuntimeError("Logic error")


class SoftwareSwitch():
    """ Three way switch ON/OFF/AUTO based on a file """

    def __init__(self, switch_file: str):
        self.switch_path = Path(switch_file)
        if not self.switch_path.is_file():
            self.position = OFF

    def __str__(self):
        return str(vars(self))

    def __repr__(self):
        return str(vars(self))

    @property
    def position(self) -> OnOffAuto:
        try:
            return OnOffAuto[self.switch_path.read_text(encoding='UTF-8').strip('\n').upper()]
        except BaseException as exc:
            LOGGER.warning(exc, exc_info=exc)
            return OFF

    @position.setter
    def position(self, state: OnOffAuto):
        with self.switch_path.open(mode="w") as f:
            f.write(state.name)


class Switches(Tomlable):
    """ On/Off/Auto switches, configurable and software/hardware based"""

    DLFT_SW_CONFIG = """
    [switches]
        [switches.camera]
            file = '/etc/tmv/camera-switch'
        [switches.upload]
            file = '/etc/tmv/upload-switch'
    """

    DLFT_HW_CONFIG = """
    [switches]
        [switches.camera]
            pins = [10]    
        [switches.upload]
            pins = [11,12]    
    """

    def __init__(self):
        self.switches = {}

    def configd(self, config_dict):
        if 'switches' in config_dict:
            for s in config_dict['switches']:
                config = config_dict['switches']
                if 'file' in config[s]:
                    self.switches[s] = SoftwareSwitch(config[s]['file'])
                elif 'pins' in config[s]:
                    self.switches[s] = HardwareSwitch(config[s]['pins'])
                else:
                    raise ConfigError("switch {s} is mis-configured")

    def __getitem__(self, switch):
        return self.switches[switch].position

    def __setitem__(self, switch, state):
        self.switches[switch].position = state

    def __contains__(self, switch):
        return switch in self.switches

    def __str__(self):
        return str(vars(self))

    def __repr__(self):
        return str(vars(self))


class Controller:
    """
    Controls Transfer and Camera services based on switches
    Only perform actions when a switch position is changed, to avoid repeatedly polling for service status
    """

    def __init__(self, switches: Switches = None):
        if 'camera' not in switches or 'upload' not in switches:
            raise ConfigError(
                f"[switches] ({switches}) needs a 'camera' and 'upload' switch. ")
        self.switches = switches
        self._upload_switch_state = None
        self._camera_switch_state = None
        self._camera_unit = Unit("tmv-camera.service")
        self._upload_unit = Unit("tmv-s3-upload.service")

    def __str__(self):
        return f"Controller: switches:{self.switches} camera-state:{self._camera_switch_state} upload-state:{self._upload_switch_state}"

    def reset_services(self):
        self._upload_switch_state = self.switches['upload']
        if self._upload_switch_state == ON:
            self._upload_unit.Restart()
        else:
            self._upload_unit.Stop()

        self._camera_switch_state = self.switches['camera']
        if self._camera_switch_state == ON or self._camera_switch_state == AUTO:
            self._camera_unit.Restart()
        else:
            self._camera_unit.Stop()

    def update_services(self):
        if not self.switches:
            LOGGER.warn("No switches set: cannot update_services()")
            return

        if self.switches['upload'] != self._upload_switch_state:
            self._upload_switch_state = self.switches['upload']
            LOGGER.debug(f"upload switch changed to {self._upload_switch_state}")
            if self._upload_switch_state == ON:
                if not self._upload_unit.Active():
                    self._upload_unit.Start()
            elif self._upload_switch_state == OFF:
                if self._upload_unit.Active():
                    self._upload_unit.Stop()
            else:
                raise RuntimeError('Logic error')

        if self.switches['camera'] != self._camera_switch_state:
            self._camera_switch_state = self.switches['camera']
            LOGGER.debug(
                f"camera switch changed to {self._camera_switch_state}")
            if self._camera_switch_state == ON or self._camera_switch_state == AUTO:
                if not self._camera_unit.Active():
                    # start restart tmv-camera service if it's inactive
                    # in this service, it will use Camera class to detect this is ON/AUTO and
                    # either take photos regardless of time settings / or respect time settings
                    self._camera_unit.Start()
            elif self._camera_switch_state == OFF:
                if self._camera_unit.Active():
                    self._camera_unit.Stop()
            else:
                raise RuntimeError('Logic error')


class SoftwareController(Controller):
    """ Use files to control the camera switchs """


def sig_handler(signal_received, frame):
    raise SignalException


def controller_console(cl_args=sys.argv[1:]):
    """
    Run as a service, polling switchs and stopping/starting services
    """
    retval = 0
    signal(SIGINT, sig_handler)
    signal(SIGTERM, sig_handler)
    parser = argparse.ArgumentParser(
        "Control TMV services such as camera, transfer.")
    parser.add_argument('--log-level', default='INFO', dest='log_level',
                        type=tmv.util.log_level_string_to_int, nargs='?',
                        help='level: {0}'.format(tmv.util.LOG_LEVEL_STRINGS))
    parser.add_argument('--config-file', default="./camera.toml")

    args = (parser.parse_args(cl_args))
    logging.getLogger("tmv.controller").setLevel(args.log_level)
    logging.basicConfig(format=LOG_FORMAT, level=args.log_level)

    LOGGER.info("Starting controller app. config-file={}".format(Path(args.config_file).absolute()))

    try:
        if not Path(args.config_file).is_file():
            default_config_path = Path(resource_filename(__name__, 'resources/camera.toml'))
            LOGGER.info("Writing default config file to {} (from {})".format(args.config_file, default_config_path.absolute()))
            Path(args.config_file).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(default_config_path, args.config_file)
        s = Switches()
        s.config(args.config_file)
        c = Controller(s)
        LOGGER.debug("Using controller {}".format(c))
        c.reset_services()     
        while True:
            c.update_services()
            sleep(1)
    except SignalException as e:
        LOGGER.info('SIGTERM, SIGINT or CTRL-C detected. Exiting gracefully.')
        retval = 0
    except BaseException as e:
        retval = 1
        LOGGER.error(e)
        LOGGER.debug(e, exc_info=e)

    sys.exit(retval)


def control_console(cl_args=sys.argv[1:]):
    parser = argparse.ArgumentParser(
        "Allow software input to 'press' switchs.")
    parser.add_argument('-c', '--config-file')
    parser.add_argument('-v', '--verbose', action="store_true")
    parser.add_argument('camera', type=OnOffAuto, choices=list(OnOffAuto))
    parser.add_argument('upload', type=OnOffAuto, choices=list(OnOffAuto))
    args = (parser.parse_args(cl_args))
    switches = Switches()
    if args.config_file:
        switches.config(args.config_file)
    else:
        switches.configs(Switches.DLFT_SW_CONFIG)

    if args.verbose:
        print(f"Setup switches: {switches}")

    switches['camera'] = args.camera
    switches['upload'] = args.upload

    if args.verbose:
        print(f"Set switches: {switches}")
