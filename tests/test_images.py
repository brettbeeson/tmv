# pylint: disable=line-too-long, logging-fstring-interpolation, dangerous-default-value, import-error,redefined-outer-name, unused-argument

from distutils.dir_util import copy_tree
import os
import shutil
import logging
from datetime import timedelta, date, time, datetime as dt
from pathlib import Path
from tempfile import mkdtemp
import pytest

from tmv.video import VideoMakerDay, VideoMakerConcat
from tmv.video import video_compile_console
from tmv.util import files_from_glob, LOG_FORMAT
from tmv.videotools import VideoInfo, fps, frames
from tmv.exceptions import VideoMakerError
from tmv.images import cal_cross_images, graph_intervals, image_tools_console

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
