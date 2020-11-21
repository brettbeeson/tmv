from pkg_resources import resource_filename

# pins all in BCM numbering
SPEED_BUTTON = 27
SPEED_LED = 10
SPEED_FILE = '/etc/tmv/camera-speed'

MODE_BUTTON = 17
MODE_LED = 4
MODE_FILE = '/etc/tmv/camera-mode'

ACTIVITY_LED = 9

CAMERA_CONFIG_FILE = "/etc/tmv/camera.toml"

FONT_FILE = resource_filename(__name__, 'resources/FreeSans.ttf')

HH_MM = "%H:%M"
