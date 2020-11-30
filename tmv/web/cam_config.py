from tmv.util import Tomlable
from pathlib import Path
from tmv.button import get_switch
from tmv.config import DLFT_CAMERA_SW_SWITCH_TOML

class CameraConfig(Tomlable):
    """ Proxy-style to read camera config file and remember file locations """

    def __init__(self):
        self.file_root = Path(".")
        self.switches = {}
        self.latest_image = None
    

    def configd(self, config_dict):
        #pp.pprint(config_dict)
        self.switches = {}
        
        if 'switch' in config_dict['camera']:
            self.switches['camera'] = get_switch(config_dict['camera'])
        else:
            self.switches['camera'] = get_switch(DLFT_CAMERA_SW_SWITCH_TOML)      
        
        self.file_root = Path(config_dict['camera']['file_root'])
        self.latest_image = self.file_root / config_dict['camera'].get('latest_image', 'latest-image.jpg')
