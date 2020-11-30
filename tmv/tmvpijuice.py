from time import sleep
import argparse
from enum import Enum
import logging
from os import system
from datetime import datetime as dt, timedelta, time

from dateutil.tz import tzutc
try:
    from pijuice import PiJuice
except Exception as e:
    print (e)
from tmv.exceptions import PiJuiceError


LOGGER = logging.getLogger("tmv.pijuiceutil")


class Blink(Enum):
    """ What blink type? """
    UPLOAD = 'UPLOAD' #  1 blink, green is good, red is bad
    WIFI = 'WIFI'     #  steady


def pj_check(pyjuice_response, raise_errors):
    """ Raise an error if response has errors"""
    if pyjuice_response['error'] != 'NO_ERROR':
        if raise_errors:
            raise PiJuiceError("pijuice failed with code: {}".format(
                pyjuice_response['error']))
        else:
            LOGGER.error(f"pijuice failed with code: {pyjuice_response['error']}")


def pj_call(method):
    """ Try a few times to call method and retrieve ['data'] from the dict, or raise an error """
    for _ in range(0, 10):
        r = method()
        if r['error'] == 'NO_ERROR':
            return r['data']
        time.sleep(.1)
    if 'error' in r:
        raise PiJuiceError(f"pijuice failed with code: {r['error']}")
    else:
        raise PiJuiceError("pijuice failed without an error code.")

try:
    class TMVPiJuice(PiJuice):
        """ Extend PiJuice functionality for TMV Camera use """

        def __init__(self, led='D2', lum=64, raise_errors = False):
            self.led = led
            self.lum = lum
            self.raise_errors = raise_errors
            super().__init__()
            self.last_blink_end = dt.min

        def power_off(self):
            LOGGER.warning("Shutting down now and powering off PiJuice in 60s")
            # give some time to abort - TODO make a nice way
            sleep(60)
            pj_check(self.power.SetPowerOff(60), self.raise_errors)
            system("sudo shutdown now")
            sleep(70)
            raise PiJuiceError("Should have powered off by now!")

        def wakeup_enable(self, wakeup):
            """ Take a (local tz) time and datetime and enable wake then.
                This requires converting to UTC to sent to PiJuice
                Call power_off afterwards
                """
            if isinstance(wakeup, time):
                wakeup_time = wakeup
            elif isinstance(wakeup, dt):
                wakeup_time = wakeup.astimezone().time()    # convert to local timezone
            else:
                raise TypeError(
                    "Expected time or datetime but got {}".format(type(wakeup)))
            local_datetime_today = dt.combine(dt.now().date(), wakeup_time)
            utc_time = local_datetime_today.astimezone(tzutc()).time()
            # dick needs a dict
            wake_time_dict = {'second': utc_time.second,
                            'minute': utc_time.minute,
                            'hour': utc_time.hour,
                            'day': "EVERY_DAY"}
            pj_check(self.rtcAlarm.SetWakeupEnabled(True),self.raise_errors)
            pj_check(self.rtcAlarm.SetAlarm(wake_time_dict),self.raise_errors)
            LOGGER.info("Set wake at UTC: {} local:{}".format(
                utc_time, wakeup_time))
            LOGGER.info("Check alarm_wakeup_enabled: {} alarm get_time: {}".format(
                pj_call(self.rtcAlarm.GetControlStatus)['alarm_wakeup_enabled'],
                pj_call(self.rtcAlarm.GetAlarm)))
            return utc_time

        def wakeup_disable(self):
            self.pj_check(self.rtcAlarm.SetWakeupEnabled(False),self.raise_errors)

        def blink(self, blink_type: Blink, status: bool):
            #GAP_AFTER_END = timedelta(seconds=1)
            #if (dt.now() < self.last_blink_end + GAP_AFTER_END):
            #   # print("Come back later!")
            #  return False

            if blink_type == Blink.UPLOAD and status:
                rgb1 = [0, self.lum, 0]
                period1 = 250
                rgb2 = [0, 0, 0]
                period2 = 0
                count = 1
            elif blink_type == Blink.UPLOAD and not status:
                rgb1 = [self.lum, 0, 0]
                period1 = 250
                rgb2 = [0, 0, 0]
                period2 = 0
                count = 1
            elif blink_type == Blink.WIFI and status:
                rgb1 = [0, 1, 0]
                period1 = 500
                rgb2 = [0, 2, 0]
                period2 = 500
                count = 5
            elif blink_type == Blink.WIFI and not status:
                rgb1 = [1, 0, 0]
                period1 = 500
                rgb2 = [2, 0, 0]
                period2 = 500
                count = 5
            else:
                raise RuntimeError("Internal error")

            # Will take period1 + period2 to finish, but returns immediately
            # So, mulitple fast calls would drop blinks / get confused
            # Hence we ignore future calls until 1s after this blink is finished
            self.status.SetLedBlink(self.led, count, rgb1, period1, rgb2, period2)
            self.last_blink_end = dt.now() + timedelta(
                milliseconds=count * (period1 + period2))
            return True
except NameError as e:
    print(e)


def blink_console():
    argparser = argparse.ArgumentParser("Blink the user LED on a pijuice")
    argparser.add_argument("blinktype", choices=['photo', 'upload', 'wifi'])
    argparser.add_argument("status", choices=['true', 'false'])
    argparser.add_argument("-n", type=int, default=1, help="Repeat n times")
    args = argparser.parse_args()
    pj = TMVPiJuice()
    for _ in range(0, args.n):
        pj.blink(Blink(args.blinktype.upper()), args.status.lower() == 'true')
        if args.n > 1:
            sleep(1)
