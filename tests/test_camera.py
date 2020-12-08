# pytest tricks stuff pylint
# pylint: disable=import-error, protected-access, unused-argument, redefined-outer-name. unused-argument, global-statement
import logging
import os.path
import os
import re
import datetime
from datetime import datetime as dt, timedelta
from pathlib import Path
from copy import deepcopy
from tempfile import mkdtemp
from io import BytesIO
import time
from glob import glob
from dateutil.parser import parse
from PIL import Image
import pytest
from freezegun import freeze_time
import dateutil

import tmv.util
from tmv.util import today_at, tomorrow_at
from tmv.camera import ActiveTimes, Camera, CameraInactiveAction, FakePiCamera, LightLevel, Timed, calc_pixel_average, camera_console
import tmv
from tmv.exceptions import PowerOff
from tmv.buttons import ON, AUTO

TEST_DATA = Path(__file__).parent / "testdata"
FDT = None
LOGGER = logging.getLogger("tmv.camera")

cwd_buttons = """
    [camera.mode_button]
        file = './camera-mode'
    [camera.speed_button]
        file = './camera-speed'
"""

@pytest.fixture()
def setup_test():
    os.chdir(mkdtemp())
    logging.basicConfig(format='%(levelname)s:%(message)s')
    LOGGER.setLevel(logging.DEBUG)
    try:
        Path("camera.toml").unlink()
    except FileNotFoundError:
        pass

def test_latest_image(setup_test):
    cf = """
    [camera]
    file_root = "."
    latest_image = "moose.jpg"
    """
    c = Camera(fake=True)
    c.configs(cf)
    cwd = Path(os.getcwd())

    assert cwd / "moose.jpg" == c.latest_image




def test_write_config(setup_test):
    with pytest.raises(SystemExit) as exc:
        camera_console(["--runs", "1","-c","camera.toml"])
        assert exc.value.code == 0
        assert Path("camera.toml").is_file()


def sleepless(s):
    """ instead of really sleeping, just move frozen time forward """
    # pytest or something used 0.01s sleeps during the test: ignore these
    # or our times will get stuffed
    if s > 0.1:
        FDT.tick(timedelta(seconds=s))
        # for _ in range(int(s * 10)):
        #    fdt_global.tick(timedelta(milliseconds=100))


def test_Timed():
    """
    00    04    08    12    16    20    24
          on                off
        on(01:00) = false
        on(08:00) = True
        on(20:00) = false[summary]
    """
    t = tmv.camera.Timed(on=datetime.time(4), off=datetime.time(16))
    with freeze_time(today_at(1)):
        assert t.active() is False
    with freeze_time(today_at(8)):
        assert t.active() is True
    with freeze_time(today_at(20)):
        assert t.active() is False
    with freeze_time(today_at(2)):
        assert t.next_active() == today_at(4)
    with freeze_time(today_at(5)):
        assert t.next_active() == today_at(5)
    with freeze_time(today_at(20)):
        assert t.next_active() == tomorrow_at(4)

    t = tmv.camera.Timed(on=datetime.time(16), off=datetime.time(4))
    with freeze_time(today_at(1)):
        assert t.active() is True
    with freeze_time(today_at(8)):
        assert t.active() is False
    with freeze_time(today_at(20)):
        assert t.active() is True


def test_Fixed():
    t = tmv.camera.Fixed(on=True, off=False)
    with freeze_time(today_at(1)):
        assert t.active() is True
    with freeze_time(today_at(8)):
        assert t.active() is True
    with freeze_time(today_at(2)):
        assert t.next_active() == today_at(2)

    t = tmv.camera.Fixed(on=False, off=True)
    with freeze_time(today_at(1)):
        assert t.active() is False
    with freeze_time(today_at(2)):
        assert t.active_in() > timedelta(days=1000)

    with pytest.raises(Exception):
        t = tmv.camera.Timed(on=True, off=True)


def test_next_mark():
    d1 = dateutil.parser.parse("2000-01-01T13:00:00")
    with freeze_time(d1) as fdt:
        instant = dt(2000, 1, 1, 0, 0, 42)
        expect = dt(2000, 1, 1, 0, 0, 42)
        expect = dt(2000, 1, 1, 0, 1, 00)
        fdt.move_to(instant)
        assert(tmv.util.next_mark(timedelta(minutes=1), instant)) == expect
        instant = dt(2000, 1, 1, 10, 0, 42)
        expect = dt(2000, 1, 1, 20, 0, 00)
        fdt.move_to(instant)
        assert(tmv.util.next_mark(timedelta(hours=10), instant)) == expect
        instant = dt(2000, 1, 1, 20, 0, 42)
        expect = dt(2000, 1, 2, 6, 0, 00)
        fdt.move_to(instant)
        assert(tmv.util.next_mark(timedelta(hours=10), instant)) == expect
        instant = dt(2000, 1, 1, 20, 0, 42)
        expect = dt(2000, 1, 1, 20, 0, 42)
        fdt.move_to(instant)
        assert(tmv.util.next_mark(timedelta(seconds=2), instant)) == expect
        instant = dt(2000, 1, 1, 20, 0, 41)
        expect = dt(2000, 1, 1, 20, 0, 41)
        fdt.move_to(instant)
        assert(tmv.util.next_mark(timedelta(seconds=1), instant)) == expect

        instant = dt(2000, 1, 1, 20, 0, 41, 500000)
        expect = dt(2000, 1, 1, 20, 0, 42)
        fdt.move_to(instant)
        assert(tmv.util.next_mark(timedelta(seconds=1), instant)) == expect
        instant = dt(2000, 1, 1, 20, 0, 41, 1)
        expect = dt(2000, 1, 1, 20, 0, 42)
        fdt.move_to(instant)
        assert(tmv.util.next_mark(timedelta(seconds=1), instant)) == expect
        instant = dt(2000, 1, 1, 20, 0, 42, 1)
        expect = dt(2000, 1, 1, 20, 0, 43)
        fdt.move_to(instant)
        assert(tmv.util.next_mark(timedelta(seconds=1), instant)) == expect
        instant = dt(2000, 1, 1, 20, 0, 42, 1)
        expect = dt(2000, 1, 1, 20, 0, 50)
        fdt.move_to(instant)
        assert(tmv.util.next_mark(timedelta(seconds=10), instant)) == expect


def test_young_coll():
    d1 = dateutil.parser.parse("2000-01-01T13:00:00")
    with freeze_time(d1) as frozen_datetime:
        yc = tmv.camera.YoungColl()
        yc.append(tmv.camera.LightLevelReading(
            dt(2000, 1, 1, 12, 0, 0), 0, LightLevel.DIM))
        yc.append(tmv.camera.LightLevelReading(
            dt(2000, 1, 1, 12, 30, 0), 0, LightLevel.DIM))
        yc.append(tmv.camera.LightLevelReading(
            dt(2000, 1, 1, 13, 1, 0), 0, LightLevel.DIM))
        yc.append(tmv.camera.LightLevelReading(
            dt(2000, 1, 1, 13, 30, 0), 0, LightLevel.DIM))

        yc.trim_old_items()
        assert len(yc) == 4

        frozen_datetime.move_to(dateutil.parser.parse("2000-01-01T14:00:00"))
        yc.trim_old_items()
        assert len(yc) == 2

        frozen_datetime.move_to(dateutil.parser.parse("2000-01-01T15:00:00"))
        yc.trim_old_items()
        assert len(yc) == 0


def test_image_stats():
    #                           pixel_avg   looks
    # 2020-04-05T14-31-20.jpg   .29         light   0
    # 2020-04-05T15-24-20.jpg   .13         light   1
    # 2020-04-05T16-24-20.jpg   .08         dim     2
    # 2020-04-05T17-24-20.jpg   .04         dim     3
    # 2020-04-05T18-24-20.jpg   .01         dim     4
    # thresholds:   light > 0.10
    #               dark  < 0.01

    with freeze_time(dateutil.parser.parse("2020-04-05T20:00:00")) as fdt:
        image_files = []
        rex = re.compile("^2020-04-05T.*")

        for r, ds, fs in os.walk(TEST_DATA/"camera_images"):
            print(ds)
            image_files = [os.path.join(r, f)
                           for f in fs if rex.match(f) is not None]
            break  # no deeper
        assert len(image_files) == 5
        cam = tmv.camera.Camera(fake=True)

        # usually max_age is 1 hour: use long to make testing easier
        cam.light_sensor.max_age = timedelta(days=1)
        for f in sorted(image_files):
            cam.light_sensor.add_reading(
                tmv.util.str2dt(f), calc_pixel_average(f))
        # pylint: disable=protected-access,pointless-statement
        assert cam.light_sensor.level == tmv.camera.LightLevel.LIGHT
        assert len(cam.light_sensor._levels) == 5
        cam.light_sensor.max_age = timedelta(hours=4)
        cam.light_sensor.level
        assert len(cam.light_sensor._levels) == 3
        fdt.move_to(dateutil.parser.parse("2020-04-07T20:00:00"))
        cam.light_sensor.level
        assert len(cam.light_sensor._levels) == 0


def test_image_stats_2():
    """ Test max_age =0 boundary case"""
    #                           pixel_avg   looks
    # 2020-04-05T14-31-20.jpg   .29         light   0
    # 2020-04-05T15-24-20.jpg   .13         light   1
    # 2020-04-05T16-24-20.jpg   .08         dim     2
    # 2020-04-05T17-24-20.jpg   .04         dim     3
    # 2020-04-05T18-24-20.jpg   .01         dim     4
    # thresholds:   light > 0.10
    #               dark  < 0.01

    with freeze_time(dateutil.parser.parse("2020-04-05T20:00:00")):
        image_files = []
        rex = re.compile("^2020-04-05T.*")

        for r, ds, fs in os.walk(TEST_DATA / "camera_images"):
            print(ds)
            image_files = [os.path.join(r, f)
                           for f in fs if rex.match(f) is not None]
            break  # no deeper
        assert len(image_files) == 5

        cam = tmv.camera.Camera(fake=True)
        cam.light_sensor.max_age = timedelta(seconds=0)
        cam.light_sensor.dark = 0.0  # make sure they are DIM
        assert cam.light_sensor.level == tmv.camera.LightLevel.LIGHT
        for f in sorted(image_files):
            cam.light_sensor.add_reading(
                tmv.util.str2dt(f), calc_pixel_average(f))
            print("length:{}".format(len(cam.light_sensor._levels)))

        assert cam.light_sensor.level == tmv.camera.LightLevel.DIM
        assert len(cam.light_sensor._levels) == 0


def test_LightLevel():
    light = LightLevel.LIGHT
    dim = LightLevel.DIM
    dark = LightLevel.DARK
    light2 = LightLevel.LIGHT
    assert light == light2
    assert light > dim
    assert dim > dark
    assert dark < light
    assert dark < dim
    assert not light > light
    assert not light < dark


def test_Sensor_lookups():
    c = tmv.camera.Camera(fake=True)
    c.active_timer = tmv.camera.ActiveTimes.factory(
        on='dim', off='dark', camera=c)
    c.light_sensor._current_level = LightLevel.LIGHT
    assert c.active_timer.camera_active()

    c = tmv.camera.Camera(fake=True)
    ss = tmv.camera.ActiveTimes.factory(on='dim', off='dark', camera=c)
    c.light_sensor._current_level = LightLevel.DARK
    # Active, as sensor will operate
    assert ss.active() is True
    # But could power off if camera not required (it's DARK)
    assert timedelta(minutes=59) <= (
        ss.waketime() - dt.now()) <= timedelta(minutes=61)
    c.light_sensor._current_level = LightLevel.DIM
    # Still active
    assert ss.active()
    # But can't power off for long (camera is active)
    assert ss.waketime() <= dt.now()
    c.light_sensor._current_level = LightLevel.LIGHT
    assert ss.waketime() <= dt.now()
    c.light_sensor._current_level = LightLevel.DIM
    assert ss.waketime() <= dt.now()
    c.light_sensor._current_level = LightLevel.DARK
    # active, but only the sensor
    assert ss.active()
    assert timedelta(minutes=59) <= (
        ss.waketime() - dt.now()) <= timedelta(minutes=61)
    #
    c.light_sensor._current_level = LightLevel.LIGHT
    # ON when DIM, OFF when DARK, should be ON when light
    assert ss.active()


def test_camera_console():
    # with pytest.raises(Exception) as e: don't work
    try:
        tmv.camera.camera_console(['-h'])
    except SystemExit as e:
        assert e.code == 0

    try:
        tmv.camera.camera_console(['-bull'])
    except SystemExit as e:
        assert e.code == 2


def test_location():
    cf = """
    [camera]
    on = 'dawn'
    off = 'dusk'
    """
    # no location: fail
    c = Camera(fake=True)
    with pytest.raises(tmv.camera.ConfigError):
        c.configs(cf)

    cf = """
    
    
    [camera]
    city = 'Brisbane'
    on = 'dawn'
    off = 'dusk'
    """
    #  location: ok
    c.configs(cf)

    cf = """
    
    [camera]
    city = 'auto'
    on = 'dawn'
    off = 'dusk'
    """
    # no location: fail

    with pytest.raises(NotImplementedError):
        c.configs(cf)


def test_image_verify(setup_test, caplog):
    c = Camera(fake=True)
    stream = BytesIO()
    # "Rewind" the stream to the beginning so we can read its content
    stream.seek(0)
    f = FakePiCamera()
    f.capture(stream)
    stream.seek(0)
    image = Image.open(stream)
    image.save("should-not-be-required.jpg")
    fn = Path("test_image_verify.jpg")
    c.save_image(image, str(fn))
    assert Path(fn).is_file()

    c = Camera(fake=True)
    image = Image.Image()
    fn = Path("test_image_dud.jpg")
    caplog.clear()
    c.save_image(image, str(fn))
    assert not Path(fn).is_file()
    assert "Image has zero width or height" in caplog.text


def test_fake(monkeypatch, setup_test):
    cf = """
       [camera.mode_button]
            file = './camera-mode'
        [camera.speed_button]
            file = './camera-speed'
        """
    local_config = Path("./camera.toml")
    local_config.write_text(cf)

    with freeze_time(parse("2000-01-01 12:00:00")) as fdt:
        global FDT
        FDT = fdt
        monkeypatch.setattr(time, 'sleep', sleepless)
        c = Camera(fake=True)
        c.config(str(local_config))
        c.file_root = "./test_fake/"
        c.file_by_date = False
        c.interval = timedelta(minutes=10)
         

        run_until(c, fdt, today_at(13))
        assert len(c.recent_images) == 6 + 1  # fencepost
        images = glob(os.path.join(c.file_root, "2000-01-01T*"))
        assert len(images) == 6 + 1  # fencepost   

        # Cannot test switch OFF as main loop waits for "not OFF"

        # run 13:00 - 14:00 with switch ON
        assert c.mode_button.value == AUTO
        run_until(c, fdt, today_at(14))
        assert c.active_timer.active() #  active 
        images = glob(os.path.join(c.file_root, "2000-01-01T*"))
        assert len(images) == 6 + 1 + 6  # one hour more of 6 photos per hour

        # run 14:00 - 15:00 with switch ON
        c.active_timer = Timed(datetime.time(6,0,0),datetime.time(7,0,0))
        c.mode_button.value = ON
        run_until(c, fdt, today_at(15))
        assert not c.active_timer.active() # not active - but overridden by switch
        images = glob(os.path.join(c.file_root, "2000-01-01T*"))
        assert len(images) == 6 + 1 + 6 + 6 # one hour more of 6 photos per hour
        assert Path("./test_fake/latest-image.jpg").is_file()


def test_calc_exposure_speed(monkeypatch, setup_test):
    cf = """
       [camera.mode_button]
            file = './camera-mode'
        [camera.speed_button]
            file = './camera-speed'
        """
    local_config = Path("./camera.toml")
    local_config.write_text(cf)

    with freeze_time(parse("2000-01-01 00:00:00")) as fdt:
        global FDT
        FDT = fdt
        monkeypatch.setattr(time, 'sleep', sleepless)
        c = Camera(fake=True)
        c.configs(cf)
        run_until(c, fdt, today_at(23, 59, 59))
        # how to check?


def check_test_fake2(monkeypatch, setup_test):
    s = 3
    c = Camera(fake=True)
    c.file_root = "./test_fake2/"
    c.file_by_date = False
    c.interval = timedelta(seconds=1)
    c.active_timer = ActiveTimes.factory(dt.now().astimezone().time(
    ), (dt.now() + timedelta(seconds=s)).astimezone().time(), c)
    c.camera_inactive_action = CameraInactiveAction.EXCEPTION
    with pytest.raises(PowerOff):
        c.run()
    assert len(c.recent_images) == s + 1  # fencepost
    images = glob(os.path.join(c.file_root, "*.jpg"))
    assert len(images) == s + 1  # fencepost


def test_config(monkeypatch, setup_test):
    with freeze_time(parse("2000-01-01 00:00:00")) as fdt:
        global FDT
        FDT = fdt
        c1 = Camera(fake=True)
        c1.file_root = "./test_config/"
        cf = """
        [location]
            city = "Brisbane"
        [camera]
            off = 07:00:00
            on = 18:00:00
        [camera.mode_button]
            file = './camera-mode'
        [camera.speed_button]
            file = './camera-speed'

        [camera.picam.LIGHT]
            id = "Custom day config at 800"
            iso = 800
            exposure_mode = "auto"
            resolution = "800x600"

        [camera.picam.DIM]
            id = "CUSTOM-DIM"
            framerate = 1
            iso = 0
            exposure_mode = "night"
            resolution = "800x600"

        [camera.picam.DARK]
            id = "CUSTOM-NIGHTY"
            framerate = 1
            iso = 1600
            shutter_speed = 1000000
            exposure_mode = "verylong"
            resolution = "800x600"
        """
        c1.configs(cf)
        # default
        assert c1.picam[LightLevel.LIGHT.name]['exposure_mode'] == 'auto'
        assert c1.picam[LightLevel.LIGHT.name]['resolution'] == '800x600'
        # new one
        assert c1.picam[LightLevel.LIGHT.name]['iso'] == 800
        c1._camera = FakePiCamera()
        # fake sleeping
        monkeypatch.setattr(time, 'sleep', sleepless)
        c1.run(3)
        # should have clicked over to DARK. Configured a special iso for DARK in toml.
        assert c1.picam[c1.light_sensor.level.name]['iso'] == 1600
        c1.run(1)


def test_low_light_sense(monkeypatch, setup_test):
    cf = """
        [camera.mode_button]
            file = './camera-mode'
        [camera.speed_button]
            file = './camera-speed'
    """
    with freeze_time(parse("2000-01-01 00:00:00")) as fdt:
        global FDT
        FDT = fdt
        monkeypatch.setattr(time, 'sleep', sleepless)
        c = Camera(fake=True)
        c.configs(cf)
        c.file_by_date = False
        c.file_root = "./test_low_light_sense/"
        c.interval = timedelta(hours=1)
        c.light_sensor.light = 0.6
        c.light_sensor.dark = 0.1
        c.light_sensor.freq = timedelta(minutes=10)
        c.light_sensor.max_age = timedelta(minutes=60)
        assert c.light_sensor.level == LightLevel.LIGHT  # starts LIGHT by default
        run_until(c, fdt, today_at(3))
        assert c.light_sensor.level == LightLevel.DARK
        run_until(c, fdt, today_at(10))
        assert c.light_sensor.level == LightLevel.DIM
        run_until(c, fdt, today_at(12))
        assert c.light_sensor.level == LightLevel.LIGHT
        run_until(c, fdt, today_at(16, 30))
        assert c.light_sensor.level == LightLevel.DIM
        run_until(c, fdt, today_at(23))
        assert c.light_sensor.level == LightLevel.DARK
        images = glob(os.path.join(c.file_root, "2000-01-01T*"))
        assert len(images) == 24


def test_low_light_sense2(monkeypatch, setup_test):
   
    with freeze_time(parse("2000-01-01 00:00:00")) as fdt:
        global FDT
        FDT = fdt
        monkeypatch.setattr(time, 'sleep', sleepless)
        c = Camera(fake=True)
        c.configs(cwd_buttons)
        c.file_root = "./test_low_light_sense2/"
        c.interval = timedelta(hours=1)
        c.light_sensor.light = 0.6
        c.light_sensor.dark = 0.1
        c.file_by_date = False
        c.light_sensor.freq = timedelta(minutes=5)
        c.light_sensor.max_age = timedelta(minutes=30)
        run_until(c, fdt, today_at(14, 30))
        assert c.light_sensor.level == LightLevel.LIGHT
        run_until(c, fdt, today_at(16))
        assert c.light_sensor.level == LightLevel.DIM
        run_until(c, fdt, today_at(23))
        assert c.light_sensor.level == LightLevel.DARK
        images = glob(os.path.join(c.file_root, "2000-01-01T*"))
        assert len(images) == 24


def test_Timed_capture(monkeypatch, setup_test):

    with freeze_time(parse("2000-01-01 06:00:00")) as fdt:
        global FDT
        FDT = fdt
        monkeypatch.setattr(time, 'sleep', sleepless)
        c = Camera(fake=True)
        c.configs(cwd_buttons)
        c.mode_button.button_path = Path("./camera-switch")
        c.file_by_date = False
        c._camera = FakePiCamera()
        c.file_root = "./test_Timed_capture/"
        c.interval = timedelta(minutes=60)
        c.active_timer = Timed(datetime.time(12), datetime.time(18))
        run_until(c, fdt, today_at(23))
        images = glob(os.path.join(c.file_root, "2000-01-01T*"))
        assert len(images) == 18 - 12 + 1  # +1 for a fencepost


def test_SunCalc(monkeypatch, setup_test):
    # dawn:   datetime.time(4, 28, 38, 892410)
    # sunrise:datetime.time(4, 55, 38, 480930)
    # noon:   datetime.time(11, 50, 59)
    # sunset  datetime.time(18, 46, 18, 926896)
    # dusk    datetime.time(19, 13, 17, 159158)

    with freeze_time(parse("2000-01-01 00:00:00")) as fdt:
        global FDT
        FDT = fdt
        monkeypatch.setattr(time, 'sleep', sleepless)
        c = Camera(fake=True)

        c.save_images = False
        c.configs("""        
        [camera]
        city = 'Brisbane'
        interval = 600
        on = 'dawn'
        off =  'sunset' # (2000, 1, 1, 18, 46, 18, 926896, tzinfo=tzlocal())
        camera_inactive_action = 'WAIT'
       
        [camera.mode_button]
            file = './camera-mode'
        [camera.speed_button]
            file = './camera-speed'

        """)
        c._camera = FakePiCamera()
        assert c.active_timer.active() is False
        run_until(c, fdt, today_at(4, 30))
        assert c.active_timer.active() is True
        run_until(c, fdt, today_at(12, 30))
        assert c.active_timer.active() is True
        run_until(c, fdt, today_at(18, 30))
        assert c.active_timer.active() is True
        run_until(c, fdt, today_at(18, 40))
        run_until(c, fdt, today_at(18, 50))
        assert c.active_timer.active() is False
        run_until(c, fdt, tomorrow_at(8))
        assert c.active_timer.active() is True


def test_Sensor(monkeypatch, setup_test):
    with freeze_time(parse("2000-01-01 00:00:00")) as fdt:
        global FDT
        FDT = fdt
        monkeypatch.setattr(time, 'sleep', sleepless)
        c = Camera(fake=True)
        c.save_images = True
        c.light_sensor.freq = timedelta(minutes=20)
        c.light_sensor.max_age = timedelta(hours=1)
        c.file_root = "./test_Sensor/"
        c.configs("""
        [location]
        city = "Brisbane"
        [camera]
        interval = 300
        # test ON at first light, then off when dark (i.e. all day)
        on = 'light'
        off =  'dim'
        camera_inactive_action = 'WAIT'
    
        [camera.mode_button]
            file = './camera-mode'
        [camera.speed_button]
            file = './camera-speed'
    
        """)
        c._camera = FakePiCamera()
        reset_camera = deepcopy(c)  # a copy of the camera after it starts
        run_until(c, fdt, tomorrow_at(12), reset_camera)
        run_until(c, fdt, today_at(18, 00), reset_camera)
        run_until(c, fdt, today_at(23, 59), reset_camera)
        run_until(c, fdt, tomorrow_at(9, 00), reset_camera)
        reset_camera.run(1)
        assert reset_camera.active_timer.light_sensor.level == LightLevel.LIGHT

def test_camera_inactive_action(monkeypatch, setup_test):
    with freeze_time(parse("2000-01-01 12:00:00")) as fdt:
        global FDT
        FDT = fdt
        monkeypatch.setattr(time, 'sleep', sleepless)
        c = Camera(fake=True)
        c.file_root = "./test_camera_inactive_action/"
        c.save_images = False
        c.configs("""
        [camera]
        interval = 900 # 15 minutes
        on = 09:00:00
        off = 13:00:00
        camera_inactive_action = 'EXCEPTION'       
        [camera.mode_button]
            file = './camera-mode'
        [camera.speed_button]
            file = './camera-speed'
        """)
        c._camera = FakePiCamera()
        with pytest.raises(PowerOff):
            run_until(c, fdt, today_at(18))
        c.configs("""
        [camera]
        on = 09:00:00
        off = 13:00:00
        camera_inactive_action = 'WAIT'
               
        [camera.mode_button]
            file = './camera-mode'
        [camera.speed_button]
            file = './camera-speed'
    
        """)
        run_until(c, fdt, tomorrow_at(18))  # no raise


def test_camera_inactive_action_2(monkeypatch, setup_test):
    with freeze_time(parse("2000-01-01 12:00:00")) as fdt:
        global FDT
        FDT = fdt
        monkeypatch.setattr(time, 'sleep', sleepless)
        c = Camera(fake=True)
        c.save_images = False
        c.configs("""
        [camera]
        interval = 900 # 15 minutes
        on = 'dim'
        off = 'dark'
        camera_inactive_action = 'EXCEPTION'
               
        [camera.mode_button]
            file = './camera-mode'
        [camera.speed_button]
            file = './camera-speed'
    
        """)
        c._camera = FakePiCamera()
        # with pytest.raises(PowerOff):
        run_until(c, fdt, today_at(14))
        assert c.light_sensor.level == LightLevel.LIGHT
        assert c.active_timer.active()
        assert c.active_timer.camera_active()


def run_times(camera, fdt, n):
    """ Run camera with one second between each loop.
        Otherwise, if time is frozen, it will never move the (time) mark """
    for _ in range(n):
        camera.run(1)
        fdt.tick(timedelta(seconds=1))


def run_until(camera, fdt, until, reset_camera=None):
    while dt.now() < until:
        try:
            camera.run(1)
        except PowerOff:
            if reset_camera:
                LOGGER.info("Reseting camera")  # , exc_info=e)
                camera = deepcopy(reset_camera)
                # fdt.tick(timedelta(hours=1))
            else:
                raise
        fdt.tick(timedelta(seconds=1))
