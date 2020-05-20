import shutil
from distutils.dir_util import copy_tree  # instead of sh(it)utils
import os
from tempfile import mkdtemp
from pathlib import Path
from inspect import getsourcefile
from multiprocessing import Process
from datetime import datetime as dt, timedelta
import logging
from time import sleep
from dateutil.parser import parse
from freezegun import freeze_time
import pytest

from tmv.videotools import VideoInfo, frames, fps
from tmv.videod import LOGGER, VideoMakerDaemon, videod_console, VideoMakerDaemonManager
from tmv.util import LOG_FORMAT_DETAILED, LOG_FORMAT


def datadir():
    mydir = Path(getsourcefile(lambda: 0)).absolute().parent
    return mydir / "testdata"


@pytest.fixture()
def setup_test():
    os.chdir(mkdtemp())
    copy_tree(datadir() / "single", ".")
    logging.basicConfig(format=LOG_FORMAT)
    LOGGER.setLevel(logging.DEBUG)
    LOGGER.info("Setting cwd to {}".format(os.getcwd()))


@pytest.fixture()
def setup_multi_test():
    os.chdir(mkdtemp())
    copy_tree(datadir() / "multi", ".")
    logging.basicConfig(format=LOG_FORMAT_DETAILED)
    LOGGER.setLevel(logging.DEBUG)


@pytest.fixture()
def daily_photos():
    os.chdir(mkdtemp())
    copy_tree(datadir() / "single" / "daily-photos", "daily-photos")
    logging.basicConfig(format=LOG_FORMAT)
    LOGGER.setLevel(logging.DEBUG)
    LOGGER.info("Setting cwd to {}".format(os.getcwd()))


def test_config(setup_test):
    vd = VideoMakerDaemon()
    c = """
    [daily-videos]
    #minterpolate = False
    #fps = 25
    #speedup = None

    [recap-videos]
    recaps = [
        { label = "Last 7 days", days = 7 , speedup=30},
        { label ="Last 30 days", days = 30 },
        { label = "From beginning", days = 0 }
    ]
    """
    vd.configs(c)
    assert len(vd.tasks) == 2


def test_daily(setup_test):
    vd = VideoMakerDaemon()
    c = """
    [daily-videos]
    """
    vd.configs(c)
    vd.raise_task_exceptions = True
    vd.run_tasks()
    # make 3 days' videos
    d1 = Path("daily-videos/2000-01-01.mp4")
    d2 = Path("daily-videos/2000-01-02.mp4")
    d3 = Path("daily-videos/2000-01-03.mp4")
    assert d1.is_file() and d2.is_file() and d3.is_file()
    # don't re-make
    d1_mtime = d1.stat().st_mtime
    vd.run_tasks()
    assert d1.stat().st_mtime == d1_mtime
    # even if image updated
    Path("daily-photos/2000-01-01T01-00-00.jpg").touch()
    vd.run_tasks()
    assert d1_mtime == d1.stat().st_mtime
    # but only on new image updated
    im = Path("daily-photos/2000-01-01/2000-01-01T01-00-00.jpg")
    im_new = Path("daily-photos/2000-01-01/2000-01-01T01-30-00.jpg")
    shutil.copy(str(im), str(im_new))
    vd.run_tasks()
    d1 = Path("daily-videos/2000-01-01.mp4")

    assert d1.stat().st_mtime > d1_mtime


def test_recap_videos(setup_test):
    # daily-videos are : 2019-10-22, 23, 24
    with freeze_time(parse("2019-10-24 23:00:00")):
        vd = VideoMakerDaemon()
        c = """
        #[daily-videos]
        #minterpolate = False
        #fps = 25
        #speedup = None

        [recap-videos]
        # any-name = { label = human readable, days = from now() to now() - X days, [ speedup = auto or X]}
        create = [
            { label = "Last 1 days", days = 1 , speedup=1 },
            { label ="Last 2 days", days = 2 },
            { label = "From beginning", days = 0 }
        ]
        #[diagonal-videos]
        """
        vd.configs(c)
        vd.raise_task_exceptions = True
        vd.run_tasks()
        v1 = Path("recap-videos/last-1-days.mp4")
        v2 = Path("recap-videos/last-2-days.mp4")
        v3 = Path("recap-videos/from-beginning.mp4")
        v1_mtime = v1.stat().st_mtime
        assert v1.is_file() and v2.is_file() and v3.is_file()
        vd.run_tasks()
        # shouldn't overwrite...
        assert v1.stat().st_mtime == v1_mtime
        Path("daily-videos/dummy").touch()
        # ... unless daily-videos folder mtime is updated
        vd.run_tasks()
        assert v1.stat().st_mtime > v1_mtime


def test_preview_videos(setup_test):
    c = """
        [preview-videos]
        filters.scale="128:-1"
        filters.fps = "fps=5"
        filters.setpts = "0.25*PTS"
        """
    vd = VideoMakerDaemon()
    vd.configs(c)
    vd.run_tasks()
    assert Path("daily-videos/previews/2019-10-22.mp4").is_file
    frames_o = frames("daily-videos/2019-10-22.mp4")
    fps_o = fps("daily-videos/2019-10-22.mp4")
    frames_p = frames("daily-videos/previews/2019-10-22.mp4")
    fps_p = fps("daily-videos/previews/2019-10-22.mp4")
    assert fps_o == 25
    assert fps_p == 5
    assert frames_p == pytest.approx((fps_p / fps_o) * 0.25 * frames_o, abs=5)
    #assert False, "Output at " + os.getcwd()
    # run again - should NOT make previews of previews!
    run1_files = list(Path(".").glob("**/*.mp4"))
    vd.run_tasks()
    run2_files = list(Path(".").glob("**/*.mp4"))
    assert run1_files == run2_files, f"{run1_files} != {run2_files}"


def test_console(daily_photos):
    # Default config should:
    # Start with images
    # Make daily videos
    # Make recaps
    # Make previews
    # Check it!
    # daily-videos are : 2019-10-22, 23, 24
    with freeze_time(parse("2000-01-04 00:00:00")):
        try:
            Path("videod.toml").unlink()
        except FileNotFoundError:
            pass
        with pytest.raises(SystemExit) as exc:
            videod_console(["--runs", "3", "--log-level", "DEBUG"])

def test_recap_speeds(setup_test):
    # 2019-10-22.mp4  2019-10-23.mp4  2019-10-24.mp4  previews
    with freeze_time(parse("2019-10-24 23:00:00")):
        print(f"getcwd={os.getcwd()}")
        vd = VideoMakerDaemon()
        c = """
        [recap-videos]
        create = [
            { label = "Last 1 days", days = 1 , speed = 1},
            { label = "Last 3 days", days = 3, speed = 3 },
        ]
        """
        
        vd.configs(c)
        logging.getLogger("tmv.video").setLevel(logging.DEBUG)
        vd.run_tasks()

def test_recap_after_finish(daily_photos):
    # daily-videos are : 2019-10-22, 23, 24
    # We set the time to 2020
    # And expect 3 recaps - they should take the end date as
    # the last date supplied
    with freeze_time(parse("2010-01-04 00:00:00")):
        try:
            Path("videod.toml").unlink()
        except:
            pass
        with pytest.raises(SystemExit) as exc:
            videod_console(["--runs", "1", "--log-level", "DEBUG"])

        assert exc.value.code == 0
        assert Path("videod.toml").is_file()
        assert Path("daily-videos/2000-01-01.mp4").is_file()
        assert Path("daily-videos/2000-01-02.mp4").is_file()
        assert Path("daily-videos/2000-01-03.mp4").is_file()
        assert len(list(Path("daily-videos/previews/").glob("*.mp4"))) == 3
        assert Path("daily-videos/previews/2000-01-03.mp4").stat().st_size < .5 * \
            Path("daily-videos/2000-01-03.mp4").stat().st_size
        # 3 recaps, 3 preview
        assert len(list(Path("recap-videos").glob("*.mp4"))) == 3
        assert len(list(Path("recap-videos/previews").glob("*.mp4"))) == 3


def test_sched(setup_test):
    s = dt.now()
    c = """
        [recap-videos]
        # null
        """
    vd = VideoMakerDaemon()
    vd.interval = timedelta(seconds=1)
    vd.configs(c)
    for _ in range(0, 4):
        vd.run_tasks()
    assert pytest.approx((dt.now()-s).total_seconds(), 4, abs=2)


def test_multi(setup_multi_test):
    c = """
        locations = ['cam1', 'cam2', 'cam3']
        file_root = "."
        # use tasks defaults       
        [daily-videos]    
        [preview-videos]
        [recap-videos]
    """
    # write config
    with open("videod.toml", "w") as f:
        print(c, file=f)

    VideoMakerDaemonManager.DEFAULT_INTERVAL = timedelta(seconds=1)
    # run (3 process+1 master)
    with pytest.raises(SystemExit) as exc:
        videod_console(["--runs", "3", "--log-level", "DEBUG"])

    assert exc.value.code == 0
    assert Path("cam1/daily-videos/2000-01-01.mp4").is_file()
    assert Path("cam2/daily-videos/2000-01-02.mp4").is_file()
    assert Path("cam3/daily-videos/2000-01-03.mp4").is_file()
    assert len(list(Path("cam3/daily-videos/previews/").glob("*.mp4"))) == 3
    assert Path("cam3/daily-videos/previews/2000-01-03.mp4").stat().st_size < .5 * \
        Path("cam3/daily-videos/2000-01-03.mp4").stat().st_size
    # 3 recaps, 3 preview
    assert len(list(Path("cam2/recap-videos").glob("*.mp4"))) == 3
    assert len(list(Path("cam2/recap-videos/previews").glob("*.mp4"))) == 3


def test_multi_stop(setup_multi_test):
    # Create VideoDaemons
    # Run them
    # Simulate SIGTERMING them
    c = """
    locations = ['cam1', 'cam2', 'cam3']
    file_root = "."

    # use tasks defaults       
    [daily-videos]    
    [preview-videos]
    [recap-videos]
    """

    try:
        from multiprocessing_logging import install_mp_handler
        install_mp_handler()
    except (NameError, ImportError) as exc:
        LOGGER.debug(f"No multi-process logging available: {exc}")
    # write config
    with open("videod.toml", "w") as f:
        print(c, file=f)

    VideoMakerDaemonManager.DEFAULT_INTERVAL = timedelta(seconds=1)
    console = Process(target=videod_console, args=(
        ["--runs", "2", "--log-level", "DEBUG"],))
    console.start()
    sleep(10)
    # send a signal to the daemon - should quit nicely and leave no zombies
    console.terminate()
    console.join()
    assert Path("cam1/daily-videos/2000-01-01.mp4").is_file()
    assert Path("cam2/daily-videos/2000-01-02.mp4").is_file()
    assert Path("cam3/daily-videos/2000-01-03.mp4").is_file()
    assert len(list(Path("cam3/daily-videos/previews/").glob("*.mp4"))) == 3
    assert Path("cam3/daily-videos/previews/2000-01-03.mp4").stat().st_size < .5 * \
        Path("cam3/daily-videos/2000-01-03.mp4").stat().st_size
    # 3 recaps, 3 preview
    assert len(list(Path("cam2/recap-videos").glob("*.mp4"))) == 3
    assert len(list(Path("cam2/recap-videos/previews").glob("*.mp4"))) == 3

def test_errors(setup_test, caplog):
    logging.getLogger("tmv.videod").setLevel(logging.DEBUG)
    vd = VideoMakerDaemon()
    c = """
        [daily-videos]
        """
    vd.configs(c)
    
    dud_file = Path("daily-photos/wrong-0place-not-an-image.moose")
    dud_image = Path("daily-photos/2000-01-01/no-date.jpg")
    null_image = Path("daily-photos/2000-01-01/2000-01-01T00-00-01.jpg")
    null_image.touch()
    dud_file.touch()
    dud_image.touch()
    vd.run_tasks()
    assert 'Ignoring invalid image' in caplog.text
    d1 = Path("daily-videos/2000-01-01.mp4")
    d2 = Path("daily-videos/2000-01-02.mp4")
    d3 = Path("daily-videos/2000-01-03.mp4")
    assert d1.is_file() and d2.is_file() and d3.is_file()
    d2.unlink()

    caplog.clear()
    vd = VideoMakerDaemon()
    c = """
        [recap-videos]
        """
    vd.configs(c)
    caplog.clear()
    null_video = Path("daily-videos/2000-01-04.mp4")
    null_video.touch()
    vd.run_tasks()
    assert 'Ignoring 1 invalid video' in caplog.text
    v1 = Path("recap-videos/last-7-days.mp4")
    v2 = Path("recap-videos/last-30-days.mp4")
    v3 = Path("recap-videos/complete.mp4")
        
    assert v1.is_file() and v2.is_file() and v3.is_file()
