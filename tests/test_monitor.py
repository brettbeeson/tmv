# pylint: disable=redefined-outer-name,unused-argument
import logging
import os
import shutil
from pathlib import Path
from filecmp import cmp
import pytest

from tmv.monitor import SSHTunnels, tunnel_console
from tmv.util import LOG_FORMAT

TEST_DATA = Path(__file__).parent / "testdata"


@pytest.fixture()
def setup_debug():
    logging.getLogger("tmv.monitor").setLevel(logging.DEBUG)
    logging.basicConfig(format=LOG_FORMAT)


def test_console(setup_debug):

    # config needs an arg
    cl = ["--user", "bbeeson","--config"]
    with pytest.raises(SystemExit) as exc:
        tunnel_console(cl)
    assert exc.value.code == 2

    cl = [""]
    with pytest.raises(SystemExit) as exc:
        tunnel_console(cl)
    assert exc.value.code == 0

    cl = ["fail", "--user", "user1", "user2"]
    with pytest.raises(SystemExit) as exc:
        tunnel_console(cl)
    assert exc.value.code == 2


def test_console_live(setup_debug):
    # Test needs a loop tunnel to localhost and a ~/.id == coolhost:
    # ssh -N -R 0:localhost:22 localhost
    # echo coolhost > ~/.id
    cl = ["queen", "--user", "bbeeson", "--dry-run"]
    with pytest.raises(SystemExit) as exc:
        tunnel_console(cl)
    assert exc.value.code == 0



    cl = ["coolhost", "--user", "bbeeson", "--dry-run"]
    with pytest.raises(SystemExit) as exc:
        tunnel_console(cl)
    assert exc.value.code == 0

    cl = ["nohost", "--user", "bbeeson", "--dry-run"]
    with pytest.raises(SystemExit) as exc:
        tunnel_console(cl)
    assert exc.value.code == 2


def test_ssh_config(setup_debug, tmp_path):
    """
        Test adding / modifying an entry in ssh/config.
        Requires loopback tunnel:
        ssh -N -R 0:localhost:22 localhost
    """
    os.chdir(tmp_path)
    
    ssh_tunnels = SSHTunnels(users=["bbeeson"])
    c0 = (TEST_DATA / "test_ssh_config").read_text()
    # run and add 'queen'
    c1 = ssh_tunnels.update_config(TEST_DATA / "test_ssh_config")
    # run and do nothing
    c2 = ssh_tunnels.update_config(TEST_DATA / "test_ssh_config")
    assert len(c1) > len(c0)
    assert len(c1) == len(c2)
    
    # c_ref = (TEST_DATA / "test_ssh_config2").read_text()
    # should have just added queen
    #assert c2 == c_ref
