# pylint: disable=import-error,protected-access
from pathlib import Path
import logging
from os import chdir, getcwd
from tmv.controller import AUTO, Controller, LOGGER, OFF, ON, Switches, control_console, Unit
from tmv.util import LOG_FORMAT
import tmv
from tempfile import TemporaryDirectory
from pkg_resources import resource_filename


def test_software_controller_faked(monkeypatch, caplog):
    c = """
    [controller]
        [controller.switches.camera]
            file = '/etc/tmv/camera-switch'
        [controller.switches.upload]
            file = '/etc/tmv/upload-switch'   
    """

    def fake_run(c):
        LOGGER.info(f"running {c} fakely")
        return "", ""  # stdout, stderr

    logging.basicConfig(format=LOG_FORMAT)
    LOGGER.setLevel(logging.DEBUG)
    monkeypatch.setattr(tmv.util, 'run_and_capture', fake_run)
    s = Switches()
    s.configs(c)
    con = Controller(s)
    con._camera_unit.Active = lambda: True
    con._upload_unit.Active = lambda: True
    con.update_services()
    Path("/etc/tmv/camera-switch").write_text("auto")
    Path("/etc/tmv/upload-switch").write_text("on")
    assert s['camera'] == AUTO
    assert s['upload'] == ON
    Path("/etc/tmv/camera-switch").write_text("off")
    Path("/etc/tmv/upload-switch").write_text("off")
    assert s['camera'] == OFF
    assert s['upload'] == OFF
    con.update_services()

    # start services if not running
    con._camera_unit.Active = lambda: False
    con._upload_unit.Active = lambda: False
    s['camera'] = AUTO
    s['upload'] = ON
    caplog.clear()
    con.update_services()
    assert "running ['systemctl', 'start', 'tmv-s3-upload.service']" in caplog.text
    assert "running ['systemctl', 'start', 'tmv-camera.service']" in caplog.text

    # don't start if already running
    con._camera_unit.Active = lambda: True
    con._upload_unit.Active = lambda: True
    caplog.clear()
    con.update_services()
    assert 'starting' not in caplog.text

    # restart if already running if forced to
    con._camera_unit.Active = lambda: True
    con._upload_unit.Active = lambda: True
    caplog.clear()
    con.reset_services()
    assert 'starting' not in caplog.text

    # update with the services running: set changed button but don't restart
    s['camera'] = OFF
    s['upload'] = OFF
    con.update_services()
    s['camera'] = ON
    s['upload'] = ON
    caplog.clear()
    con.update_services()
    assert 'changed' in caplog.text
    assert 'starting' not in caplog.text

def test_control_console(capsys):
    """
    Requires write access to /etc/tmv/
    """
    s = Switches()
    s.configs(Switches.DLFT_SW_CONFIG)
    cl = ["on", "off"]
    control_console(cl)
    assert s['camera'] == ON
    assert s['upload'] == OFF
    cl = ["auto", "on"]
    control_console(cl)
    assert s['camera'] == AUTO
    assert s['upload'] == ON
    cl = []

    control_console(cl)
    assert capsys.readouterr().out.strip() == "auto on"

def test_switches():
    temp = TemporaryDirectory() 
    chdir(temp.name)
    s = Switches()
    s.configs(Switches.CWD_SW_CONFIG)
    assert s['camera'] == OFF
    assert s['upload'] == OFF
    s['camera'] = ON
    s['upload'] = OFF
    assert s['camera'] == ON
    assert s['upload'] == OFF
    print(getcwd())
    temp.cleanup()


def test_config():
    s = Switches()
    c = Path(resource_filename("tmv", 'resources/camera.toml')).read_text('UTF-8')
    s.configs(c)


def test_units_status():
    assert Unit("syslog.service").active()
    assert not Unit("no-there.service").active()
