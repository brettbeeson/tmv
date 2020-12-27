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
from tmv.images import cal_cross_images

TEST_DATA = Path(__file__).parent / "testdata"

# 365 days @ 1h with a moving cross
CAL_CROSS_IMAGES = str(cal_cross_images(TEST_DATA) / "*.jpg")


@pytest.fixture(scope="module")
def setup_module():
    os.chdir(mkdtemp())
    print("Setting cwd to {}".format(os.getcwd()))
    logging.basicConfig(format=LOG_FORMAT)
    logging.getLogger("tmv.video").setLevel(logging.DEBUG)


def test_valid(setup_module):
    # expect warnings of invalid files
    logging.getLogger("tmv.video").setLevel(logging.ERROR)
    mm = VideoMakerDay()
    mm.files_from_glob(["invalid/*.jpg"])
    with pytest.raises(VideoMakerError):
        mm.load_videos()


def notst_graph(self):
    mm = VideoMakerConcat()
    mm.files_from_glob(["3days1m/*.jpg"])
    mm.load_videos()
    #mm.graph_intervals(timedelta(seconds=3600))
    return


def test_vsync_cont(setup_module):
    mm = VideoMakerDay()
    print("DISCONTINUOUS SET | CFR-PADDED")
    mm.files_from_glob((TEST_DATA / "discont-stamped/*.jpg"))  # 228 files
    mm.load_videos()
    nfiles = len(mm.videos[0].images)

    assert nfiles == 228

    print("DISCONTINUOUS SET | CFR-EVEN")
    mm.write_videos(filename="dis-cfr-even.mp4",
                    vsync="cfr-even", force=True, speedup=60)
    f = frames("dis-cfr-even.mp4")
    print("Write {} and read {}. fps_avg={} fps_max={}"
          .format(nfiles, f, mm.videos[0].fps_video_avg(speedup=60), mm.videos[0].fps_video_max(speedup=60)))

    print("DISCONTINUOUS SET | VFR")
    mm.write_videos(filename="dis-vfr.mp4",
                    vsync="vfr", force=True, speedup=60)
    nfiles = len(mm.videos[0].images)
    f = frames("dis-vfr.mp4")
    print("Write {} and read {}. fps_avg={} fps_max={}"
          .format(nfiles, f, mm.videos[0].fps_video_avg(speedup=60), mm.videos[0].fps_video_max(speedup=60)))
    assert f == 228, "Got {} frames instead of expected 404".format(f)

    print("CONTINUOUS SET | CFR")
    mm = VideoMakerDay()
    mm.files_from_glob(TEST_DATA / "cont-stamped/*.jpg")
    mm.load_videos()
    mm.write_videos(
        filename="con-cfr-even.mp4",
        vsync="cfr-even",
        force=True,
        speedup=60)
    m = mm.videos[0]
    nfiles = len(m.images)
    f = frames("con-cfr-even.mp4")
    print("Write {} and read {}. fps_avg={} fps_max={}"
          .format(nfiles, f, m.fps_video_avg(speedup=60), m.fps_video_max(speedup=60)))
    assert nfiles == f, "Got {} frames, expected {}".format(f, nfiles)
    print("CONTINUOUS SET | VFR")
    mm.write_videos(filename="con-vfr.mp4",
                    vsync="vfr", force=True, speedup=60)
    nfiles = len(mm.videos[0].images)
    m = mm.videos[0]
    f = frames("con-vfr.mp4")
    print("Write {} and read {}. fps_avg={} fps_max={} "
          .format(nfiles, f, m.fps_video_avg(speedup=60), m.fps_video_max(speedup=60) / 60))
    assert f == 404, "Got {} frames, expected {}".format(f, 404)


def test_rename(setup_module):
    print(os.getcwd())
    try:
        shutil.rmtree("temp-renamed")
    except FileNotFoundError:
        pass
    shutil.copytree(TEST_DATA / "rename", "temp-renamed")
    mm = VideoMakerDay()
    mm.files_from_glob(["temp-renamed/*.JPG"])
    mm.load_videos()
    mm.rename_images()



def txestDayMaker():
    mm = VideoMakerDay()
    mm.cache = False
    mm.files_from_glob([r"**\*.jpg"])
    mm.load_videos()
    #mm.save_videos()
    # print("%s"%mm)
    # [print(m) for m in  mm.videos]
    assert len(mm.videos) == 3


def txestDayHourMaker():
    mm = VideoMakerDay()
    mm.files_from_glob([r"**\*.jpg"])
    mm.cache = False
    mm.verbose = True
    mm.dayStartTime = time(8)
    mm.dayEndTime = time(17)
    mm.daySliceLength = timedelta(hours=3)
    mm.load_videos()
 #   mm.save_videos()

    print("%s" % mm)
    # [print(m) for m in  mm.videos]
    assert len(mm.videos) == 1
    assert len(mm.videos[0].images) == 122
    assert mm.videos[0].images[29].datetimeTaken.date() == date(
        2015, 7, 3)
    assert mm.videos[0].images[30].datetimeTaken.date() == date(
        2015, 7, 4)


def test_console_fps_speed(setup_module):
    #                                   input           output
    # dur_real  dur_video   speedup     frames          frames
    #                                   @1/60fps_real   @25fps_video
    # 7 days    1 min       x10080      10800           1500               keep 50% of frames
    # 30 days   2 min       x21600      43200           3000               keep 10%
    # 1 year    10 min      x52560      525600          15000              keep 3%
    #
    l = logging.getLogger("tmv.video")
    l.setLevel(logging.DEBUG)
    files = str(TEST_DATA / "3days1h/*.jpg")
    images = files_from_glob([files])
    cl = [
        "--output", "1-default.mp4",
        "--log-level", "DEBUG",
        *images
    ]
    with pytest.raises(SystemExit) as exc:
        video_compile_console(cl)
    assert exc.value.code == 0
    f = frames("1-default.mp4")
    assert f == 72

    cl = [
        "--output", "2-25fps.mp4",
        "--log-level", "DEBUG",
        "--fps", "25",
        *images
    ]
    with pytest.raises(SystemExit) as exc:
        video_compile_console(cl)
    assert exc.value.code == 0
    assert frames("2-25fps.mp4") == 72

    # @25fps the impliciti sp[eedup, as used above is 90000
    # test 9000
    fn = "3-25fps-9000x.mp4"
    cl = [
        "--output", fn,
        "--log-level", "DEBUG",
        "--fps", "25",
        "--speedup", "9000",
        *images
    ]
    with pytest.raises(SystemExit) as exc:
        video_compile_console(cl)
    assert exc.value.code == 0
    assert frames(fn) == pytest.approx(72 * 10, rel=0.05)
    assert fps(fn) == pytest.approx(25)
    print(os.getcwd())
    print(f"frames({fn}) = {frames(fn)}")
    print(f"fps({fn}) = {fps(fn)}")

    # @25fps the impliciti sp[eedup, as used above is 90000
    # test x180000 (x2 faster)
    fn = "4-25fps-x180000.mp4"
    cl = [
        "--output", fn,
        "--log-level", "DEBUG",
        "--fps", "25",
        "--speedup", "180000",
        *images
    ]
    with pytest.raises(SystemExit) as exc:
        video_compile_console(cl)
    assert exc.value.code == 0
    assert frames(fn) == pytest.approx(72 / 2, abs=5)
    assert fps(fn) == pytest.approx(25)
    print(os.getcwd())
    print(f"frames({fn}) = {frames(fn)}")
    print(f"fps({fn}) = {fps(fn)}")

    # @25fps the impliciti sp[eedup, as used above is 90000
    # use a tenth of that, but half the fps
    #
    fn = "5-x10000.mp4"
    cl = [
        "--output", fn,
        "--log-level", "DEBUG",
        "--speedup", "10000",
        "--fps", "12",
        *images
    ]
    with pytest.raises(SystemExit) as exc:
        video_compile_console(cl)
    assert exc.value.code == 0
    print(os.getcwd())
    print(f"frames({fn}) = {frames(fn)}")
    print(f"fps({fn}) = {fps(fn)}")
    assert frames(fn) == pytest.approx(72 * 9 / 2, rel=20)
    assert fps(fn) == pytest.approx(12)


def test_console_concat(setup_module):
    # move them here to check visually
    for f in Path("/tmp/tmv/").rglob("concat*"):
        os.remove(f)
    fn = "concat-90d.mp4"
    cl = [
        "--output", fn,
        "--log-level", "DEBUG",
        str(TEST_DATA / "90days1h/*.jpg")
    ]
    with pytest.raises(SystemExit) as exc:
        video_compile_console(cl)
    assert exc.value.code == 0
    assert frames(fn) == 896
    assert fps(fn) == 25

    fn = "concat-cross.mp4"
    cl = [
        "--output", fn,
        "--log-level", "DEBUG",
        CAL_CROSS_IMAGES]
    with pytest.raises(SystemExit) as exc:
        video_compile_console(cl)
    assert exc.value.code == 0
    assert frames(fn) == 8761
    assert fps(fn) == 25
    copy_tree(".", "/tmp/tmv")


def test_console_diagonal(setup_module, caplog):
    """
    Use cal_cross to do numeric and visual tests
    """
    for f in Path("/tmp/tmv/").rglob("diagonal*"):
        os.remove(f)

    fn = "diagonal-cross-auto-fps25.mp4"
    cl = [
        "--output", fn,
        "--slice", "Diagonal",
           "--sliceage", "1 hour",
        "--log-level", "DEBUG",
        str(CAL_CROSS_IMAGES)
    ]
    with pytest.raises(SystemExit) as exc:
        video_compile_console(cl)
    assert exc.value.code == 0
    assert frames(fn) == pytest.approx(365, abs=1)  # one a day
    assert fps(fn) == 25

    fn = "diagonal-90days.mp4"

    cl = [
        "--output", fn,
        "--slice", "Diagonal",
        "--speedup", "1000000",
        "--end", "2000-04-01T00-00-00",
        "--log-level", "DEBUG",
        CAL_CROSS_IMAGES
    ]
    with pytest.raises(SystemExit) as exc:
        video_compile_console(cl)
    assert exc.value.code == 0
    vi = VideoInfo(fn)
    assert vi.real_duration.total_seconds() == pytest.approx(
        timedelta(days=90).total_seconds(), abs=3600*10)
    assert vi.real_start == dt(2000, 1, 1, 0, 0, 0)
    assert vi.duration.total_seconds() == pytest.approx(
        timedelta(days=90).total_seconds()/1000000, abs=1)
    assert vi.fps == 25

    fn = "diagonal-cross-1h.mp4"
    cl = [
        "--output", fn,
        "--slice", "Diagonal",
        "--sliceage", "1 hour",
        "--log-level", "DEBUG",
        str(CAL_CROSS_IMAGES)
    ]
    with pytest.raises(SystemExit) as exc:
        video_compile_console(cl)
    assert exc.value.code == 0
    assert frames(fn) == pytest.approx(365, abs=1)  # one a day
    assert fps(fn) == 25

    fn = "diagonal-cross-1h-limited.mp4"
    cl = [
        "--output", fn,
        "--slice", "Diagonal",
        "--sliceage", "1 hour",
        "--start-time", "06:00",
        "--end-time", "18:00",
        "--log-level", "DEBUG",
        str(CAL_CROSS_IMAGES)
    ]
    with pytest.raises(SystemExit) as exc:
        video_compile_console(cl)
    assert exc.value.code == 0
    # still one a day, just tighter band
    assert frames(fn) == pytest.approx(365, abs=1)
    assert fps(fn) == 25

    caplog.clear()
    fn = "diagonal-cross-auto.mp4"
    cl = [
        "--output", fn,
        "--slice", "Diagonal",
        "--log-level", "DEBUG",
        "--fps", "5",
        str(CAL_CROSS_IMAGES)
    ]
    with pytest.raises(SystemExit) as exc:
        video_compile_console(cl)
    assert exc.value.code == 0
    assert fps(fn) == 5

    copy_tree(".", "/tmp/tmv")


def test_console_hour(setup_module):
    for f in Path("/tmp/tmv/").rglob("hour*"):
        os.remove(f)

    fn = "hour-90days.mp4"
    cl = [
        "--output", fn,
        "--slice", "Concat",
        "--start-time", "11:00",
        "--end-time", "13:00",
        "--log-level", "DEBUG",
        CAL_CROSS_IMAGES
    ]
    with pytest.raises(SystemExit) as exc:
        video_compile_console(cl)
    assert exc.value.code == 0
   # assert frames(fn) == 8761
    assert fps(fn) == 25

    fn = "hour-cross.mp4"
    cl = [
        "--output", fn,
        "--slice", "Concat",
        "--start-time", "11:00",
        "--end-time", "13:00",
        "--log-level", "DEBUG",
        str(TEST_DATA / "90days1h/*.jpg")
    ]
    with pytest.raises(SystemExit) as exc:
        video_compile_console(cl)
    assert exc.value.code == 0
    #assert frames(fn) == 896
    assert fps(fn) == 25

    copy_tree(".", "/tmp/tmv")


def test_metadata(setup_module):
    cl = [
        "--output", "metadata.mp4",
        "--log-level", "DEBUG",
        str(TEST_DATA / "3days1h/*.jpg")
    ]
    with pytest.raises(SystemExit) as exc:
        video_compile_console(cl)
    assert exc.value.code == 0


def no_test_console_autoname(setup_module, capsys):
    cl = [
        "--log-level", "DEBUG",
        "--filenames",
        str(TEST_DATA / "90days1h/*.jpg")
    ]

    fn = "2020-02-21T06_to_2020-05-16T17.mp4"

    with pytest.raises(SystemExit) as exc:
        video_compile_console(cl)
    l = capsys.readouterr()
    assert l.out.strip() == '2020-02-21T06_to_2020-05-16T17.mp4'
    assert exc.value.code == 0
    assert frames(fn) == 896
    assert fps(fn) == 25
