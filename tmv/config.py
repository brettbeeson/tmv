from enum import Enum
from pkg_resources import resource_filename
from tmv.circstates import State

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

SPEED_BUTTON_STATES = [
    State(Speed.SLOW, on_time = 0.1, off_time = 1),
    State(Speed.MEDIUM, on_time = 0.1, off_time = 0.5),
    State(Speed.FAST, on_time = 0.1, off_time = 0.1),
]
MODE_BUTTON_STATES = [
    State(ON, on_time=2, off_time=.1),
    State(OFF, on_time=.1, off_time=2),
    State(AUTO, on_time=.2, off_time=.2),
]

# pins all in BCM numbering
SPEED_BUTTON = 27
SPEED_LED = 10
SPEED_FILE = 'camera-speed'
MODE_BUTTON = 17
MODE_LED = 4
MODE_FILE = 'camera-mode'
ACTIVITY_LED = 9
CAMERA_CONFIG_FILE = "camera.toml"


FONT_FILE = resource_filename(__name__, 'resources/FreeSans.ttf')

HH_MM = "%H:%M"
