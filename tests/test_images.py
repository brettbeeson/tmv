from os import chdir, getcwd
import logging
from tempfile import mkdtemp
from pathlib import Path
import pytest
# pylint: disable=import-error
from tmv.images import image_tools_console
from tmv.util import LOG_FORMAT

@pytest.fixture()
def setup_test():
    chdir(mkdtemp())
    logging.basicConfig(format=LOG_FORMAT)
    logging.getLogger("tmv.images").setLevel(logging.DEBUG)
    print("Setting cwd to {}".format(getcwd()))


def on_demand_calendar():
    cl = ["cal"]
    Path("/tmp/cal").mkdir(exist_ok=True)
    chdir("/tmp/cal")
    with pytest.raises(SystemExit) as exc:
        image_tools_console(cl)
    assert exc.value.code == 0
