# pylint: disable=import-error,protected-access, redefined-outer-name, unused-argument
from os import chdir, getcwd
from tempfile import mkdtemp
import logging
from datetime import datetime as dt, timedelta
from time import sleep
import pytest
from tmv.config import *  # pylint: disable=unused-wildcard-import, wildcard-import
from tmv.util import LOG_FORMAT
from tmv.buttons import StatefulButton
from tmv.interface.interface import Interface


cwd_buttons = """
    [camera.mode_button]
        file = './camera-mode'
    [camera.speed_button]
        file = './camera-speed'
"""


@pytest.fixture(scope="module")
def setup_module():
    chdir(mkdtemp())
    print("Setting cwd to {}".format(getcwd()))
    logging.basicConfig(format=LOG_FORMAT)
    logging.getLogger("tmv.button").setLevel(logging.DEBUG)


def test_buttons(setup_module):
    s = StatefulButton("./buttonfile", MODE_BUTTON_STATES)
    assert s.value == ON
    s.value = AUTO
    assert s.value == AUTO
    assert s.value != ON

# todo: test read-only and permission errors


def test_oled_buttons(setup_module):
    cf = """

    [camera.mode_button]
    file = './camera-mode'
    button = 21

    [camera.speed_button]
    file = './camera-speed'
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

if __name__ == '__main__':
    test_oled_buttons(None)
