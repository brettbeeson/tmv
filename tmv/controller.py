# pylint: disable=logging-fstring-interpolation,logging-not-lazy, dangerous-default-value

import sys
from enum import Enum
from signal import signal, SIGINT, SIGTERM
import argparse
import logging
from pathlib import Path
from time import sleep
from shutil import which
from posix import geteuid
from subprocess import CalledProcessError
import shutil
from pkg_resources import resource_filename
# to enable monkeypatching, don't import "from tmv.util", but instead:
import tmv.util
from tmv.util import Tomlable, service_details, LOG_FORMAT
from tmv.exceptions import ConfigError, SignalException


try:
    import RPi.GPIO as GPIO  # Import GPIO library
except (ImportError, NameError) as exc:
    print(exc)


LOGGER = logging.getLogger("tmv.controller")


class Unit:
    """
    subprocess/systemdctl based control of systemd units, similiar interface as psytemd.systemd1.Unit
    """

    def __init__(self, service_full_name):
        """ e.g. Unit("tmv-camera.service") """
        self._service = service_full_name

    def __str__(self):
        return self._service

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

    def active(self):
        """
        true if status is 'active (...)'
        false otherwise or non-existant
        """
        try:
            return service_details(self._service)['status'].startswith('active')
        except (CalledProcessError, KeyError):
            return False

    def status(self):
        try:
            return service_details(self._service)['status']
        except KeyError:
            return 'unknown'
        
        """
        Return systemd service detail
        active
        inactive
        activating
        deactivating
        failed
        not-found
        dead
        """
        
        
    def start(self):
        # must be authorised. will throw
        LOGGER.info(f"execute: systemctl start {self._service}")
        tmv.util.run_and_capture(["systemctl", "start", self._service])

    def stop(self):
        LOGGER.info(f"execute: systemctl stop {self._service}")
        tmv.util.run_and_capture(["systemctl", "stop", self._service])

    def restart(self):
        LOGGER.info(f"execute: systemctl restart {self._service}")
        tmv.util.run_and_capture(["systemctl", "restart", self._service])


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

    def __str__(self):
        return str(vars(self))

    def __repr__(self):
        return str(vars(self))

    @property
    def position(self) -> OnOffAuto:
        """
        Get switch state. If no file exists, create it and default to OFF.
        """
        try:
            return OnOffAuto[self.switch_path.read_text(encoding='UTF-8').strip('\n').upper()]
        except (FileNotFoundError, KeyError):
            LOGGER.info(f"Creating {str(self.switch_path)}")
            self.switch_path.write_text(OFF.name)
            return OFF

    @position.setter
    def position(self, state: OnOffAuto):
        with self.switch_path.open(mode="w") as f:
            f.write(state.name)


class Switches(Tomlable):
    """ On/Off/Auto switches, configurable and software/hardware based"""

    DLFT_SW_CONFIG = """
    [controller.switches]
        [controller.switches.camera]
            file = '/etc/tmv/camera-switch'
        [controller.switches.upload]
            file = '/etc/tmv/upload-switch'
    """

    CWD_SW_CONFIG = """
    [controller.switches]
        [controller.switches.camera]
            file = 'camera-switch'
        [controller.switches.upload]
            file = 'upload-switch'
    """

    DLFT_HW_CONFIG = """
    [controller.switches]
        [controller.switches.camera]
            pins = [10]    
        [controller.switches.upload]
            pins = [11,12]    
    """

    def __init__(self):
        self.switches = {}

    def configd(self, config_dict):
        if 'controller' in config_dict:
            c = config_dict['controller']
            if 'log_level' in c:
                LOGGER.setLevel(c['log_level'])
            if 'switches' in c:
                for s in c['switches']:
                    if 'file' in c['switches'][s]:
                        self.switches[s] = SoftwareSwitch(c['switches'][s]['file'])
                    elif 'pins' in c['switches'][s]:
                        self.switches[s] = HardwareSwitch(c['switches'][s]['pins'])
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
    Controls upload and Camera services based on switches
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
        self._upload_unit = Unit("tmv-upload.service")

    def __str__(self):
        return f"Controller: switches:{self.switches} camera-state:{self._camera_switch_state} upload-state:{self._upload_switch_state}"

    def reset_services(self):
        self._upload_switch_state = self.switches['upload']
        if self._upload_switch_state == ON:
            self._upload_unit.restart()
        else:
            self._upload_unit.stop()

        self._camera_switch_state = self.switches['camera']
        if self._camera_switch_state == ON or self._camera_switch_state == AUTO:
            self._camera_unit.restart()
        else:
            self._camera_unit.stop()

    def update_services(self):
        if not self.switches:
            LOGGER.warning("No switches set: cannot update_services()")
            return

        if self.switches['upload'] != self._upload_switch_state:
            self._upload_switch_state = self.switches['upload']
            LOGGER.debug(f"upload switch changed to {self._upload_switch_state}")
            if self._upload_switch_state == ON:
                if not self._upload_unit.active():
                    self._upload_unit.start()
            elif self._upload_switch_state == OFF:
                if self._upload_unit.active():
                    self._upload_unit.stop()
            else:
                raise RuntimeError('Logic error')

        if self.switches['camera'] != self._camera_switch_state:
            self._camera_switch_state = self.switches['camera']
            LOGGER.debug(
                f"camera switch changed to {self._camera_switch_state}")
            if self._camera_switch_state == ON or self._camera_switch_state == AUTO:
                if not self._camera_unit.active():
                    # start restart tmv-camera service if it's inactive
                    # in this service, it will use Camera class to detect this is ON/AUTO and
                    # either take photos regardless of time settings / or respect time settings
                    self._camera_unit.start()
            elif self._camera_switch_state == OFF:
                if self._camera_unit.active():
                    self._camera_unit.stop()
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
    # pylint: disable=broad-except
    signal(SIGINT, sig_handler)
    signal(SIGTERM, sig_handler)
    parser = argparse.ArgumentParser(
        "Control TMV services such as camera, upload.")
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
    except SignalException:
        LOGGER.info('SIGTERM, SIGINT or CTRL-C detected. Exiting gracefully.')
        sys.exit(0)
    except BaseException as exc:
        LOGGER.error(exc)
        LOGGER.debug(exc, exc_info=exc)
        sys.exit(1)


def control_console(cl_args=sys.argv[1:]):
    try:
        parser = argparse.ArgumentParser(
            "Allow software input to 'press' switchs.")
        parser.add_argument('-c', '--config-file')
        parser.add_argument('-v', '--verbose', action="store_true")
        parser.add_argument('-r', '--restart', action="store_true", help="Force services to restart. e.g. to reload config files")
        parser.add_argument('camera', type=OnOffAuto, choices=list(OnOffAuto), nargs="?")
        parser.add_argument('upload', type=OnOffAuto, choices=list(OnOffAuto), nargs="?")
        args = (parser.parse_args(cl_args))
        switches = Switches()
        if args.config_file:
            switches.config(args.config_file)
        else:
            switches.configs(Switches.DLFT_SW_CONFIG)

        if args.verbose:
            print(f"State state of switches: {switches}")
        if args.restart:
            if args.verbose:
                print("Restarting tmv-controller")
            ctlr = Unit("tmv-controller.service")
            ctlr.restart()
        if args.camera:
            switches['camera'] = args.camera
        if args.upload:
            switches['upload'] = args.upload
        if not args.camera and not args.upload:
            print(f"{switches['camera']} {switches['upload']}")
        if args.verbose:
            print(f"Finish state of switches: {switches}")
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
