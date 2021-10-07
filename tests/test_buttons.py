# pylint: disable=import-error,protected-access, redefined-outer-name, unused-argument
from os import chdir, getcwd
from tempfile import mkdtemp
import logging
from datetime import datetime as dt, timedelta
from time import sleep
import pytest
from tmv.config import *  # pylint: disable=unused-wildcard-import, wildcard-import
from tmv.util import LOG_FORMAT, uptime
from tmv.buttons import StatefulButton
from tmv.interface.interface import Interface
from . import running_on_pi
from tmv.buttons import ON, OFF, AUTO, SLOW, MEDIUM, FAST  # pylint: disable=unused-import


cwd_buttons = """
    [camera.mode_button]
        file = 'camera-mode'
    [camera.speed_button]
        file = 'camera-speed'
"""


@pytest.fixture(scope="module")
def setup_module():
    chdir(mkdtemp())
    print("Setting cwd to {}".format(getcwd()))
    logging.basicConfig(format=LOG_FORMAT)
    logging.getLogger("tmv.button").setLevel(logging.DEBUG)


def test_buttons(setup_module):
    s = StatefulButton("buttonfile", MODE_BUTTON_STATES)
    assert s.value == ON
    s.value = AUTO
    assert s.value == AUTO
    assert s.value != ON

# todo: test read-only and permission errors

@pytest.mark.skipif(not running_on_pi(), reason="requires a Pi")
def test_oled_buttons(setup_module):
    cf = """

    [camera]
    tmv_root = "/home/pi/tmv-data"  
    
    [camera.mode_button]
    file = 'camera-mode'
    button = 21

    [camera.speed_button]
    file = 'camera-speed'
    button = 20

    [camera.activity]
    led = 0

    [ interface ]
    screen = "OLEDScreen"
    """

    interface = Interface()
    interface.configs(cf)
    # run for 1m
    start = dt.now()
    while dt.now() - start < timedelta(seconds=60):
        sleep(1)
        print(f"{interface.speed_button.value},{interface.mode_button.value}")

def test_lru_cache_timeout():
    # test cache of 10s
    u1 = uptime()
    sleep(1)
    u2 = uptime()
    sleep(10)
    u3 = uptime()
    assert u1 == u2
    assert u1 != u3

if __name__ == '__main__':
    test_oled_buttons(None)
