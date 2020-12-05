# pylint: disable=line-too-long, logging-fstring-interpolation, dangerous-default-value, import-error,redefined-outer-name, unused-argument

import os
import logging
from time import sleep
from pathlib import Path
from tempfile import mkdtemp
import pytest

from tmv.util import files_from_glob, LOG_FORMAT
import tmv.interface.app
from tmv.interface.app import app, socketio, camera, create_camera


TEST_DATA = Path(__file__).parent / "testdata"




@pytest.fixture(scope="module")
def setup_module():
    # steart flask and scoketio
    os.chdir(mkdtemp())
    print("Setting cwd to {}".format(os.getcwd()))
    logging.basicConfig(format=LOG_FORMAT)
    logging.getLogger("tmv.web").setLevel(logging.DEBUG)
   

def test_connection1(setup_module):
       
    create_camera(TEST_DATA / 'test-interface.toml')
    
    flask_test_client = app.test_client()

    socketio_test_client = socketio.test_client(app, flask_test_client=flask_test_client)
  
    socketio_test_client.connect()
    r = socketio_test_client.get_received()
    assert r[0]['args'] == "Hello from TMV Camera."
        

    
