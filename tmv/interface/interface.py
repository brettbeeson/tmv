# pylint: disable=protected-access, line-too-long, logging-fstring-interpolation, dangerous-default-value, logging-not-lazy, too-many-lines

from datetime import datetime as dt, timedelta             # dt = class, time=class
# to enable monkeypatching, don't import "from x.y", but instead "import y" and use "x.y"
import logging
import importlib
import threading
from time import sleep
from pathlib import Path

from tmv.buttons import StatefulButton, StatesCircle, ON, OFF
from tmv.camera import SpeedButtonFactory, ModeButtonFactory
from tmv.util import Tomlable, interval_speeded
from tmv.config import *  # pylint: disable=wildcard-import, unused-wildcard-import

LOGGER = logging.getLogger("tmv.interface.interface")


class Interface(Tomlable):
    """Represents the interface to the camera (not the camera itself), such as the config file, buttons and screen    """

    def __init__(self):
        super().__init__()
        self._interval = timedelta(seconds=60)
        self.mode_button = StatefulButton(MODE_FILE, MODE_BUTTON_STATES)
        self.mode_button.lit_for = timedelta(seconds=30)
        self.speed_button = StatefulButton(SPEED_FILE, SPEED_BUTTON_STATES)
        self.speed_button.lit_for = timedelta(seconds=30)
        self.camera_activity = StatesCircle(ACTIVITY_FILE, ACTIVITY_STATE, fallback=OFF)

        self.file_root = "."
        self.has_pijuice = False
        self._latest_image = "latest-image.jpg"
        self.port = 5000
        self.screen = None
        self.shutdown = False

    @property
    def latest_image(self):
        """ return with file_root as the ... file root! """
        return Path(self.file_root) / self._latest_image

    @property
    def latest_image_time(self):
        """ the filesystem modified time, not the filename-marked time  """
        return dt.fromtimestamp(self.latest_image.stat().st_mtime)

    def n_images(self):
        return len(list(Path(self.file_root).glob("*")))

    @latest_image.setter
    def latest_image(self, value):
        self._latest_image = value

    @property
    def interval(self):
        return interval_speeded(self._interval, self.speed_button.value)

    def configd(self, config_dict):
        c = config_dict  # shortcut
        # read the [camera] to match real camera with this "interface" camera
        if 'camera' in config_dict:
            c = config_dict['camera']  # can accept config in root or [camera]
        if 'mode_button' in c:
            self.mode_button = ModeButtonFactory(c['mode_button'], software_only=False)
            self.mode_button.lit_for = timedelta(seconds=30)
        if 'speed_button' in c:
            self.speed_button = SpeedButtonFactory(c['speed_button'], software_only=False)
            self.speed_button.lit_for = timedelta(seconds=30)
        
        self.has_pijuice = c.get('pijuice', False)
        
        if 'interval' in c:
            # interval specified as seconds: convert to timedelta
            self._interval = timedelta(seconds=c['interval'])
            if self._interval.total_seconds() < 10.0:
                LOGGER.warning("Intervals < 10s are not tested")

        self.setattr_from_dict('file_root', c)
        self.setattr_from_dict('latest_image', c)

        # read the [interface] for specific-to-interface settings
        #
        c = config_dict
        if 'interface' in config_dict:
            c = config_dict['interface']  # can accept config in root or [interface]

        if 'log_level' in c:
            logging.getLogger("tmv").setLevel(c['log_level'])

        if 'screen' in c:
            module = importlib.import_module("tmv.interface.screen")
            LOGGER.info(f"Dynamically creating a screen for class {c['screen']} in module {module}")
            klass = getattr(module, c['screen'])
            self.screen = klass(self)
            LOGGER.info("Interface will use a screen. Ensure your LEDs for speed and mode buttons and check button pins.")
            self.mode_button.lit_for = None
            self.speed_button.lit_for = None
        LOGGER.debug(f"screen: {self.screen}")

        self.setattr_from_dict('port', c)

    