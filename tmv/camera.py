# pylint: disable=protected-access, line-too-long, logging-fstring-interpolation, dangerous-default-value, logging-not-lazy, too-many-lines

from signal import signal, SIGINT, SIGTERM
import argparse

from io import BytesIO
from sys import maxsize, argv
from enum import Enum
import datetime  # for datetime.time
from datetime import datetime as dt, timedelta
import sys
import threading             # dt = class, time=class
# to enable monkeypatching, don't import "from x.y", but instead "import y" and use "x.y"
import time  # for time.sleep
import os
from os.path import join
import logging

from collections.abc import MutableSequence
from pprint import pformat
from pathlib import Path
from math import exp, sqrt, tau
import traceback
import debugpy

from transitions import Machine
import toml
from PIL import Image, ImageFont, ImageDraw, ImageStat
import astral
from astral.geocoder import database, lookup  # Get co-ordinates from city name
from astral.sun import sun
from tmv.util import unlink_safe
from tmv.circstates import StatesCircle

from tmv.streamer import StreamingHandler, StreamingOutput, TMVStreamingServer
from tmv.util import penultimate_unique, next_mark, LOG_FORMAT, LOG_LEVELS
from tmv.util import Tomlable, setattrs_from_dict, ensure_config_exists, interval_speeded
from tmv.exceptions import ConfigError, PiJuiceError, SignalException, PowerOff
from tmv.buttons import ON, OFF, AUTO, VIDEO, StatefulButton
from tmv.config import *  # pylint: disable=wildcard-import, unused-wildcard-import

LOGGER = logging.getLogger("tmv.camera")

try:
    from picamera import PiCamera  # pylint: disable=unused-import
except ImportError as e:
    LOGGER.warning(e)

class FakePiCamera():
    """ Returns synthetic images via software and time-of-day"""

    def __init__(self, resolution='640x480', framerate=20):
        self.lum = 0
        self.framerate = 1
        self.exposure_speed = 0.1
        self.width = 400
        self.height = 300
        self.activity = StatesCircle(ACTIVITY_FILE, ACTIVITY_STATE, fallback=OFF)
        self.output = None
        
    def __enter__(self):
        return self

    def __exit__(self, _type, value, traceback):
        pass

    def close(self):
        pass

    # pylint: disable=redefined-builtin
    # must copy definition of picamera with 'format' keyword
    def capture(self, stream=None, format="jpeg", filename=None, quality=80):
        """
        norm distro around noon
        (5, 0.001) , (10, 0.48),  (12, 0.79)
        """
        self.activity.value = ON
        # time.sleep(1)
        h = dt.now().hour + dt.now().minute / 60 + dt.now().second / 3600
        _sigma = 2
        _mu = 12
        # Probability density function.  P(x <= X < x+dx) / dx
        variance = _sigma ** 2.0
        pdf = exp((h - _mu)**2.0 / (-2.0 * variance)) / sqrt(tau * variance)
        self.lum = int(255.0 * pdf * 5)

        im = Image.new("RGB", (self.width, self.height), (self.lum, self.lum, self.lum))
        if filename is None:
            im.save(stream, format, quality=quality)
            self.activity.value = OFF
            return im
        else:
            im.save(filename)
            self.activity.value = OFF
            return im

    def start_recording(self, output, format):
        self.output = output

    def stop_recording(self):
        self.output = None
    
        



class LightLevel(Enum):
    """ Measured by a sensor, or an image. Unit ~ = lux or pixel_average"""
    LIGHT = 'LIGHT'
    DIM = 'DIM'
    DARK = 'DARK'

    def __str__(self):
        return str(self.name)

    def __lt__(self, other):
        if self == LightLevel.LIGHT:
            return False
        elif self == LightLevel.DIM:
            return other == LightLevel.DARK
        elif self == LightLevel.DARK:
            return other != LightLevel.DARK
        else:
            raise RuntimeError()

    def __gt__(self, other):
        if other == LightLevel.LIGHT:
            return False
        elif other == LightLevel.DIM:
            return self == LightLevel.LIGHT
        elif other == LightLevel.DARK:
            return self != LightLevel.DARK
        else:
            raise RuntimeError()


class CameraInactiveAction(Enum):
    """ What to do if the camera is inactive? """
    WAIT = 1        # Remain on, and just wait until next active time
    POWER_OFF = 2    # Power off (use PiJuice, etc)
    EXCEPTION = 3   # Raise a PowerOff exception
    EXIT = 4        # Exit the program with SystemCode 4


class LightLevelReading:
    """ Store image stats such as name, time, pixel_average and period."""

    def __init__(self, timestamp, pixel_average: float, light_level: LightLevel):
        self.timestamp = timestamp
        self.pixel_average = pixel_average
        self.light_level = light_level

    def __lt__(self, other_image_deets):
        return self.timestamp < other_image_deets.timestamp

    def __gt__(self, other_image_deets):
        return self.timestamp > other_image_deets.timestamp

    def __str__(self):
        return "ts:{} ll:{} pa:{:.3f}".format(
            self.timestamp, self.light_level, self.pixel_average)


class YoungColl(MutableSequence):
    """Maintain a list with no 'old' items
       Items must have a timestamp() -> (naive) datetime method
       Guanateed sorted
       (Could use sortedcontainers module too but just another dependancy)
    """

    def __init__(self, max_age=timedelta(hours=1)):
        self._max_age = max_age
        self.list = list()

    def trim_old_items(self):
        instant = dt.now()
        trimmed = (i for i in self.list
                   if i.timestamp + self._max_age >= instant)
        self.list = list(trimmed)

    def __len__(self):
        return len(self.list)

    def __getitem__(self, i):
        # Various looping functions call this with out of range 'i' and handle the execption
        return self.list[i] #@IgnoreException

    def __delitem__(self, i):
        del self.list[i]

    def __setitem__(self, i, v):
        self.list[i] = v
        self.list = sorted(self.list)

    def insert(self, i, v):  # pylint: disable=arguments-differ
        self.list.insert(i, v)
        self.list = sorted(self.list)

    def __str__(self):
        return str(self.list)


class LightLevelSensor():
    """ Determine the light level, based on current, and recent images' pixel_averages 
        Simplify? Just count number of sensings in a row and change when >3 in a row.
    """

    def __init__(self, light, dark, max_age=timedelta(hours=1), freq=timedelta(minutes=10)):
        assert light > dark
        self.light = light
        self.dark = dark
        self._current_level = LightLevel.LIGHT
        self._levels = YoungColl(max_age)
        self.freq = freq
        self.power_off = timedelta(hours=1)
        self.save_images = False

    def __str__(self):
        return "LightLevelSensor dark:{:.3f} light:{:.3f} level:{} len(_levels):{} _current_level:{} freq:{}".format(
            self.dark, self.light, str(self.level), len(self._levels), self._current_level.name, self.freq)

    def __repr__(self):
        return "LightLevelSensor dark:{:.3f} light:{:.3f} level:{} len(_levels):{} _current_level:{} freq:{}".format(
            self.dark, self.light, str(self.level), len(self._levels), self._current_level.name, self.freq)

    def _assess_level(self, pixel_average):
        """ Does not change current level, just assess """
        if pixel_average >= self.light:
            return LightLevel.LIGHT
        elif pixel_average < self.dark:
            return LightLevel.DARK
        else:
            return LightLevel.DIM

    def pixel_average(self) -> float:
        """ Return the latest pixel average, from a standard sensed image """
        return self._levels[-1].pixel_average

    def add_reading(self, instant, pixel_average):
        # Caution: with debugging this, calling level()
        # will trim the list and confuse the shit out of you
        llr = LightLevelReading(
            instant, pixel_average, self._assess_level(pixel_average))
        self._levels.append(llr)

    @property
    def level(self) -> LightLevel:
        """ Determine if it's DIM | DARK | LIGHT based on a list of recent images """
        if len(self._levels) > 0:
            most_recent_reading = self._levels[-1]
            self._levels.trim_old_items()
            if len(self._levels) == 0:
                # no readings left: remember the most recent
                self._current_level = most_recent_reading.light_level

        if len(self._levels) == 0:
            return self._current_level
        levels = [ll.light_level for ll in self._levels]
        most_recent_level = levels[-1]
        # we could have [DIM, DIM, DARK, DARK, DIM, DIM, LIGHT]
        # but we want   [                      DIM, DIM, LIGHT]
        # that is, only the last two type
        penultimate_level = penultimate_unique(levels)
        levels_last_two_unique = [level for level in levels
                                  if level == most_recent_level or (penultimate_level is None or level == penultimate_level)]
        constant_levels = all(level == most_recent_level for level in levels_last_two_unique)
        if most_recent_level != self._current_level and constant_levels:
            # it's been a new level for some time:  to this level
            LOGGER.info("LEVEL change from {} to {}".format(
                self._current_level, most_recent_level))
            self._current_level = most_recent_level
        return self._current_level

    # pylint: disable=protected-access
    @property
    def max_age(self):
        return self._levels._max_age

    @max_age.setter
    def max_age(self, max_age: timedelta):
        self._levels._max_age = max_age


class SunEvent(Enum):
    """ Calculated using current position and a time. Instants in time."""
    DAWN = 1
    SUNRISE = 2
    DUSK = 3
    SUNSET = 4


class ActiveTimes:
    """ Base for classes which contain triggers to turn the device on or off"""

    def __init__(self, on, off):
        if on == off:
            raise ConfigError("on and off must be different")
        self._on = on
        self._off = off

    def active(self):
        """ True if the "on" condition is met. Override in subclasses
            Active means we should take photos or run light sensor) """
        raise NotImplementedError()

    def next_active(self) -> dt:
        """ Return the next active time"""
        raise NotImplementedError()

    def waketime(self) -> dt:
        """ Generally the same as 'next', but can override"""
        return self.next_active()

    def active_in(self) -> timedelta:
        next_active = self.next_active()
        instant = dt.now()
        if next_active < instant:
            return timedelta(0)
        else:
            return next_active - instant

    def __str__(self):
        return "{}: on:{} off:{}".format(self.__class__, self._on, self._off)

    def __repr__(self):
        return "{}: on:{} off:{}".format(self.__class__, self._on, self._off)

    @staticmethod
    def factory(on, off, camera):
        """Create based on on/off parameters provided

        Arguments:
            on {[type]} - - [description]
            off {[type]} - - [description]

        Returns:
            on is time: timed
            on is string: sunrise | sunset | dawn | dusk: suncalc
            on is string: light | dim | dark: sensor
            on is boolean: fix            ed

        """
        if isinstance(on, bool):
            if not isinstance(off, bool):
                raise TypeError("on, off values must be in the same category")
            return Fixed(on, off)
        if isinstance(on, datetime.time):
            if not isinstance(off, datetime.time):
                raise TypeError("on, off values must be in the same category")
            return Timed(on, off)

        if isinstance(on, str):
            if on in ['sunrise', 'sunset', 'dawn', 'dusk']:
                if off not in ['sunrise', 'sunset', 'dawn', 'dusk']:
                    raise TypeError("on, off values must be in  same category")
                return SunCalc(on, off, camera.location)

            if on in ['light', 'dim', 'dark']:
                if off not in ['light', 'dim', 'dark']:
                    raise TypeError("on, off values must be in  same category")
                return Sensor(LightLevel(on.upper()),
                              LightLevel(off.upper()),
                              camera.light_sensor)

        raise TypeError("Didn't understand on/off settings")


class Sensor(ActiveTimes):
    """ Using the camera as a lux sensor, trigger based on light | dim | dark"""
    # todo: This whole Sensor/capture_light is confsed. SImplify!
    # Convenience
    DARK = LightLevel.DARK
    LIGHT = LightLevel.LIGHT
    DIM = LightLevel.DIM

    class LevelToActive:
        """ Convert a level to a activestate(on/off). """

        def __init__(self, on_level, off_level, other_level, from_dark, from_dim, from_light):
            self.on_level = on_level
            self.off_level = off_level
            self.other_level = other_level

            self.from_level = {}
            self.from_level[LightLevel.DARK] = from_dark
            self.from_level[LightLevel.DIM] = from_dim
            self.from_level[LightLevel.LIGHT] = from_light
            self._previous_level = None
            self._current_level = None

        def __repr__(self):
            return "LevelToActive from_level:{}".format(
                self.from_level)

        def level_to_active(self, previous_level, current_level):
            if current_level == self.off_level:
                return False
            elif current_level == self.on_level:
                return True
            else:
                assert current_level == self.other_level
                return self.from_level[previous_level]

    # We need to know the state (ON/OFF) of each light level,
    # but this has two parts: entering-from-stateX and entering-from-stateY
    # Use a static lookup and just select the right one.
    # *** A (better!?) apporach is to "do nothing" and maintain the
    # current_state during the other_level ****
    #
    #   ON      OFF     imples that:
    #   dark    dim     light=OFF
    #   dark    light   dark->dim=ON    light->dim=OFF
    #   dim     light   dark=ON
    #   dim     dark    light=ON
    #   light   dark    light->dim=ON   dark->dim=OFF
    #   light   dim     dark=OFF
    #
    #                                   FROM:
    #                 ON    OFF   OTHER DARK fDIM  fLIGHT
    lookups = [
        LevelToActive(DARK, DIM, LIGHT, False, False, None),
        LevelToActive(DARK, LIGHT, DIM, True, None, False),
        LevelToActive(DIM, LIGHT, DARK, None, True, True),
        LevelToActive(DIM, DARK, LIGHT, True, True, None),
        LevelToActive(LIGHT, DARK, DIM, False, None, True),
        LevelToActive(LIGHT, DIM, DARK, None, False, False),
    ]

    def __init__(self, on_level: LightLevel, off_level: LightLevel, light_sensor):
        super().__init__(on_level, off_level)
        self.light_sensor = light_sensor
        # the last different level (e.g. coming from DIM, now DARK)
        self.current_level = light_sensor.level
        self.previous_level = light_sensor.level
        self.lookup = next(la for la in self.lookups
                           if la.off_level == off_level and la.on_level == on_level)

    def __repr__(self):
        return "Sensor active:{} camera_active:{} on:{} off:{} lookup:{} prev_level:{} curr_level:{}".format(
            self.active(), self.camera_active(), self._on, self._off, self.lookup, self.previous_level, self.current_level)

    def active(self):
        """ See camera_active"""
        return True  # self.camera_active()

    def camera_active(self):
        """ Different to other ActiveTimers, this class is "active" when
            either the camera or the light sensor(or both) can be active """
        new_level = self.light_sensor.level
        if new_level != self.current_level:
            # level change!
            self.previous_level = self.current_level
            self.current_level = new_level
        camera_active = self.lookup.level_to_active(
            self.previous_level, self.current_level)
        if camera_active is None:
            # This is the 'other level': no change
            camera_active = self.current_level
        return camera_active

    def next_active(self):
        """ If inactive, the next active time is unknown as we can't sense the future! 
            Return the next sensing time as a guess"""
        if self.active():
            return dt.now()
        else:
            return dt.now() + self.light_sensor.freq

    def waketime(self):
        """ This class can poweroff even if active: when the camera is not required, but the sensor is used"""
        if self.camera_active():
            # Camera is on: don't power off
            return dt.now()
        else:
            # Camera of off (ut sensor is on): return a longish time to allow camera to power down then restart and sense
            return dt.now() + self.light_sensor.power_off


class Fixed(ActiveTimes):
    """ Always on or always off """

    def active(self):
        return self._on

    def next_active(self):
        if self.active():
            return dt.now()
        else:
            return dt.now() + timedelta(days=9999)
            # dt.max overflows


class Timed(ActiveTimes):
    """ Simply control on/off with a time """

    def __init__(self, on: time, off: time):
        super().__init__(on, off)
        if (not isinstance(self._on, datetime.time) or not isinstance(self._off, datetime.time)):
            # This is ok if's a FakeDateTime!
            LOGGER.warning(
                "on/off not a datetime. ({},{})".format(self._on.__class__, self._off.__class__))

    def active(self) -> bool:
        # Search through reversed list to find latest trigger time
        # Return the last trigger (i.e. effectively from the day before) if
        # no triggers are active (e.g. early morning with on at 10:00)

        ordered_capture_times = list(sorted([
            (self._on, True),
            (self._off, False)
        ]))
        rev_ordered_capture_times = list(
            reversed(ordered_capture_times))

        lt = dt.now().astimezone().time()  # local time
        active_trigger = next(
            (i for i in rev_ordered_capture_times if i[0] <= lt),
            rev_ordered_capture_times[0])
        return active_trigger[1]

    def next_active(self) -> dt:
        instant = dt.now()
        lt = instant.astimezone().time()  # local time
        if self.active():
            return instant
        elif lt <= self._on:
            # it's before on : today @ X o'clock
            return dt.combine(instant.date(), self._on)
        else:
            # it's after on : tomorrow @ X o'clock
            return dt.combine(instant.date(), self._on) + timedelta(hours=24)


class SunCalc(Timed):
    """ Using the location, estimate sun position(and hence SunEvent)
        and compare to on/off trigger. A special type of Timed  """

    def __init__(self, on: SunEvent, off: SunEvent, location: astral.LocationInfo):
        self.location = location
        if self.location is None:
            raise ConfigError(
                "No city specified: required for dawn|dusk|sunrise|sunset")
        self.on_event = on.lower()
        self.off_event = off.lower()
        self.sun_events = None
        self.update_calcs()
        super().__init__(self._on, self._off)

    def update_calcs(self):
        # varies depending on datetime.now():
        self.sun_events = sun(self.location.observer)
        # set on/off to times, then Timer can do everythong else
        self._on = self.sun_events[self.on_event].astimezone().time()
        self._off = self.sun_events[self.off_event].astimezone().time()

    def active(self):
        self.update_calcs()
        return super().active()


class Camera(Tomlable, Machine):
    """ A timelapse camera with a real/synth/dummy camera"""

    busy_sleep_s = .2  # testing with sleepless required >0.1

    # Defaults as per docs. Note:
    # - awb_gains: get/set, unknown default
    # These don't work:
    # 'brightness': 50,
    # 'exposure_compensation': 0,
    picam_defaults = {
        'awb_mode': 'auto',
        'contrast': 0,
        'drc_strength': 'off',
        'exposure_mode': 'auto',
        'framerate': 30,
        'hflip': False,
        'iso': 0,
        'meter_mode': 'average',
        'rotation': 0,
        'resolution': '640x480',
        'sharpness': 0,
        'shutter_speed': 0,
        'sensor_mode': 0,
        'saturation': 0,
        'still_stats': False,
        'vflip': False,
        'zoom': (0.0, 0.0, 1.0, 1.0)
    }

    def __init__(self, sw_cam=False):
        """ Not all defaults are set: you should call config before use."""
        Tomlable.__init__(self)

        # get_camera() will return an instance of this class
        if sw_cam:
            self.CameraClass = FakePiCamera
        else:
            self.CameraClass = PiCamera 
        # software only : read-only
        self.mode_button = StatefulButton(MODE_FILE, MODE_BUTTON_STATES, fallback=AUTO)
        self.current_mode = None
        self.speed_button = StatefulButton(SPEED_FILE, SPEED_BUTTON_STATES, fallback=MEDIUM)
        self.activity = StatesCircle(ACTIVITY_FILE, ACTIVITY_STATE, fallback=OFF)
        self.led = None  # illuminate when shutter open
        self.latest_image = Path('latest-image.jpg')
        self.camera = None  # reference to PiCamera or FakePiCamera
        self.video_port = 5001  # where a video capture will be streamed to (i.e. localhost:5001)
        self._pijuice = None
        self.calc_shutter_speed = False
        self.location = None
        self.recent_images = []

        self.run_started_at = None
        self.light_sensor = LightLevelSensor(0.2, 0.05, max_age=timedelta(minutes=30), freq=timedelta(minutes=5))
        self.light_sense_outstanding = False
        # just wait if less than this duration
        self.inactive_min = timedelta(minutes=30)
        self._interval = timedelta(seconds=60)
        self.active_timer = ActiveTimes.factory(on=True, off=False, camera=self)
        self.file_by_date = True
        self.save_images = True
        self._last_camera_settings = []

        self.tmv_root = Path(".")
        self.overlays = ['spinny', 'image_name', 'settings']
        self.camera_inactive_action = CameraInactiveAction.WAIT
        self.inactive_min = timedelta(minutes=30)
        # stored in a dictorary with keys as *str* (DIM|DARK|ETC) (not LightLevel enum)
        self.picam = {
            str(LightLevel.LIGHT): {
                'iso': 200,
                'exposure_mode': 'auto'
            },
            str(LightLevel.DIM): {
                'iso': 800,
                'exposure_mode': 'night'
            },
            str(LightLevel.DARK): {
                'iso': 1600,
                'exposure_mode': 'verylong'
            },
        }
        self.picam_sensing = {
            # These are adjusted so that:
            # light image > 0.2
            # dark  image < 0.05
            "iso": 200,
            "exposure_mode": 'off',
            "shutter_speed": 10000
        }

        # state machine setup
        states = ['starting', 'started', 'active', 'inactive', 'off', 'video', 'finished']
        transitions = [
            # trigger       source      dest conditionsw
            #['start', 'starting', 'started'],
            ['mode_to_off', '*', 'off'],
            ['mode_to_video', '*', 'video'],
            ['mode_to_on', ['active', 'off', 'started', 'inactive', 'video'], 'active'],
            ['mode_to_active', ['started', 'off','active', 'inactive', 'video'], 'active'],
            ['mode_to_inactive', ['started', 'inactive', 'active', 'video'], 'inactive'],
        ]
        Machine.__init__(self, states=states, initial='starting', transitions=transitions)

    def settle(self):
        # sleep a bit unless a FakeCamera
        time.sleep((self.CameraClass is not FakePiCamera) * 0.5)
        
    @property
    def interval(self):
        """ return the interval, adjusted via speed_button"""
        return interval_speeded(self._interval, self.speed_button.value)

    def configd(self, config_dict):
        c = config_dict  # shortcut
        if 'camera' in config_dict:
            c = config_dict['camera']  # can accept config in root or [camera]
        if 'log_level' in c:
            # set tmv logger (so it applies to all files, not just camera.py)
            logging.getLogger('tmv').setLevel(c['log_level'])

        self.tmv_root = Path(c.get('tmv_root', '.'))
        os.chdir(str(self.tmv_root))
        LOGGER.info(f"Changing to dir: {self.tmv_root}")

        if c.get('pijuice', False):
            try:
                # optional, for controling power with a PiJuice
                from tmv.tmvpijuice import TMVPiJuice  # pylint: disable=import-outside-toplevel
                self._pijuice = TMVPiJuice()
            except (ModuleNotFoundError, ImportError, NameError) as exc:
                self._pijuice = None
                LOGGER.warning("Failed to init pijuice:  {exc}. Continuing.")
                LOGGER.debug("Failed to init pijuice. Continuting.", exc_info=exc)

        self.setattr_from_dict('overlays', c)
        self.setattr_from_dict('calc_shutter_speed', c)

        if 'city' in c:
            # pylint: disable=no-else-raise
            if c['city'] == 'auto':
                raise NotImplementedError("city = 'auto' not implemented")
            else:
                self.location = lookup(c['city'], database())

        if 'camera_inactive_action' in c:
            self.camera_inactive_action = CameraInactiveAction[c['camera_inactive_action']]

        if 'interval' in c:
            # interval specified as seconds: convert to timedelta
            self._interval = timedelta(seconds=c['interval'])

        if 'inactive_threshold' in c:
            # inactive_threshold specified as seconds: convert to timedelta
            self.inactive_min = timedelta(seconds=c['inactive_threshold'])

        if 'on' in c and 'off' in c:
            # create the controller for active periods
            self.active_timer = ActiveTimes.factory(                c['on'], c['off'], self)
        else:
            LOGGER.warning("[camera] on and off times should be set. Defaulting to {}".format(
                self.active_timer))
        # config picam modes for light levels
        if 'picam' in c:
            for level_str in [ll.value for ll in LightLevel]:
                if level_str in c['picam']:
                    self.picam[level_str] = c['picam'][level_str]
                    if 'framerate' in self.picam[level_str]:
                        if self.picam[level_str]['framerate'] < 0.20:  # 1/6 is the minimum, use 1/5 for safety
                            raise ConfigError("framerate={} is < 1/5 s".format(
                                self.picam[level_str]['framerate']))

        # config light sensor
        if 'sensor' in c:
            setattrs_from_dict(self.light_sensor, c['sensor'])
            if 'freq' in c['sensor']:
                self.light_sensor.freq = timedelta(
                    seconds=float(c['sensor']['freq']))
            if 'max_age' in c['sensor']:
                self.light_sensor.max_age = timedelta(
                    seconds=float(c['sensor']['max_age']))
            if 'power_off' in c['sensor']:
                self.light_sensor.power_off = timedelta(
                    seconds=float(c['sensor']['power_off']))

        # sanity checks
        if self.light_sensor.power_off <= self.inactive_min:
            # Otherwise we will never power off
            raise ConfigError("power_off ({}) must be longer than inactive_min ({}). "
                              .format(self.light_sensor.power_off, self.inactive_min))

        known_keys = ['log_level', 'sensor', 'picam', 'on', 'off', 'inactive_threshold',
                      'camera_inactive_action', 'interval', 'city', 'pijuice',
                      'tmv_root', 'overlays', 'calc_shutter_speed',
                      'activity']

        unknowns = list(k for k in c if k not in known_keys)
        if unknowns:
            raise ConfigError(f'Unknown settings for [camera]: {unknowns}')

    def __str__(self):
        return pformat(vars(self))

 
    def get_camera(self):
        """Suggest you use new PiCamera returned in content manager ('with') """
        return self.CameraClass()
        
    def start(self):
        assert self.state == 'starting'
        assert isinstance(self.tmv_root,Path)
        self.run_started_at = dt.now()
        if self._pijuice:
            self._pijuice.wakeup_disable() # ensure no false wakeups if alarm was set before running 
        # Run the light sensor so we know what to do on the first loop
        if self.mode_button.value == AUTO or self.mode_button.value == ON:
            with self.get_camera() as cam:
                set_picam(cam, {** self.picam_defaults, ** self.picam_sensing})
                self.settle()
                self.capture_light(cam, dt.now())
        LOGGER.debug(f"Camera started. First light level: {self.light_sensor.level} interval: {self.interval.total_seconds()}s")
        self.to_started()

    def run(self, n=maxsize):
        """
        Main loop. May shutdown machine if required.
        """
        if self.state == "starting":
            self.start()

        for _ in range(0, n):

            # if mode button changes, run a transition
            self.dispatch_mode_button_transitions()
            
            # run the current state
            if self.state == "started":
                time.sleep(self.busy_sleep_s)
            elif self.state == "video":
                self.state_video_loop()
            elif self.state == "active":
                self.state_active_loop()
            elif self.state == "off":
                # do nothing via a long sleep
                time.sleep(self.busy_sleep_s * 5)
            elif self.state == "inactive":
                # if inactive for too long, end finished state.
                if self.active_timer.waketime() - dt.now() >= self.inactive_min and \
                        self.camera_inactive_action != CameraInactiveAction.WAIT:
                    LOGGER.debug(f"inactive for {self.active_timer.waketime() - dt.now()}. Finishing.")
                    self.finish()
                time.sleep(self.busy_sleep_s)
            else:
                raise RuntimeError(f"Unexpected state of {self.state}")

    def state_active_loop(self):
        # use instant here to ease debug, but dt.now()
        # to sleep the exact amount
        instant = dt.now()
        next_image_mark = next_mark(self.interval, instant)
        next_sense_mark = next_mark(self.light_sensor.freq, instant)
        LOGGER.debug("interval: {} instant: {} next_image_mark: {} next_sense_mark: {}".format(self.interval, instant, next_image_mark, next_sense_mark))

        if self.light_sense_outstanding:
            # run light sensor that we missed, immediately
            with self.get_camera() as cam:
                set_picam(cam, {** self.picam_defaults, ** self.picam_sensing})
                self.settle()
                self.capture_light(cam, dt.now())

            # no need to sense again this loop
            self.light_sense_outstanding = False
            next_sense_mark = dt.now() + timedelta(days=9999)  # dt.max() overflows

        if next_image_mark == next_sense_mark:
            # they want the same time: do the image and note outstanding for the sensor
            self.light_sense_outstanding = True
        if next_image_mark <= next_sense_mark:
            # capture image

            settings = {** self.picam_defaults, ** self.picam[self.light_sensor.level.name]}
            LOGGER.debug(f"self.calc_shutter_speed={self.calc_shutter_speed} settings['exposure_mode']={settings['exposure_mode']}")
            if self.calc_shutter_speed and settings['exposure_mode'] == 'off':
                # exposure_speed: 'retrieve the current shutter speed'
                # shutter_speeed is the requested value
                settings['shutter_speed'] = self.shutter_speed_from_last()
                if settings['shutter_speed'] is None:
                    settings['shutter_speed'] = self.shutter_speed_from_sensor()
            
            # busy sleep (in case the speed is changed) until we're ready to go
            while dt.now() < next_image_mark and self.mode_button.value == self.current_mode:
                next_image_mark = next_mark(self.interval, instant)
                time.sleep(self.busy_sleep_s)
            
            # don't take a photo if mode was changed whilst waiting
            if self.mode_button.value == self.current_mode:
                with self.get_camera() as cam:
                    set_picam(cam, settings)
                    self.settle()
                    self.capture_image(cam, next_image_mark)
        else:
            # run light sensor

            # non-busy sleep
            while dt.now() < next_sense_mark and self.mode_button.value == self.current_mode :
                time.sleep(self.busy_sleep_s)

            # don't take a photo if mode was changed whilst waiting
            if self.mode_button.value == self.current_mode: 
                with self.get_camera() as cam:
                    set_picam(cam, {** self.picam_defaults, ** self.picam_sensing})
                    self.capture_light(cam, next_sense_mark)

    def state_video_loop(self):
        """Stream a video in a thread until mode button ain't VIDEO no more"""
        LOGGER.debug(f"Starting video at :{self.video_port}")
        # use self.CameraClass for mocking but haven't done video mock
        with self.CameraClass(resolution='640x480', framerate=5) as camera:
            # StreamingOutput (class) is used to output the frames
            # We attach the camera stream to it and then pass to Server
            output = StreamingOutput()
            camera.start_recording(output, format='mjpeg')
            StreamingHandler.output = output
            # ensure these are declared in finally block
            server = None
            server_thread = None
            try:
                address = ('', self.video_port)
                server = TMVStreamingServer(address, StreamingHandler)
                # daemon=True means kill on main process exit (don't wait for it to join)
                server_thread = threading.Thread(target=server.serve_forever, daemon=True)
                server_thread.start()
                while self.mode_button.value == VIDEO:
                    time.sleep(self.busy_sleep_s)
            except IOError as exc:
                # Image server failed but we're ok to continue TMV
                # if e.errno == 98 => bind error
                LOGGER.warning(exc)
                time.sleep(10) # we'll try again on next loop, so don't thrash
            finally:
                LOGGER.debug("Stopping video. Leaves socket OPEN??? sometimes")
                camera.stop_recording()
                if server:
                    server.shutdown()  # "blocked until serve_forever exits"
                    server.socket.close() # doublely sure.... ???

                if server_thread:
                    server_thread.join()

    def dispatch_mode_button_transitions(self):
        mode = self.mode_button.value  # get once as reads a file and could change
        if mode != self.current_mode:
            LOGGER.debug(f"Changing mode to {mode}. Disabling pijuice wakeup")
            self.current_mode = mode
            if self._pijuice:
                # we only what to wakeup in auto mode, and coming from auto mode it might still be set
                self._pijuice.wakeup_disable()
        if mode == ON:
            self.mode_to_on()  # state will be active now (i.e. on ==> force active)
        elif mode == OFF:
            self.mode_to_off()
        elif mode == AUTO:
            # note that two triggers with inverse conditions for Machine don't work (second one never runs)
            # so do it manually here
            if self.active_timer.active():
                self.mode_to_active()
            else:
                self.mode_to_inactive()
        elif mode == VIDEO:
            time.sleep(5) # don't start video if just scrolling past in button UI
            if mode  == "video":
                self.mode_to_video()
        else:
            raise RuntimeError(f"Unexpected mode of {self.mode_button.value}")

    def shutter_speed_from_last(self):
        """ Return estimated shutter speed in usec based on trying to achieve a pixel
            average of 0.5 on the last image, using linear interpolation """
        if len(self.recent_images) == 0:
            LOGGER.debug("No recent images to calc shutter speed")
            return None
        last_image = self.recent_images[-1]
        pa1 = last_image[3]
        es1 = last_image[2]
        if es1 is None:
            LOGGER.debug("No shutter speed stored")
            return None
        if pa1 == 0:
            LOGGER.debug("Pixel average is zero")
            return 999
        pa2 = 0.5
        es2 = pa2 * es1 / pa1
        es2 = max(es2, 5)  # max shutter open time

        es_min = (1 / 100) * 1000000  # 10,000us
        es_max = 5 * 1000000
        es2 = min(es_max, es2)
        es2 = max(es_min, es2)
        es2 = int(es2)
        LOGGER.debug(f"pa1={pa1:.2f} es1={es1} pa2={pa2:.2f} es2={es2}")
        return int(es2)

    def shutter_speed_from_sensor(self):
        """ Return estimated 'good' shutter (in whole microseconds) speed based on the sensor
        Empirical and not very good: use shutter_speed_from_list where possible
        Linear: pixel_average     length
                 PA                SL
        Max:     0.0*             5s
        Min      0.5              1/250
        * fixed
        SL = m * PA + c => c=max_length, m=min_length - c / (PA_min)

          |           -------       }
          |         /               } constrain between
        SL|      /                  } max_length and min_length
          |  ---                    }
          |_____________________
                     PA

        """
        sl_min = (1 / 100) * 1000000  # 10,000us
        sl_max = 5 * 1000000
        # sensor is insensitive
        # default definition of 'dark' is 0.05
        pa_min = 0.02
        pa_max = 0.0
        c = sl_max
        m = (sl_min - c) / (pa_min - pa_max)
        pa = self.light_sensor.pixel_average()
        sl = m * pa + c
        sl = min(sl_max, sl)
        sl = max(sl_min, sl)
        sl = int(sl)
        LOGGER.debug(f"pa={pa:.3f} M_sl={sl:0.3f} m={m:.2f} c={c:.2f}")

        return sl

    @staticmethod
    def save_image(pil_image, image_path: Path):
        try:
            if pil_image.size[0] * pil_image.size[1] == 0:
                raise RuntimeError("Image has zero width or height")
            pil_image.verify()  # raises "suitable exception"
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning(f"{image_path} failed verify and is not saved: {exc}")
            return
        image_path.absolute().parent.mkdir(exist_ok=True,parents=True)
        #if os.path.dirname(image_filename) != '':
        #    os.makedirs(os.path.dirname(image_filename), exist_ok=True)
        if 'exif' in pil_image.info:
            pil_image.save(str(image_path), exif=pil_image.info['exif'])
        else:
            pil_image.save(str(image_path))

    def capture_image(self, cam, mark):

        start = dt.now()
        self.activity.value = ON
        if self.led:
            self.led.on()

        # Capture sensor buffer to an in-memory stream
        stream = BytesIO()
        cam.capture(stream, format='jpeg')  # use_video_port=True results in poorer quality images
        stream.seek(0)  # "Rewind" the stream to the beginning so we can read its content
        pil_image = Image.open(stream)

        self.activity.value = OFF
        if self.led:
            self.led.off()

        pa = image_pixel_average(pil_image)
        LOGGER.info("CAPTURED mark: {} pa:{:.3f} es:{:0.3f}s took:{:.3f}s".format(mark, pa, cam.exposure_speed / 1000000, (dt.now() - start).total_seconds()))
        image_filename = self.dt2filename(mark)
        self.recent_images.append((dt.now(), image_filename, cam.exposure_speed, pa),)
        del self.recent_images[0:-10]  # trim to last 10 items

        if self.save_images:
            self.apply_overlays(pil_image, mark)
            self.save_image(pil_image, image_filename)
            self.link_latest_image(image_filename)

        self._last_camera_settings = get_picam(cam)

    def capture_light(self, cam, mark):
        image_filename = self.dt2dir(mark) / self.dt2basename(mark, image_ext=".sense.jpg")
        start = dt.now()
        # Capture sensor buffer to an in-memory stream
        stream = BytesIO()
        cam.capture(stream, format='jpeg')  # use_video_port=True results in poorer quality images
        stream.seek(0)  # "Rewind" the stream to the beginning so we can read its content
        pil_image = Image.open(stream)
        pa = image_pixel_average(pil_image)

        ll = self.light_sensor._assess_level(pa)
        self.light_sensor.add_reading(mark, pa)
        LOGGER.debug("SENSED mark:{} pa:{:.3f} ll:{} took:{:.2f}".format(mark, pa, ll, (dt.now() - start).total_seconds()))

        if self.light_sensor.save_images:
            self.apply_overlays(pil_image, mark)
            self.save_image(pil_image, image_filename)

        self._last_camera_settings = get_picam(cam)

    def link_latest_image(self, image_filename):
        """ Add hardlink to the specified image at a well-known location """
        # Image may be uploaded in the meantime
        try:
            unlink_safe(self.latest_image)
            os.link(image_filename, str(self.latest_image))
        except FileNotFoundError as ex:
            LOGGER.warning(f"Unable to link latest image: {ex}")

    def apply_overlays(self, im: Image, mark):
        """ Add dates, spinny, etc. Inplace."""
        pxavg = image_pixel_average(im)
        bg_colour = (128, 128, 128, 128)
        text_colour = (255, 255, 255)
        width, height = im.size
        draw = ImageDraw.Draw(im)
        band_height = 30

        try:
            if 'bottom_band' in self.overlays:
                draw.rectangle(xy=(0, height - 30, width, height), fill=bg_colour)
            if 'settings' in self.overlays:
                # Draw the picam's settings
                text = pformat(self._last_camera_settings)
                text += "\n\npixel_average = {pxavg:.3f}"
                text_size = 10
                font = ImageFont.truetype(FONT_FILE_IMAGE, text_size, encoding='unic')
                text_box_size = draw.textsize(text=text, font=font)
            if 'simple_settings' in self.overlays:
                # Draw some of picam's settings
                text = pformat(get_picam(self._last_camera_settings))
                text = f"sensor={self.light_sensor.pixel_average():.3f} level={self.light_sensor._current_level} px_avg={pxavg:.3f}"
                try:
                    LOGGER.debug(f"self._last_camera_settings = {self._last_camera_settings}")
                    text += f" es {self._last_camera_settings['exposure_speed']/1000000:.3f} iso={self._last_camera_settings['iso']} exp={self._last_camera_settings['exposure_mode']}"
                except KeyError as ex:
                    LOGGER.warning(f"Unable to get picam settings for overlay: {ex}")
                text_size = 10
                font = ImageFont.truetype(FONT_FILE_IMAGE, text_size, encoding='unic')
                tw, th = draw.textsize(text=text, font=font)
                # RHS
                x = width - tw
                # one line above bottom
                y = height - th * 2
                draw.text(xy=(x, y), text=text, fill=text_colour, font=font)
            if 'spinny' in self.overlays:
                # Draw circles with a hour and minute hand, for continuity checking. Plus it looks cool.
                # 1px off corner x1    y1              x2      y2
                bounding_box = [(1, height - band_height), (band_height, height - 1)]
                # hour hand
                draw.pieslice(bounding_box, mark.hour / 12 * 360 - 90,
                              mark.hour / 12 * 360 - 90 -1, fill=None, outline=text_colour, width=2) 
                draw.arc(bounding_box, 0, 360, fill=text_colour)
                bounding_box = [(1+band_height, height - band_height), (1+band_height*2, height - 1)]
                # minute hand
                draw.pieslice(bounding_box, mark.minute / 60 * 360 - 90,
                              mark.minute / 60 * 360 - 90-1, fill=None, outline=text_colour, width=2)
                draw.arc(bounding_box, 0, 360, fill=text_colour)
            if 'image_name' in self.overlays:
                text = os.path.basename(self.dt2basename(mark))
                text_size = 10
                font = ImageFont.truetype(FONT_FILE_IMAGE, text_size, encoding='unic')
                # Get the size of the time to write, so we can correctly place it
                text_box_size = draw.textsize(text=text, font=font)
                # centre text
                x = int((width / 2) - (text_box_size[0] / 2))
                # place one line above bottom
                y = (height - text_box_size[1] * 2)
                draw.text(xy=(x, y), text=text, fill=text_colour, font=font)

        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning(f"Exception adding overlays: {exc}")
            LOGGER.debug(f"Exception adding overlays: {exc}", exc_info=exc)

    def dt2dir(self, mark: datetime) -> Path:
        """ Return current directory for image saves eg. ./cam1/2000-11-01/"""
        if self.file_by_date:
            folder_naming_format = "%Y-%m-%d"
            subfolder = mark.strftime(folder_naming_format)
            return self.tmv_root / subfolder
        else:
            return self.tmv_root

    def dt2filename(self, mark: datetime) -> Path:
        """ Full filename(including dir) eg. ./cam1/2000-11-01/2000-11-01T00-12-00.jpg"""
        return self.dt2dir(mark) / self.dt2basename(mark)

    def dt2basename(self, mark: datetime, image_ext=".jpg") -> str:
        """ Name of the saved file. "basename" as per os.path.basename"""
        # eg. 2000-11-01T00-12-00.jpg
        image_naming_format = "%Y-%m-%dT%H-%M-%S"
        return mark.strftime(image_naming_format) + image_ext

    def finish(self):
        """
        Camera finished, so undertake requested action(exit, etc)
        Doesn't return unless interrupt (e.g. mode change during 60s before power down)
        """
        #LOGGER.debug(''.join(traceback.format_stack()[-20:]))
        waketime = self.active_timer.waketime()
        if self.camera_inactive_action == CameraInactiveAction.EXCEPTION:
            raise PowerOff(f"Camera finished. Mode: {self.current_mode}. Wake at {waketime}".format())
        if self.camera_inactive_action == CameraInactiveAction.POWER_OFF:
            # Turn off power and wakeup later
            if self._pijuice is not None:
                LOGGER.warning(f"Camera finished. Mode: {self.current_mode}. Powering off in 60s. Waking at {waketime}.")
                power_off_at = dt.now() + timedelta(seconds=60)               
                # busy wait, returning if mode changes (abort shutdown)
                while dt.now() < power_off_at:
                    if self.mode_button.value != self.current_mode:
                        return
                    time.sleep(self.busy_sleep_s)   
                self._pijuice.wakeup_enable(waketime)  # pass wakeup as a (local) time
                self._pijuice.power_off()
            else:
                raise PiJuiceError("Trying to sleep but no pijuice available. Set pijuice=true in config perhaps?")
        elif self.camera_inactive_action == CameraInactiveAction.EXIT:
            LOGGER.info(f"Camera finished. Exiting. Wake was at {waketime}")
            sys.exit(4)
        else:
            raise RuntimeError(f"Unexpected camera_inactive_action of {self.camera_inactive_action}")




def sun_calc_lightlevel(observer, instant) -> LightLevel:
    """Categorise a datetime based on sun's position and a location

    Arguments:
        dt {[type]} -- Must be tz aware
        location {DbIp.observer | (lat,long,ele)} --

    Note:
        Could cache sun_events
        """
    sun_events = astral.sun.sun(observer)

    if instant < sun_events['sunrise'] or instant > sun_events['sunset']:
        return LightLevel.DIM

    if sun_events['sunrise'] <= instant <= sun_events['sunset']:
        return LightLevel.LIGHT

    raise Exception("Error categoising " + instant)


def set_picam(picam, settings):
    """ Do manually to enable ordering and error checking """
    # iso first ?
    settable_settings = ['sensor_mode', 'framerate', 'iso', 'shutter_speed',
                         'awb_mode', 'exposure_mode',
                         'contrast', 'drc_strength',
                         'hflip',
                         'meter_mode', 'rotation', 'resolution',
                         'sharpness', 'saturation',
                         'still_stats', 'zoom', 'vflip']

    if type(picam).__name__ == "PiCamera":
        # logger.debug("Setting to {}".format(pformat(settings)))

        # warn of invalid settings
        for k, v in settings.items():
            if k not in settable_settings:
                raise ConfigError(
                    "'{}={}' is not settable for picam".format(k, v))
        # set
        for k in settable_settings:
            if k in settings.keys():
                if k == 'exposure_mode' and settings[k] != picam.exposure_mode:
                    # logger.debug(
                    #    "Exposure mode changed from {} to {}: sleep 1s".
                    #    format(settings[k], picam.exposure_mode))
                    time.sleep(1)
                setattr(picam, k, settings[k])


def get_picam(c):
    """ Return a dict of the attributes in a PiCamera"""
    d = {}
    if type(c).__name__ == "PiCamera":
        all_settings = ['analog_gain', 'awb_mode', 'awb_gains', 'contrast', 'drc_strength', 'digital_gain',
                        'exposure_mode', 'exposure_speed', 'framerate', 'hflip', 'iso',
                        'meter_mode', 'rotation', 'sharpness',
                        'shutter_speed', 'sensor_mode', 'saturation',
                        'still_stats', 'zoom', 'vflip']
        for s in all_settings:
            d[s] = getattr(c, s)
    return d


def calc_pixel_average(image_filename):
    img = Image.open(image_filename)
    img_stats = ImageStat.Stat(img)
    # Get dynamically?
    pmin = 0
    pmax = 255
    # .mean = [r,g,b]
    pmean = sum(img_stats.mean) / len(img_stats.mean)
    pmean_frac = (pmean - pmin) / (pmax - pmin)
    return pmean_frac


def image_pixel_average(img: Image):
    img_stats = ImageStat.Stat(img)
    # Get dynamically?
    pmin = 0
    pmax = 255
    # .mean = [r,g,b]
    pmean = sum(img_stats.mean) / len(img_stats.mean)
    pmean_frac = (pmean - pmin) / (pmax - pmin)
    return pmean_frac


def sig_handler(signal_received, frame):
    raise SignalException


def camera_console(cl_args=argv[1:]):
    # pylint: disable=broad-except
    retval = 0
    signal(SIGINT, sig_handler)
    signal(SIGTERM, sig_handler)
    parser = argparse.ArgumentParser("TMV Camera.")
    parser.add_argument('--log-level', '-ll', type=lambda s: LOG_LEVELS(s).name, nargs='?', choices=LOG_LEVELS.choices())
    parser.add_argument('--config-file', '-cf', default=CAMERA_CONFIG_FILE,
                        help="Config file is required. It will be created if non-existant.")
    parser.add_argument('--fake', action='store_true',help="Use FakePiCamera")
    parser.add_argument('--runs', type=int, default=maxsize)
    parser.add_argument("--debug", default=False, action='store_true',help="Use debugpy and wait for remote debugger on :5678")

    args = (parser.parse_args(cl_args))

    logging.basicConfig(format=LOG_FORMAT)  # set all debuggers, level=args.log_level)
    ensure_config_exists(args.config_file)
    LOGGER.info("Using config: {args.config_file}")

    if args.debug:
        debug_port = 5678
        debugpy.listen(("0.0.0.0", debug_port))
        print(f"Waiting for debugger attach on {debug_port}")
        debugpy.wait_for_client()
        debugpy.breakpoint()

    LOGGER.info(f"Starting camera app. config-file: {Path(args.config_file).absolute()} ")

    cam = Camera(sw_cam=args.fake)

    try:
        ensure_config_exists(args.config_file)
        cam.config(args.config_file)
        if args.log_level:
            # set tmv logger (so it applies to all files, not just camera.py)
            logging.getLogger("tmv").setLevel(args.log_level)  # cl overrides config
        cam.run(args.runs)

    except SignalException:
        LOGGER.info('SIGTERM, SIGINT or CTRL-C detected. Exiting gracefully.')
        retval = 0
    except toml.decoder.TomlDecodeError as e:
        retval = 1
        LOGGER.error("TOML error in {}:{} ".format(args.config_file, e))
        LOGGER.debug(e, exc_info=e)
    except BaseException as e:
        retval = 1
        LOGGER.error(e)
        LOGGER.debug(e, exc_info=e)
    finally:
        # workaround bug: https://github.com/waveform80/picamera/issues/528
        # if cam._camera is not None:
        #    LOGGER.info("Closing camera. Setting framerate = 1 to avoid close bug")
        #    cam._camera.framerate = 1
        #    cam._camera.close()
        #    time.sleep(0.5)
        pass

    return retval


if __name__ == "__main__":
    camera_console()
