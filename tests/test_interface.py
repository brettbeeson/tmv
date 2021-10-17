# pylint: disable=line-too-long, logging-fstring-interpolation, dangerous-default-value, import-error,redefined-outer-name, unused-argument

import os
import logging
#from time import sleep

from pathlib import Path
from tempfile import mkdtemp
import pytest
from tmv.config import MEDIUM

from tmv.util import LOG_FORMAT
from . import running_on_pi


TEST_DATA = Path(__file__).parent / "testdata"


@pytest.fixture(scope="function")
def setup_test():
    # start flask and socketio
    
    os.chdir(mkdtemp())
    print(f"Setting cwd to {os.getcwd()}")
    logging.basicConfig(format=LOG_FORMAT)
    logging.getLogger("tmv.web").setLevel(logging.DEBUG)


def test_connection(setup_test):
    from tmv.interface.app import app, socketio, interface_console, interface, Interface
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
    assert len(r[0]['args'][0]) == len(cf.read_text(encoding='utf-8'))


def test_buttons(setup_test):
    from tmv.interface.app import app, socketio, interface_console, interface, Interface
    cf = Path(TEST_DATA / 'test-interface.toml')

    interface.config(cf)
    interface.tmv_root = "."

    flask_test_client = app.test_client()

    socketio_test_client = socketio.test_client(
        app, flask_test_client=flask_test_client)

    socketio_test_client.connect()
    r = socketio_test_client.get_received()
    assert r[0]['args'] == "Hello from TMV!"

    socketio_test_client.emit("mode", "off")
    socketio_test_client.emit("speed", "fast")
    m = interface.mode_button.path.read_text(encoding='utf-8')
    s = interface.speed_button.path.read_text(encoding='utf-8')
    assert m == "off"
    assert s == "fast"


def manual_test_start_server(setup_test):
    """ Test webpage manually """
    from tmv.interface.app import app, socketio, interface_console, interface, Interface
    cf = Path(TEST_DATA / 'test-interface.toml')
    interface.config(cf)
    interface.latest_image = (TEST_DATA / 'interface/latest-image.jpg')
    interface_console(
        ["--config-file", "tests/testdata/test-interface.toml", "-ll", "DEBUG"],)


# if __name__ == '__main__':
#    manual_test_start_server(None)

@pytest.mark.skipif(not running_on_pi(), reason="requires a Pi")
def test_buttons2():
    from tmv.interface.app import app, socketio, interface_console, interface, Interface
    """ Test interval change with speed button"""
    c = Interface()
    cf = """
    [interface.mode_button]
    button = 20
    """

    c.configs(cf)
    assert c.mode_button.button == 20
    assert c.speed_button.value == MEDIUM
        
