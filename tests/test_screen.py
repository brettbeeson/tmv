# pylint: disable=unused-import, import-outside-toplevel,protected-access, line-too-long, logging-fstring-interpolation, logging-not-lazy

import logging
import subprocess
import os
import random
import string
from pathlib import Path
from time import sleep
from sys import stderr
import tempfile
import pytest

#try:
from luma.emulator.device import gifanim
#except ModuleNotFoundError as e:
#    print(f"luma not installed: {e}",file=stderr)

import tmv
from tmv.interface.screen import OLEDScreen
from tmv.interface.interface import Interface
from tmv.util import LOG_FORMAT
from . import running_on_pi
from tmv.buttons import*  # pylint: disable=unused-import, unused-wildcard-import

show_images = False

TEST_DATA = Path(__file__).parent / "testdata" / "screen"


def show(image, filename):
    image.save(filename)
    if show_images:
        subprocess.run(["gnome-open", filename], check=True)


@pytest.fixture(scope="function")
def setup_test():
    os.chdir(tempfile.mkdtemp())
    print("Setting cwd to {}".format(os.getcwd()))
    logging.basicConfig(format=LOG_FORMAT)
    logging.getLogger("tmv.screen").setLevel(logging.DEBUG)


def press(button):
    button.pin.drive_low()
    sleep(.25)
    button.pin.drive_high()


class FakeScreen:
    """[summary]    """

    def __init__(self, w, h):
        self.height = w
        self.width = h


def test_oled_interface_oled(setup_test):
    cf = """
    [camera]
    tmv_root = "."
    interval = 60
    [interface.mode_button]
        button = 20 
    [interface.speed_button]
        button = 16
    [interface]
    screen = "OLEDScreen"
    """

    def _init_display_emulated(self):
        """ Enumlate a screen : write to GIF instead of physical screen"""
        self._gif = ''.join(random.choices(
            string.ascii_uppercase + string.digits, k=3)) + ".gif"
        self._display = gifanim(
            filename=self._gif, duration=0.1, max_frames=100, mode="1")

    if not running_on_pi():
        # mock GPIO
        tmv.interface.screen.OLEDScreen._init_display = _init_display_emulated
        from gpiozero import Device
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

    modefile = Path("camera-mode")
    assert not modefile.exists()
    assert interface.mode_button.value == AUTO
    press(interface.mode_button.button)  # video
    press(interface.mode_button.button)  # ON
    assert interface.mode_button.value == ON
    assert modefile.exists()
    speedfile = Path("camera-speed")
    assert not speedfile.exists()
    assert interface.speed_button.value == MEDIUM
    press(interface.speed_button.button)
    assert interface.speed_button.value == FAST
    assert speedfile.exists()

    if not running_on_pi() and show_images:
        interface.screen._display.write_animation()
        subprocess.run(["gnome-open", interface.screen._gif])
