# pylint: disable=protected-access, line-too-long, logging-fstring-interpolation, dangerous-default-value, logging-not-lazy, too-many-lines

from datetime import datetime as dt, timedelta             # dt = class, time=class
# to enable monkeypatching, don't import "from x.y", but instead "import y" and use "x.y"
import logging
import importlib
import glob
import os
from pathlib import Path

from tmv.buttons import StatefulButton, StatefulHWButton, StatesCircle, OFF
from tmv.util import Tomlable, interval_speeded, timed_lru_cache
from tmv.config import *  # pylint: disable=wildcard-import, unused-wildcard-import

LOGGER = logging.getLogger("tmv.interface.interface")


class Interface(Tomlable):
    """Represents the interface to the camera (not the camera itself), such as the config file, buttons and screen    """

    def __init__(self):
        print("Interface start")
        super().__init__()
        self._interval = timedelta(seconds=60)
        self.latest_image = Path('latest-image.jpg')
        # Default buttons are software only. Set hardware in config
        self.mode_button = StatefulButton(MODE_FILE, MODE_BUTTON_STATES, fallback=AUTO)
        self.speed_button = StatefulButton(SPEED_FILE, SPEED_BUTTON_STATES, fallback=MEDIUM)
        # Always software only
        self.activity = StatesCircle(ACTIVITY_FILE, ACTIVITY_STATE, fallback=OFF)
        self.tmv_root = Path(".")
        self.has_pijuice = False

        self.port = 5000    # Where Flask server is started
        self.screen = None

    def poke(self):
        """ Stop interface's screen from sleeping """
        if self.screen:
            self.screen.last_button_press = dt.now()

    def stop(self):
        if self.screen:
            self.screen.stop()

    @property
    def latest_image_time(self):
        """ the filesystem modified time, not the filename-marked time  """
        return dt.fromtimestamp(self.latest_image.stat().st_mtime)

    @timed_lru_cache(seconds=10, maxsize=10)
    def n_images(self):
        # Resurive as often stores in day-named-folders under root
        return len(glob.glob(str(self.tmv_root / "**/*.jpg"), recursive=True))

    @property
    def interval(self):
        return interval_speeded(self._interval, self.speed_button.value)

    def configd(self, config_dict):
        """read the [camera] to match real camera with this "interface" camera"""

        if 'camera' in config_dict:
            c = config_dict['camera']

            self.tmv_root = Path(c.get('tmv_root', '.'))
            os.chdir(self.tmv_root)

            self.has_pijuice = c.get('pijuice', False)
            if 'interval' in c:
                self._interval = timedelta(seconds=c['interval'])

        #
        # read the [interface] for specific-to-interface settings
        #

        if 'interface' in config_dict:
            c = config_dict['interface']

            if 'log_level' in c:
                logging.getLogger("tmv").setLevel(c['log_level'])

            # __init__ defaults are software buttons. If pins are specified, convert to hardbuttons
            if 'mode_button' in c:
                # if self.mode_button and self.mode_button.button:
                #    self.mode_button.button.close()
                #    self.mode_button = None
                button = c['mode_button'].get('button', None)
                led = c['mode_button'].get('led', None)  # usually unused now (show on screen instead)
                self.mode_button = StatefulHWButton(MODE_FILE, MODE_BUTTON_STATES, led, button, fallback=AUTO)
            if 'speed_button' in c:
                button = c['speed_button'].get('button', None)
                led = c['speed_button'].get('led', None)  # usually unused now (show on screen instead)
                self.speed_button = StatefulHWButton(SPEED_FILE, SPEED_BUTTON_STATES, led, button, fallback=MEDIUM)

            if 'screen' in c:
                module = importlib.import_module("tmv.interface.screen")
                klass = getattr(module, c['screen'])
                # unless we manually cleanup Buttons (gpiozero), we can a 'reusing pin' error
                # so don't try to re-create screen
                if self.screen:
                    LOGGER.info("Interface already have a screen. Restart to change screen.")
                else:
                    self.screen = klass(self)
                    LOGGER.info("Interface will use a screen. Ensure your pins for speed and mode buttons are set in mode|speed_button")

            self.setattr_from_dict('port', c)

        LOGGER.debug(f"Using screen: {self.screen}")
        LOGGER.debug(f"Using mode_button: {self.mode_button}")
        LOGGER.debug(f"Using speed_button: {self.speed_button}")
