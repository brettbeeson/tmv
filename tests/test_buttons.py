# pylint: disable=import-error,protected-access
from os import chdir, getcwd
from tempfile import TemporaryDirectory, mkdtemp
import logging
import pytest
from pathlib import Path
from tmv.buttons import AUTO, OFF, ON, ModeButton

from tmv.camera import buttons_console, Camera, FakePiCamera
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


def test_control_console(setup_module, capsys):
    """
    Run buttons console, testing output. Use local button files.
    """
    
    local_config = Path("./camera.toml")
    local_config.write_text(cwd_buttons)

    # default - should create files
    with pytest.raises(SystemExit) as excinfo:
        buttons_console(["-c",str(local_config)])
        assert excinfo.value.code == 0
    out = capsys.readouterr().out.strip() 
    assert out == "auto\nmedium"
    
    # set
    cl = ["-c",str(local_config),"on", "slow"]
    with pytest.raises(SystemExit) as excinfo:
        buttons_console(cl)
        assert excinfo.value.code == 0
    
    # get (from file - should be the set'd values)
    with pytest.raises(SystemExit) as excinfo:
        buttons_console(["-c",str(local_config)])
        assert excinfo.value.code == 0
    out = capsys.readouterr().out.strip() 
    assert out == "on\nslow"


def test_buttons(setup_module):

    s = ModeButton()
    s.set(button_path="./buttonfile")
    assert s.value == AUTO
    s.value = ON
    assert s.value == ON
    assert s.value != AUTO
