# pylint: disable=line-too-long, logging-fstring-interpolation, dangerous-default-value, import-error, redefined-outer-name, unused-argument

import logging
import os
from tempfile import mkdtemp
from tempfile import TemporaryDirectory
from os import chdir
from pathlib import Path
from distutils.dir_util import copy_tree
import pytest
from _datetime import timedelta, datetime as dt

from tmv.videotools import VideoInfo, frames, video_decompile_console
from tmv.util import * # pylint:disable=unused-wildcard-import, wildcard-import
from tmv.video import video_compile_console


TEST_DATA = Path(__file__).parent / "testdata"


@pytest.fixture(scope="function")
def setup_module():
    # steart flask and scoketio
    os.chdir(mkdtemp())
    print("Setting cwd to {}".format(os.getcwd()))
    logging.basicConfig(format=LOG_FORMAT)
    logging.getLogger("tmv.web").setLevel(logging.DEBUG)


def test_video_info(setup_module):
    v1 = VideoInfo(TEST_DATA / "sample1.mp4")
    assert v1.frames == 55
    assert v1.valid
    assert v1.fps == 1

    v2 = VideoInfo(TEST_DATA / "sample2.mp4")
    assert v2.frames == 444
    assert v2.fps == 20

    v3 = VideoInfo(TEST_DATA / "metadata.mp4")
    print(v3)
    assert v3.real_duration == timedelta(seconds=259200)
    assert v3.real_start == dt(2000, 1, 1, 1, 0, 0)


def test_video_decompile_console(setup_module):
    with TemporaryDirectory() as tempd:

        chdir(tempd)

        #  images -> video

        cl = ["--output", "original.mp4", "--log-level",
              "DEBUG", str(TEST_DATA / "1day1m/*.jpg")]
        with pytest.raises(SystemExit) as exc:
            video_compile_console(cl)
        assert exc.value.code == 0
        video_orig = VideoInfo("original.mp4")

        # video -> imags

        logging.getLogger().setLevel(logging.DEBUG)
        cl = ["original.mp4", "--output", tempd]
        with pytest.raises(SystemExit) as exc:
            video_decompile_console(cl)
        assert exc.value.code == 0

        # images -> video (again, from extracted frames)

        cl = ["--output", "frankie.mp4", "--log-level", "DEBUG", "**/*.jpg"]
        with pytest.raises(SystemExit) as exc:
            video_compile_console(cl)
        assert exc.value.code == 0
        video_frankie = VideoInfo("frankie.mp4")  # stein

        for f in list(Path("/tmp/tmv/").rglob("*.jpg")) + list(Path("/tmp/tmv/").rglob("*.mp4")):
            Path(f).unlink()
        copy_tree(".", "/tmp/tmv")

        assert video_frankie.fps == video_orig.fps
        assert pytest.approx(video_frankie.frames, video_orig.frames, abs=1)
        assert video_frankie.duration == video_orig.duration
        assert video_frankie.real_duration == video_orig.real_duration
        assert video_frankie.real_start == video_orig.real_start


def test_video_decompile_nometa(setup_module):
    # this file has no metadata - we have to take a guess of 9 to 5
    with TemporaryDirectory() as tempd:
        logging.getLogger().setLevel(logging.DEBUG)
        cl = [str(TEST_DATA / "2000-01-01-no-meta.mp4"), "--output",
              tempd, "--start", "04:00", "--interval", "30", "-ll", "DEBUG"]
        with pytest.raises(SystemExit) as exc:
            video_decompile_console(cl)
        assert exc.value.code == 0

        tempp = Path(tempd)
        images = sorted(list((tempp/"2000-01-01").glob("*.jpg")))
        assert len(images) == frames(TEST_DATA / "2000-01-01-no-meta.mp4")
        assert str2dt(Path(images[0]).stem) == dt(2000, 1, 1, 4, 0, 0)
        assert pytest.approx(str2dt(
            Path(images[-1]).stem).timestamp(), dt(2000, 1, 1, 19, 0, 0).timestamp(), abs=30)


def test_video_decompile_nometa2(setup_module):
    # this file has no metadata - and is disjoint
    # specify start, end and deduce interval
    with TemporaryDirectory() as tempd:
        logging.getLogger().setLevel(logging.DEBUG)
        cl = [str(TEST_DATA / "2019-11-07-disjoint-no-meta.mp4"), "--output",
              tempd, "--start", "09:55", "--end", "12:15", "-ll", "DEBUG"]
        with pytest.raises(SystemExit) as exc:
            video_decompile_console(cl)
        assert exc.value.code == 0

        tempp = Path(tempd)
        images = sorted(list((tempp/"2019-11-07").glob("*.jpg")))
        assert len(images) == frames(
            TEST_DATA / "2019-11-07-disjoint-no-meta.mp4")
        assert str2dt(Path(images[0]).stem) == dt(2019, 11, 7, 9, 55, 0)
        assert pytest.approx(str2dt(
            Path(images[-1]).stem).timestamp(), dt(2019, 11, 7, 12, 15, 0).timestamp(), abs=30)


def not_test_video_decompile_ocr():
    # this file has no metadata - and is disjoint
    # use ocr to read timestamp
    with TemporaryDirectory() as tempd:
        logging.getLogger().setLevel(logging.DEBUG)
        cl = [str(TEST_DATA / "2019-11-07-disjoint-no-meta.mp4"), "--output",
              tempd, "--start", "09:55", "--interval", "30", "--ocr", "-ll", "DEBUG"]
        with pytest.raises(SystemExit) as exc:
            video_decompile_console(cl)
        assert exc.value.code == 0

        tempp = Path(tempd)
        images = sorted(list((tempp/"2019-11-07").glob("*.jpg")))
        assert len(images) == frames(
            TEST_DATA / "2019-11-07-disjoint-no-meta.mp4")
        assert str2dt(Path(images[0]).stem) == dt(2000, 1, 1, 4, 0, 0)
        assert pytest.approx(str2dt(
            Path(images[-1]).stem).timestamp(), dt(2000, 1, 1, 19, 0, 0).timestamp(), abs=30)
