# pylint: disable=unused-import, import-outside-toplevel,protected-access, line-too-long, logging-fstring-interpolation, logging-not-lazy
import subprocess
import os
from pathlib import Path
from time import sleep
from sys import stderr
from _datetime import datetime as dt, timedelta
import pytest

from PIL.ImageOps import invert
from tmv.interface.screen import TMVScreen
from tmv.camera import Interface
from . import running_on_pi

TEST_DATA = Path(__file__).parent / "testdata" / "screen"


class FakeScreen:
    """[summary]    """

    def __init__(self, w, h):
        self.height = w
        self.width = h


def test_screen_image_display():
    # todo: check images location
    screen = TMVScreen(Interface())
    os.chdir(TEST_DATA)
    #self._screen_image
    screen._interface._latest_image = "1.jpg"
    screen._display = FakeScreen(122, 250)
    screen.update_image() # logo
    show(screen._screen_image, "01.png")
    screen.update_image()
    show(screen._screen_image, "02.png")


def test_screen_fake():
    screen = TMVScreen(Interface())
    screen._display = FakeScreen(122, 250)
    screen.update_image()
    show(screen._screen_image, "01.png")


@pytest.mark.skipif(not running_on_pi(), reason="requires a Pi")
def test_screen_interface():
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
    screen = true
    """
    interface = Interface()
    interface.configs(cf)
    screen = TMVScreen(interface)
    screen.update_display()
    print("Try the buttons!\nmode, speed", file=stderr)
    print(f"{interface.mode_button},{interface.speed_button}")
    start = dt.now()
    while (dt.now() - start < timedelta(seconds=10)):
        print(f"{interface.mode_button.value}, {interface.speed_button.value}")
        print(f"{interface.mode_button.button},{interface.speed_button.button}")
        sleep(1)
    screen.update_image()
    screen.update_display()
    screen._screen_image.save("test_screen_interface.png")
    print("Saved to test_screen_interface.png")


@pytest.mark.skipif(not running_on_pi(), reason="requires a Pi")
def test_screen_direct():

    screen = TMVScreen(None)
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
    screen = true
    """
    interface = Interface()
    interface.configs(cf)
    screen = TMVScreen(interface)
    screen._display = FakeScreen(122, 250)
    screen.update_image()
    print(f"{interface.mode_button},{interface.speed_button}")
    show(screen._screen_image, "test_screen_interface_fake.png")


def show(image, filename):
    image.save(filename)
    subprocess.run(["gnome-open", filename], check=True)
