# pylint: disable=unused-import, import-outside-toplevel,protected-access, line-too-long, logging-fstring-interpolation, logging-not-lazy

import subprocess
import os
import random, string
from pathlib import Path
from time import sleep
from sys import stderr
from _datetime import datetime as dt, timedelta
import pytest

#from PIL.ImageOps import invert

from luma.emulator.device import capture, gifanim
from luma.core.virtual import terminal, snapshot, viewport
from luma.oled.device import sh1106

import tmv
from tmv.interface.screen import EInkScreen, OLEDScreen
from tmv.interface.interface import Interface
#from tmv.util import interval_speeded
from . import running_on_pi


TEST_DATA = Path(__file__).parent / "testdata" / "screen"


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


def uuuuuuuest_oled():
    w = 128
    h = 64
    try:
        device = sh1106(max_frames=100)
    except Exception as e:
        print(f"Falling back to emulator: {e}")
        if Path("test_oled.gif").exists():
            Path("test_oled.gif").unlink()
        device = gifanim(max_frames=100, filename="test_oled.gif")

#    term = terminal(device)
    p1 = make_snapshot(w, h, "hi!", interval=1)
    p2 = make_snapshot(w, h, "thre", interval=1)
    pages = [p1, p2]
    virtual = viewport(device, w, h*2)
    virtual.add_hotspot(p1, (0, 0))
    virtual.add_hotspot(p2, (0, h))
    for _ in range(3):
        virtual.set_position((0, 0))
        sleep(1)
        virtual.set_position((0, h))
        sleep(1)

    if Path("test_oled.gif").exists():
        subprocess.run(["gnome-open", "luma_anim.gif"], check=True)


def make_snapshot(width, height, text, interval=1):

    def render(draw, width, height):
        t = text

        size = draw.multiline_textsize(t)
        if size[0] > width:
            t = text.replace(" ", "\n")
            size = draw.multiline_textsize(t)

        left = (width - size[0]) // 2
        top = (height - size[1]) // 2
        draw.multiline_text((left, top), text=t, align="center", spacing=-2)

    return snapshot(width, height, render, interval=interval)


def test_oled_interface_oled():
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
    screen = "OLEDScreen"
    """

    def _init_display_emulated(self):
        """ Enumlate a screen : write to GIF instead of physical screen"""
        self._gif = ''.join(random.choices(string.ascii_uppercase + string.digits, k=3)) + ".gif"
        self._display = gifanim(filename= self._gif, duration=0.1, max_frames=100,mode="1")

    if not running_on_pi():
        tmv.interface.screen.OLEDScreen._init_display = _init_display_emulated

    interface = Interface()
    interface.configs(cf)

    print(f"Buttons: {interface.mode_button},{interface.speed_button}")

    for i in range(10):
        if running_on_pi():
            sleep(.1)
        interface.screen.update_display()

    if not running_on_pi():
        interface.screen._display.write_animation()
        subprocess.run(["gnome-open", interface.screen._gif])
    
    """
    # if using capture() device, it produces pngs.
    import glob
    for f in glob.glob("./luma*.png"):
        subprocess.run(["gnome-open", f])
    """
