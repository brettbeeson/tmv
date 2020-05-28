# pylint: disable=line-too-long, logging-fstring-interpolation, dangerous-default-value, logging-not-lazy

from signal import signal, SIGINT, SIGTERM
import argparse
from io import BytesIO
import sys
from enum import Enum
import datetime
from datetime import datetime as dt, timedelta             # dt = class
import time
import os
from os.path import join
import logging
from collections.abc import MutableSequence
from pprint import pformat
from pathlib import Path
import shutil
from math import exp, sqrt, tau
from pkg_resources import resource_filename

import toml
from PIL import Image, ImageFont, ImageDraw, ImageStat
import astral
from astral.geocoder import database, lookup  # Get co-ordinates from city name
from astral.sun import sun

from tmv.util import penultimate_unique, next_mark, LOG_FORMAT, LOG_LEVELS
from tmv.util import Tomlable, setattrs_from_dict, sleep_until, FONT_FILE
from tmv.exceptions import ConfigError, PiJuiceError, SignalException, CameraError, PowerOff
from tmv.controller import Switches, ON, OFF, AUTO

LOGGER = logging.getLogger("tmv.camera")  # __name__

DFLT_CAMERA_CONFIG_FILE = "/etc/tmv/camera.toml"

try:
    # optional, for controling power with a PiJuice
    from tmv.pijuice import TMVPiJuice
except (ImportError, NameError) as exc:
    LOGGER.debug(exc)

try:
    from picamera import PiCamera
except ImportError as exc:
    LOGGER.debug(exc)


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

    def __gt__(self, other):
        if other == LightLevel.LIGHT:
            return False
        elif other == LightLevel.DIM:
            return self == LightLevel.LIGHT
        elif other == LightLevel.DARK:
            return self != LightLevel.DARK


class CameraInactiveAction(Enum):
    """ What to do if the camera is inactive? """
    WAIT = 1        # Remain on, and just wait until next active time
    POWER_OFF = 2    # Power off (use PiJuice, etc)
    EXCEPTION = 3   # Raise a PowerOff exception
    EXIT = 4        # Exit the program with SystemCode 4


class LightLevelReading:
    """ Store image stats such as name, time, pixel_average and period."""

    def __init__(self, timestamp, pixel_average, light_level):
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
        return self.list[i]

    def __delitem__(self, i):
        del self.list[i]

    def __setitem__(self, i, v):
        self.list[i] = v
        self.list = sorted(self.list)

    def insert(self, i, v):
        self.list.insert(i, v)
        self.list = sorted(self.list)

    def __str__(self):
        return str(self.list)


class LightLevelSensor():
    """ Determine the light level, based on current, and recent images' pixel_averages """

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

    def add_reading(self, instant, pixel_average):
        # Bit tricky: with debugging this, calling level()
        # will trim the list and confuse the shit out of you
        llr = LightLevelReading(
            instant, calc_pixel_average, self._assess_level(pixel_average))
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
        levels = [i.light_level for i in self._levels]
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
        """ Always true, as the light sensor is always active. See camera_active"""
        camera_active = self.camera_active()
        sensor_active = True
        return camera_active or sensor_active

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
        """ If inactive, the next active time is unknown
         as we can't sense the future! Return the next sensing time
         as a guess"""
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


class Camera(Tomlable):
    """ A timelapse camera """

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

    def __init__(self):
        self._camera = None
        self._pijuice = None
        try:
            self._pijuice = TMVPiJuice()
        except (ImportError, NameError) as exc:
            self._pijuice = None
            print(exc)
        self.location = None
        self.recent_images = []
        self.run_start = None
        self.light_sensor = LightLevelSensor(0.2, 0.05, timedelta(minutes=5), timedelta(seconds=60))
        self.light_sense_outstanding = False
        # just wait if less than this duration
        self.inactive_min = timedelta(minutes=30)
        self.interval = timedelta(seconds=60)
        self.active_timer = ActiveTimes.factory(on=True, off=False, camera=self)
        self.file_by_date = True
        self.save_images = True
        self.file_root = os.path.abspath(".")
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

    def configd(self, config_dict):

        if 'camera' in config_dict:
            c = config_dict['camera']

            if 'log_level' in c:
                LOGGER.setLevel(c['log_level'])

            self.setattr_from_dict('file_by_date', c)
            self.setattr_from_dict('file_root', c)
            self.file_root = os.path.abspath(
                os.path.expanduser(self.file_root))
            self.setattr_from_dict('overlays', c)

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
                self.interval = timedelta(seconds=c['interval'])
                if self.interval.total_seconds() < 10.0:
                    LOGGER.warning("Intervals < 10s are not tested")

            if 'inactive_threshold' in c:
                # inactive_threshold specified as seconds: convert to timedelta
                self.inactive_min = timedelta(
                    seconds=c['inactive_threshold'])

            if 'on' in c and 'off' in c:
                # create the controller for active periods
                self.active_timer = ActiveTimes.factory(
                    c['on'], c['off'], self)
            else:
                LOGGER.warning("[camera] on and off times should be set. Defaulting to {}".format(
                    self.active_timer))
            # config picam modes for light levels
            if 'picam' in c:
                for level_str in [ll.value for ll in LightLevel]:
                    if level_str in c['picam']:
                        self.picam[level_str] = c['picam'][level_str]
                        if 'framerate' in self.picam[level_str]:
                            if self.picam[level_str]['framerate'] < (1 / 5):  # 1/6 is the minimum?
                                raise ConfigError("framerate={} is incorrect".format(
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

    def manual_override(self, on: bool):
        self.active_timer = ActiveTimes.factory(on, not on, self)

    def __str__(self):
        return pformat(vars(self))

    def run(self, n=sys.maxsize):
        """
        Main loop. May shutdown machine if required.
        """
        if self._camera is None:
            try:
                LOGGER.debug("Picamera() start")
                self._camera = PiCamera(led_pin=40)  # PiZero's BCM GPIO40 is the camera's LED
                LOGGER.debug("Picamera() returned")
            except Exception:
                raise CameraError("No camera hardware available")

        if self.run_start is None:
            self.run_start = dt.now()
            # Run the light senser so we know what to do on the first loop
            set_picam(self._camera, {** self.picam_defaults, ** self.picam_sensing})
            self.capture_light(dt.now())
            LOGGER.debug("Firstrun: level: {}".format(self.light_sensor.level))

        for _ in range(0, n):
            # Sleep / power off / etc if the camera is inactive
            waketime = self.active_timer.waketime()
            if waketime - dt.now() >= self.inactive_min:
                self.camera_inactive_until(waketime)
                # if we slept (i.e. didn't power-off), we need
                # to check the light level again before blindly taking
                # a photo. This is relevant to Sensor
                self.light_sense_outstanding = True
            # Sleep until next "active" time. Sometime it's not active after sleep! :
            # 1. can be not true for Suncalc by a minute or so,
            # because sunset/etc times change day by day
            # so upon wakeup, may be slightly later (hence inactive!)
            # 2. for Sensor, it doesn't know when to activate. If not turning off
            # we can just keep running the light sensor (). If turning off,
            # we want to turn off for an hour and then re-check.
            # Hence we check if we're really active after sleeping and consider if we
            # should just run the light_sensor

            if self.active_timer.active() and self.light_sense_outstanding:
                # run light sensor that we missed, immediately
                set_picam(self._camera, {
                    ** self.picam_defaults, ** self.picam_sensing
                })
                self.capture_light(dt.now())
                self.light_sense_outstanding = False

            if self.active_timer.active():
                # use instant here to ease debug, but dt.now()
                # to sleep the exact amount
                instant = dt.now()
                next_image_mark = next_mark(self.interval, instant)
                next_sense_mark = next_mark(
                    self.light_sensor.freq, instant)
                # logger.debug("instant: {} next_image_mark: {} next_sense_mark: {}".format(                        instant, next_image_mark, next_sense_mark))
                if next_image_mark == next_sense_mark:
                    # they want the same time: do the image and note outstanding for the sensor
                    self.light_sense_outstanding = True
                if next_image_mark <= next_sense_mark:
                    # capture image
                    set_picam(self._camera, {** self.picam_defaults, ** self.picam[self.light_sensor.level.name]})
                    sleep_until(next_image_mark, dt.now())
                    self.capture_image(next_image_mark)
                else:
                    # run light sensor
                    set_picam(self._camera, {** self.picam_defaults, ** self.picam_sensing})
                    sleep_until(next_sense_mark, instant)
                    self.capture_light(next_sense_mark)


    @staticmethod
    def save_image(pil_image, image_filename):
        try:
            if (pil_image.size[0] * pil_image.size[1] == 0):
                raise RuntimeError("Image has zero width or height")
            pil_image.verify()
        except Exception as exc:
            LOGGER.warning(f"{image_filename} failed verify and is not saved: {exc}")
            return
        if os.path.dirname(image_filename) != '':
            os.makedirs(os.path.dirname(image_filename), exist_ok=True)
        if 'exif' in pil_image.info:
            pil_image.save(image_filename, exif=pil_image.info['exif'])
        else:
            pil_image.save(image_filename)
        
    def capture_image(self, mark):
        image_filename = self.dt2filename(mark)
        self.recent_images.append((dt.now(), image_filename))
        del self.recent_images[0:-10]  # trim to last 10 items
        start = dt.now()
        self._camera.led = True
        pil_image = self.capture()
        self._camera.led = False

        pa = image_pixel_average(pil_image)
        LOGGER.debug("CAPTURED mark: {} pa:{:.3f} took:{:.2f}".format(mark, pa, (dt.now() - start).total_seconds()))

        if self.save_images:
            self.apply_overlays(pil_image, mark)
            self.save_image(pil_image, image_filename)

    def capture_light(self, mark):
        image_filename = join(self.dt2dir(
            mark), self.dt2basename(mark, image_ext=".sense.jpg"))
        start = dt.now()
        pil_image = self.capture()
        pa = image_pixel_average(pil_image)
        ll = self.light_sensor._assess_level(pa)
        self.light_sensor.add_reading(mark, pa)
        LOGGER.debug("SENSED mark: {} pa:{:.3f} ll:{} took:{:.2f}".format(mark, pa, ll, (dt.now() - start).total_seconds()))

        if self.light_sensor.save_images:
            self.apply_overlays(pil_image, mark)
            self.save_image(pil_image, image_filename)

    def capture(self) -> Image:
        """ Capture sensor buffer to an in-memory stream"""
        stream = BytesIO()
        self._camera.capture(stream, format='jpeg')
        # "Rewind" the stream to the beginning so we can read its content
        stream.seek(0)
        return Image.open(stream)

    def apply_overlays(self, im: Image, mark):
        """ Add dates, spinny, etc. Inplace."""
        pxavg = image_pixel_average(im)
        bg_colour = (128,128,128, 128)
        if pxavg > 0.5:
            text_colour = (0, 0, 0)
        else:
            text_colour = (255, 255, 255)
        width, height = im.size
        draw = ImageDraw.Draw(im)

        try:
            if 'settings' in self.overlays:
                # Draw the picam's settings
                text = pformat(get_picam(self._camera))
                text += "\n\npixel_average = {pxavg:.3f}"
                text_size = 10
                font = ImageFont.truetype(FONT_FILE, text_size, encoding='unic')
                text_box_size = draw.textsize(text=text, font=font)
                # left top corner
                draw.text(
                    xy=(0, 0), text=text, fill=text_colour, font=font)
                # centre text
            if 'simple_settings' in self.overlays:
                # Draw some of picam's settings
                picam = get_picam(self._camera)
                text = f"level={self.light_sensor._current_level} avg={pxavg:.3f}"
                text += f" es {picam['exposure_speed']/1000000:.3f} iso={picam['iso']} exp={picam['exposure_mode']}"
                text_size = 10
                font = ImageFont.truetype(FONT_FILE, text_size, encoding='unic')
                tw, th = draw.textsize(text=text, font=font)
                # RHS
                x = width - tw                 
                # one line above bottom
                y = height - th * 2
                #draw.rectangle(xy=(x, y, x + tw, y + th), fill=bg_colour)
                draw.text(xy=(x, y), text=text, fill=text_colour, font=font)
            if 'spinny' in self.overlays:
                # Draw a small circle with a minute hand, for continuity checking. Plus it looks cool.

                dia = 30
                # 1px off corner x    y              x
                bounding_box = [(1, height - dia), (dia, height - 1)]
                # minute hand
                draw.pieslice(bounding_box, mark.minute / 60 * 360 - 90,
                              mark.minute / 60 * 360 - 90, fill=None, outline=text_colour)
                draw.arc(bounding_box, 0, 360, fill=text_colour)
            if 'image_name' in self.overlays:
                text = os.path.basename(self.dt2basename(mark))
                text_size = 10
                font = ImageFont.truetype(FONT_FILE, text_size, encoding='unic')
                # Get the size of the time to write, so we can correctly place it
                text_box_size = draw.textsize(text=text, font=font)
                # centre text
                x = int((width / 2) - (text_box_size[0] / 2))
                # place one line above bottom
                y = (height - text_box_size[1] * 2)
                draw.text(xy=(x, y), text=text,
                          fill=text_colour, font=font)
        except Exception as exc:
            LOGGER.warning(f"Exception adding overlays: {exc}")
            LOGGER.debug(f"Exception adding overlays: {exc}", exc_info=exc)

    def dt2dir(self, mark: datetime):
        """ Return current directory for image saves eg. ./cam1/2000-11-01/"""
        if self.file_by_date:
            folder_naming_format = "%Y-%m-%d"
            subfolder = mark.strftime(folder_naming_format)
            return os.path.join(self.file_root, subfolder)
        else:
            return self.file_root

    def dt2filename(self, mark: datetime):
        """ Full filename(including dir) eg. ./cam1/2000-11-01/2000-11-01T00-12-00.jpg"""
        return join(self.dt2dir(mark), self.dt2basename(mark))

    def dt2basename(self, mark: datetime, image_ext=".jpg"):
        """ Name of the saved file. "basename" as per os.path.basename"""
        # eg. 2000-11-01T00-12-00.jpg
        image_naming_format = "%Y-%m-%dT%H-%M-%S"
        return mark.strftime(image_naming_format) + image_ext

    def camera_inactive_until(self, wakeup):
        """
        Camera inactive, so undertake requested action(sleep, etc)
        Arguments:
            dt {datetime} - - When to wakeup.
        """
        if self.camera_inactive_action == CameraInactiveAction.EXCEPTION:
            raise PowerOff("Camera inactive. Wake at {}".format(wakeup))
        elif self.camera_inactive_action == CameraInactiveAction.POWER_OFF:
            # Turn off power and wakeup later
            if self._pijuice is not None:
                # pass wakeup as a (local) time
                self._pijuice.wakeup_enable(wakeup)
                self._pijuice.power_off()
            else:
                raise PiJuiceError("No pijuice available")
        elif self.camera_inactive_action == CameraInactiveAction.WAIT:
            LOGGER.info(
                "Camera inactive. Waiting until {}".format(wakeup))
            sleep_until(wakeup, dt.now())
        elif self.camera_inactive_action == CameraInactiveAction.EXIT:
            LOGGER.info(
                "Camera inactive. Exiting. Wake at {}".format(wakeup))
            sys.exit(4)
        else:
            raise RuntimeError


class FakePiCamera():
    """ Returns plain jane images via software and time-of-day"""

    def __init__(self):
        self.lum = 0

    def close(self):
        pass

    # pylint: disable=redefined-builtin
    # must copy definition of picamera with 'format' keyword
    def capture(self, stream=None, format="jpeg", filename=None, quality=80):
        """
        norm distro around noon
        (5, 0.001) , (10, 0.48),  (12, 0.79)
        """
        h = dt.now().hour + dt.now().minute / 60 + dt.now().second / 3600
        _sigma = 2
        _mu = 12
        # Probability density function.  P(x <= X < x+dx) / dx
        variance = _sigma ** 2.0
        pdf = exp((h - _mu)**2.0 / (-2.0 * variance)) / sqrt(tau * variance)
        self.lum = int(255.0 * pdf * 5)

        im = Image.new("RGB", (400, 300), (self.lum, self.lum, self.lum))
        if filename is None:
            im.save(stream, format, quality=quality)
            return im
        else:
            im.save(filename)
            return im


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


def camera_console(cl_args=sys.argv[1:]):
    # pylint: disable=broad-except
    retval = 0
    signal(SIGINT, sig_handler)
    signal(SIGTERM, sig_handler)
    parser = argparse.ArgumentParser("TMV Camera.")
    parser.add_argument('--log-level', '-ll', default='WARNING', type=lambda s: LOG_LEVELS(s).name, nargs='?', choices=LOG_LEVELS.choices())
    parser.add_argument('--config-file', default="./camera.toml",
                        help="Config file is required. It will be created if non-existant.")
    parser.add_argument('--fake', action='store_true')
    parser.add_argument('--runs', type=int, default=sys.maxsize)

    args = (parser.parse_args(cl_args))

    logging.getLogger("tmv.camera").setLevel(args.log_level)
    logging.basicConfig(format=LOG_FORMAT, level=args.log_level)

    LOGGER.info(f"Starting camera app. config-file: {Path(args.config_file).absolute()} ")

    cam = Camera()

    try:

        if args.fake:
            LOGGER.warning("Using a fake camera")
            # pylint: disable=protected-access
            cam._camera = FakePiCamera()

        if not Path(args.config_file).is_file():
            shutil.copy(resource_filename(
                __name__, 'resources/camera.toml'), args.config_file)
            LOGGER.info(
                "Writing default config file to {}.".format(args.config_file))

        cam.config(args.config_file)

        # Read soft/hard buttons and override to ON/OFF if required
        # or otherwise do nothing for AUTIO
        sws = Switches()
        sws.config(args.config_file)
        camera_switch = sws['camera']
        LOGGER.info(f"Setting Camera switch to: {camera_switch}")
        # logger.debug(f"switches={sws}")
        if camera_switch == ON:
            cam.manual_override(True)
        elif camera_switch == OFF:
            cam.manual_override(False)
        elif camera_switch == AUTO:
            pass

        cam.run(args.runs)

    except SignalException:
        LOGGER.info('SIGTERM, SIGINT or CTRL-C detected. Exiting gracefully.')
        retval = 0
    except toml.decoder.TomlDecodeError as e:
        retval = 1
        LOGGER.error("Error in {}:{} ".format(args.config_file, e))
        LOGGER.debug(e, exc_info=e)

    except BaseException as e:
        retval = 1
        LOGGER.error(e)
        LOGGER.debug(e, exc_info=e)
    finally:
        # probably can remove?
        if cam._camera is not None:
            cam._camera.close()

    sys.exit(retval)
