# pylint: disable=import-error,protected-access, redefined-outer-name, unused-argument
from os import chdir, getcwd
from tempfile import mkdtemp
import logging
import pytest
from tmv.config import *  # pylint: disable=unused-wildcard-import, wildcard-import
from tmv.util import LOG_FORMAT
from tmv.buttons import StatefulButton

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
