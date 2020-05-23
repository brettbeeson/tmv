# pylint: disable=redefined-outer-name,unused-argument
import logging
import pytest
from tmv.monitor import SSHTunnels, tunnel_console
from tmv.util import LOG_FORMAT


@pytest.fixture()
def setup_debug():
    logging.getLogger("tmv.monitor").setLevel(logging.DEBUG)
    logging.basicConfig(format=LOG_FORMAT)


def test_console(setup_debug):
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
