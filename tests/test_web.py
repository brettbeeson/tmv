# pylint: disable=line-too-long, logging-fstring-interpolation, dangerous-default-value, import-error,redefined-outer-name, unused-argument

import os
import logging
from pathlib import Path
from tempfile import mkdtemp
import pytest
from tmv.util import files_from_glob, LOG_FORMAT
#import tmv.web.app

TEST_DATA = Path(__file__).parent / "testdata"

@pytest.fixture(scope="module")
def setup_module():
    # steart flask and scoketio
    os.chdir(mkdtemp())
    print("Setting cwd to {}".format(os.getcwd()))
    logging.basicConfig(format=LOG_FORMAT)
    logging.getLogger("tmv.images").setLevel(logging.DEBUG)

@pytest.fixture
def client():
    #db_fd, flaskr.app.config['DATABASE'] = tempfile.mkstemp()
    #flaskr.app.config['TESTING'] = True

    #with tmv.web.app.test_client() as client:
    #    with tmv.web.app.app_context():
    #        pass
    #    yield client
    pass
    #os.close(db_fd)
    #os.unlink(flaskr.app.config['DATABASE'])
