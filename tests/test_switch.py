# pylint: disable=import-error,protected-access
from os import chdir, getcwd
from tempfile import TemporaryDirectory, mkdtemp
import logging
import pytest
from tmv.switch import AUTO, OFF, ON, SwitchFactory, get_switch, switches_console
from tmv.camera import CWD_CAMERA_SW_SWITCH_TOML
from tmv.util import LOG_FORMAT


@pytest.fixture(scope="module")
def setup_module():
    chdir(mkdtemp())
    print("Setting cwd to {}".format(getcwd()))
    logging.basicConfig(format=LOG_FORMAT)
    logging.getLogger("tmv.switch").setLevel(logging.DEBUG)


def test_control_console(setup_module, capsys):
    """
    Run switches console, testing output and input via local .toml file
    """
    # make default config in cwd
    with pytest.raises(SystemExit) as excinfo:
        switches_console(["-c","./default.toml"])
        assert excinfo.value.code == 0
    out = capsys.readouterr().out.strip() 
    

    cl = ["-c","./default.toml","on", "off"]
    with pytest.raises(SystemExit) as excinfo:
        switches_console(cl)
        assert excinfo.value.code == 0
    
    with pytest.raises(SystemExit) as excinfo:
        switches_console([])
        assert excinfo.value.code == 0
    out = capsys.readouterr().out.strip() 
    assert out == "on\noff"




def test_switches():
    temp = TemporaryDirectory()
    chdir(temp.name)
    s = get_switch(CWD_CAMERA_SW_SWITCH_TOML)
    assert s.position == AUTO
    s.position = ON
    assert s.position == ON
    assert s.position != AUTO
    #print(getcwd())
    temp.cleanup()