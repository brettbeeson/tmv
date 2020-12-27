# pylint: disable=line-too-long, logging-fstring-interpolation, dangerous-default-value, import-error,redefined-outer-name, unused-argument

import os
import shutil
import logging
from datetime import timedelta, datetime as dt
from pathlib import Path
import glob
from tempfile import mkdtemp
import pytest

from tmv.video import VideoMakerConcat
from tmv.util import LOG_FORMAT, str2dt
from tmv.images import graph_intervals, image_tools_console

TEST_DATA = Path(__file__).parent / "testdata"


@pytest.fixture(scope="module")
def setup_module():
    os.chdir(mkdtemp())
    print("Setting cwd to {}".format(os.getcwd()))
    logging.basicConfig(format=LOG_FORMAT)
    logging.getLogger("tmv.images").setLevel(logging.DEBUG)


def test_graph():
    mm = VideoMakerConcat()
    mm.files_from_glob(TEST_DATA / "3days1h-holey/*.jpg")
    mm.load_videos()
    graph_intervals(mm.videos)
    graph_intervals(mm.videos, timedelta(hours=2))
    graph_intervals(mm.videos, timedelta(hours=24))
    # assert False
    # check visually


def test_videotools_console():
    cl = ["graph", "--bin", "2 hours", "--log-level",
          "DEBUG", str(TEST_DATA / "1day1m/*.jpg")]
    with pytest.raises(SystemExit) as exc:
        image_tools_console(cl)
    assert exc.value.code == 0


def test_rename_console(setup_module):
    """ Rename three files with only EXIF data """
    for f in glob.glob(str(TEST_DATA / "rename" / "*.*",)):
        p = Path(f)
        shutil.copyfile(f, p.name)

    cl = ["rename", "--log-level","DEBUG", "*.*"]
    with pytest.raises(SystemExit):
        image_tools_console(cl)

    renamed = list(glob.glob("*"))
    renamed.sort()
    assert len(renamed) == 3
    assert str2dt(renamed[0]) == dt(2019, 3, 30, 17, 40, 48)
    assert str2dt(renamed[1]) == dt(2019, 3, 30, 18, 4, 6)
    assert str2dt(renamed[2]) == dt(2020, 12, 25, 19,22,28)
