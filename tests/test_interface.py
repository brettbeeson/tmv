# pylint: disable=line-too-long, logging-fstring-interpolation, dangerous-default-value, import-error,redefined-outer-name, unused-argument

import os
import logging
#from time import sleep
from pathlib import Path
from tempfile import mkdtemp
import pytest

from tmv.util import LOG_FORMAT
from tmv.interface.app import app, socketio, interface_console, interface, buttons_console


TEST_DATA = Path(__file__).parent / "testdata"


@pytest.fixture(scope="function")
def setup_module():
    # steart flask and scoketio
    os.chdir(mkdtemp())
    print("Setting cwd to {}".format(os.getcwd()))
    logging.basicConfig(format=LOG_FORMAT)
    logging.getLogger("tmv.web").setLevel(logging.DEBUG)


def test_connection(setup_module):

    cf = Path(TEST_DATA / 'test-interface.toml')

    interface.config(cf)

    flask_test_client = app.test_client()

    socketio_test_client = socketio.test_client(
        app, flask_test_client=flask_test_client)

    socketio_test_client.connect()
    r = socketio_test_client.get_received()
    assert r[0]['args'] == "Hello from TMV!"

    socketio_test_client.emit("req-camera-config")
    r = socketio_test_client.get_received()
    # read config back from server
    assert r[0]['name'] == "camera-config"
    assert len(r[0]['args'][0]) == len(cf.read_text())


def test_buttons(setup_module):

    cf = Path(TEST_DATA / 'test-interface.toml')

    interface.config(cf)

    flask_test_client = app.test_client()

    socketio_test_client = socketio.test_client(
        app, flask_test_client=flask_test_client)

    socketio_test_client.connect()
    r = socketio_test_client.get_received()
    assert r[0]['args'] == "Hello from TMV!"

    socketio_test_client.emit("mode", "off")
    socketio_test_client.emit("speed", "fast")
    m = interface.mode_button.path.read_text()
    s = interface.speed_button.path.read_text()
    assert m == "off"
    assert s == "fast"


def test_control_console(setup_module, capsys):
    """
    Run buttons console, testing output. Use local button files.
    """

    local_config = TEST_DATA / "test-interface.toml"  # local buttons

    # default - should create files
    with pytest.raises(SystemExit) as excinfo:
        buttons_console(["-c", str(local_config)])
        assert excinfo.value.code == 0
    out = capsys.readouterr().out.strip()
    assert out == "on\nslow"

    # set
    cl = ["-c", str(local_config), "on", "slow"]
    with pytest.raises(SystemExit) as excinfo:
        buttons_console(cl)
        assert excinfo.value.code == 0

    # get (from file - should be the set'd values)
    with pytest.raises(SystemExit) as excinfo:
        buttons_console(["-c", str(local_config)])
        assert excinfo.value.code == 0
    out = capsys.readouterr().out.strip()
    assert out == "on\nslow"


def manual_test_start_server(setup_module):
    """ Test webpage manually """

    cf = Path(TEST_DATA / 'test-interface.toml')
    interface.config(cf)
    interface.latest_image = (TEST_DATA / 'interface/latest-image.jpg')
    interface_console(
        ["--config-file", "tests/testdata/test-interface.toml", "-ll", "DEBUG"],)


# if __name__ == '__main__':
#    manual_test_start_server(None)
