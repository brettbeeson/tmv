# pylint: disable=import-error,protected-access
from os import chdir, getcwd
from tempfile import TemporaryDirectory, mkdtemp
import logging
import pytest
from pathlib import Path
from tmv.buttons import AUTO, OFF, ON, ModeButton

from tmv.camera import Camera, FakePiCamera
from tmv.util import LOG_FORMAT

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

    s = ModeButton()
    s.set(button_path="./buttonfile")
    assert s.value == AUTO
    s.value = ON
    assert s.value == ON
    assert s.value != AUTO
