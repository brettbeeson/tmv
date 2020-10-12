from pkg_resources import resource_filename

DLFT_CAMERA_SW_SWITCH_TOML = """
    [switch]
    file = "/etc/tmv/camera-switch"
    """
DLFT_CAMERA_HW_SWITCH_TOML = """
    [switch]
    pins = [4, 17]
    """
CWD_CAMERA_SW_SWITCH_TOML = """
    [switch]
    file = "./camera-switch"
    """

DFLT_UPLOAD_HW_SWITCH_TOML = """ 
[switch]
    pins = [22]
"""

DFLT_UPLOAD_SW_SWITCH_TOML = """
[switch]
    file = "/etc/tmv/upload-switch"
"""

DFLT_CAMERA_CONFIG_FILE = "/etc/tmv/camera.toml"

FONT_FILE = resource_filename(__name__, 'resources/FreeSans.ttf')

HH_MM = "%H:%M"
