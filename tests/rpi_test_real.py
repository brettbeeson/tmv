from freezegun import freeze_time
import logging
import PIL
import tmv.camera
from dateutil.parser import parse
from datetime import datetime as dt, timedelta
import shutil
import os
from tmv.camera import LightLevel, Camera, FakePiCamera, CameraInactiveAction


TMP_DIR = "tests/camera/tmp/"
tmv_logger = logging.getLogger("tmv.camera")

def setup_module(module):
    fh = logging.FileHandler('tmv.camera.log', "w")
    formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s')
    formatter.datefmt = '%Y-%m-%dT%H:%M:%S'
    fh.setFormatter(formatter)

    global tmv_logger
    tmv_logger = logging.getLogger("tmv.camera")
    tmv_logger.setLevel(logging.DEBUG)
    tmv_logger.addHandler(fh)
    tmv_logger.setLevel(logging.DEBUG)
    try:
        shutil.rmtree(TMP_DIR)
    except FileNotFoundError:
        pass
    os.mkdir(TMP_DIR)

def test_flip(monkeypatch):
    global tmv_logger
    # tmv.util.unlink_safe("test_real.log")
    
    with freeze_time(parse("2000-01-01 12:00:00"), tick=True) as fdt:
        global fdt_global
        fdt_global = fdt
        # monkeypatch.setattr(time, 'sleep', sleepless)
        c = tmv.camera.Camera()
        c.file_root = TMP_DIR + "/test_real/"
        cf = """
        [camera]
        on = true
        off = false
        interval = 5.0
        file_by_date = false
        [camera.picam.LIGHT]
            iso = 800
            hflip = true
        [camera.sensor]
            save_images = true
            freq = 20.0
            dark = 0.0
            light = 0.0
        """
        c.configs(cf)
        c.run(20)
