# pylint: disable=redefined-outer-name,unused-argument
import logging
import pytest
from tmv.monitor import SSHTunnels, sshauto_console
from tmv.util import LOG_FORMAT


@pytest.fixture()
def setup_debug():
    logging.getLogger("tmv.monitor").setLevel(logging.DEBUG)
    logging.basicConfig(format=LOG_FORMAT)


def test_console(setup_debug):
    cl = [""]
    with pytest.raises(SystemExit) as exc:
        sshauto_console(cl)
    assert exc.value.code == 0

    cl = ["fail", "--users", "user1", "user2"]
    with pytest.raises(SystemExit) as exc:
        sshauto_console(cl)
    assert exc.value.code == 2

def test_console_live(setup_debug):
    # nneds a tunnel to 'queen'
    cl = ["queen", "--users", "bbeeson", "--dry-run"]
    with pytest.raises(SystemExit) as exc:
        sshauto_console(cl)
    assert exc.value.code == 0

    cl = ["coolhost", "--users", "bbeeson", "--dry-run"]
    with pytest.raises(SystemExit) as exc:
        sshauto_console(cl)
    assert exc.value.code == 0

    cl = ["nohost", "--users", "bbeeson", "--dry-run"]
    with pytest.raises(SystemExit) as exc:
        sshauto_console(cl)
    assert exc.value.code == 2
