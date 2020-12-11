from pkg_resources import resource_filename

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
