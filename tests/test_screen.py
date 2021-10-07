# pylint: disable=unused-import, import-outside-toplevel,protected-access, line-too-long, logging-fstring-interpolation, logging-not-lazy

import subprocess
import os
import random, string
from pathlib import Path
from time import sleep
from sys import stderr
from _datetime import datetime as dt, timedelta
import pytest
import tempfile
#from PIL.ImageOps import invert

from luma.emulator.device import capture, gifanim
from luma.core.virtual import terminal, snapshot, viewport
from luma.oled.device import sh1106

import tmv
from tmv.interface.screen import EInkScreen, OLEDScreen
from tmv.interface.interface import Interface
from tmv.util import interval_speeded
#from tmv.util import interval_speeded
from . import running_on_pi
from tmv.buttons import ON, OFF, AUTO, SLOW, MEDIUM, FAST  # pylint: disable=unused-import



TEST_DATA = Path(__file__).parent / "testdata" / "screen"

def press(button):
    button.pin.drive_low()
    sleep(.25)
    button.pin.drive_high()
    

class FakeScreen:
    """[summary]    """

    def __init__(self, w, h):
        self.height = w
        self.width = h


def test_screen_image_display():
    # todo: check images location
    screen = EInkScreen(Interface())
    os.chdir(TEST_DATA)
    # self._screen_image
    screen._interface._latest_image = "1.jpg"
    screen._display = FakeScreen(122, 250)
    screen.update_image()  # logo
    show(screen._screen_image, "01.png")
    screen.update_image()
    show(screen._screen_image, "02.png")


def test_screen_fake():
    screen = EInkScreen(Interface())
    screen._display = FakeScreen(122, 250)
    screen.update_image()
    show(screen._screen_image, "01.png")


@pytest.mark.skipif(not running_on_pi(), reason="requires a Pi")
def test_live_eink_screen_interface():
    cf = """
    [camera.mode_button]
    file = 'camera-mode'
    button = 6


    [camera.speed_button]
    file = '/etc/tmv/camera-speed'
    button = 5

    [camera.activity]
    led = 0

    [ interface ]
    screen = "EInkScreen"
    """
    
    interface = Interface()
    interface.configs(cf)
    interface.screen.update_display()
    print("Try the buttons!\nmode, speed", file=stderr)
    print(f"{interface.mode_button},{interface.speed_button}")
    start = dt.now()
    while (dt.now() - start < timedelta(seconds=10)):
        print(f"{interface.mode_button.value}, {interface.speed_button.value}")
        print(f"{interface.mode_button.button},{interface.speed_button.button}")
        sleep(1)
    interface.screen.update_image()
    interface.screen.update_display()
    interface.screen._screen_image.save("test_screen_interface.png")
    print("Saved to test_screen_interface.png")


@pytest.mark.skipif(not running_on_pi(), reason="requires a Pi")
def test_live_eink_screen_direct():
    screen = EInkScreen(None)
    screen.test()


def test_screen_interface_fake():
    cf = """

    [camera.mode_button]
    file = 'camera-mode'
    button = 5


    [camera.speed_button]
    file = '/etc/tmv/camera-speed'
    button = 6

    [camera.activity]
    led = 0

    [ interface ]
    screen = "EInkScreen"
    """
    interface = Interface()
    interface.configs(cf)
    interface.screen = EInkScreen(interface)
    interface.screen._display = FakeScreen(122, 250)
    interface.screen.update_image()
    print(f"{interface.mode_button},{interface.speed_button}")
    show(interface.screen._screen_image, "test_screen_interface_fake.png")


def show(image, filename):
    image.save(filename)
    subprocess.run(["gnome-open", filename], check=True)


def test_oled_interface_oled():
    cf = """
    [camera]
    tmv_root = "/tmp"
    interval = 60
    [camera.mode_button]
        button = 20 
    [camera.speed_button]
        button = 16
    [interface]
    screen = "OLEDScreen"
    """
    modefile = Path("/tmp/camera-mode")
    speedfile = Path("/tmp/camera-speed")
    try:
        speedfile.unlink()
    except:
        pass
    try:
        modefile.unlink()
    except: 
        pass
    os.chdir(tempfile.mkdtemp())
    def _init_display_emulated(self):
        """ Enumlate a screen : write to GIF instead of physical screen"""
        self._gif = ''.join(random.choices(string.ascii_uppercase + string.digits, k=3)) + ".gif"
        self._display = gifanim(filename= self._gif, duration=0.1, max_frames=100,mode="1")

    if not running_on_pi():
        #mock GPIO
        tmv.interface.screen.OLEDScreen._init_display = _init_display_emulated
        from gpiozero import Device, LED
        from gpiozero.pins.mock import MockFactory
        Device.pin_factory = MockFactory()

    interface = Interface()
    interface.configs(cf)

    for i in range(10):
        sleep(.1)

    # test paging, mode and speed buttons
    assert interface.screen.page == 1   
    press(interface.screen.key_right)
    assert interface.screen.page == 2
    press(interface.screen.key_left)
    assert interface.screen.page == 1

    assert not modefile.exists()
    assert interface.mode_button.value == AUTO
    press(interface.mode_button.button)
    assert interface.mode_button.value == ON
    assert  modefile.exists()

    assert not speedfile.exists()
    assert interface.speed_button.value == MEDIUM
    press(interface.speed_button.button)
    assert interface.speed_button.value == FAST
    assert  speedfile.exists()


    if not running_on_pi():
        interface.screen._display.write_animation()
        subprocess.run(["gnome-open", interface.screen._gif])
    
    """
    # if using capture() device, it produces pngs.
    import glob
    for f in glob.glob("./luma*.png"):
        subprocess.run(["gnome-open", f])
    """

def test_oled_interface_oled_rel():
    cf = """
    [camera]
    tmv_root = "fredo" # note realative
    interval = 60
    [camera.mode_button]
        button = 20 
    [camera.speed_button]
        button = 16
    [interface]
    screen = "OLEDScreen"
    """
    os.chdir(tempfile.mkdtemp()) # so root should  /tmp/asdfasjdf/fredo
    os.mkdir("fredo")
    def _init_display_emulated(self):
        """ Enumlate a screen : write to GIF instead of physical screen"""
        self._gif = ''.join(random.choices(string.ascii_uppercase + string.digits, k=3)) + ".gif"
        self._display = gifanim(filename= self._gif, duration=0.1, max_frames=100,mode="1")

    if not running_on_pi():
        #mock GPIO
        tmv.interface.screen.OLEDScreen._init_display = _init_display_emulated
        from gpiozero import Device, LED
        from gpiozero.pins.mock import MockFactory
        Device.pin_factory = MockFactory()

    interface = Interface()
    interface.configs(cf)

    modefile = Path("./fredo/camera-mode")
    assert not modefile.exists()
    assert interface.mode_button.value == AUTO
    press(interface.mode_button.button)
    assert interface.mode_button.value == ON
    assert  modefile.exists()

    speedfile = Path("./fredo/camera-speed")
    assert not speedfile.exists()
    assert interface.speed_button.value == MEDIUM
    press(interface.speed_button.button)
    assert interface.speed_button.value == FAST
    assert  speedfile.exists()