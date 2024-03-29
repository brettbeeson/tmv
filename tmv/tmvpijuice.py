# pylint: disable=logging-fstring-interpolation, logging-not-lazy
from time import sleep
import logging
from os import system

from datetime import time, datetime as dt  # class
from dateutil.tz import tzutc
from pijuice import PiJuice  # pylint: disable=import-error

from tmv.exceptions import PiJuiceError
from tmv.util import timed_lru_cache

LOGGER = logging.getLogger("tmv.tmvpijuice")


@timed_lru_cache(seconds=60, maxsize=10)
def pj_status():
    p = TMVPiJuice()
    return pj_call(p.status.GetStatus)

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
        sleep(.1)
    if 'error' in r:
        raise PiJuiceError(f"pijuice failed with code: {r['error']}")
    else:
        raise PiJuiceError("pijuice failed without an error code.")


class TMVPiJuice(PiJuice):  # NameError
    """ Extend PiJuice functionality for TMV Camera use """

    def __init__(self, led='D2', lum=64, raise_errors=False):
        self.led = led
        self.lum = lum
        self.raise_errors = raise_errors
        super().__init__()

    def power_off(self):
        LOGGER.warning("Shutting down now and powering off PiJuice in 60s")
        pj_check(self.power.SetPowerOff(60), self.raise_errors)  # 60s for shutdown
        system("sudo shutdown now")
        sleep(60)
        raise PiJuiceError("Should have powered off by now!")

    def wakeup_enable(self, wakeup):
        """ Take a (local tz) time and datetime and enable wake then.
            This requires converting to UTC to sent to PiJuice
            Call power_off afterwards
            """
        LOGGER.debug(f"wakeup_enable called with {wakeup}")
        if isinstance(wakeup, time):
            wakeup_time = wakeup
        elif isinstance(wakeup, dt):
            wakeup_time = wakeup.astimezone().time()    # convert to local timezone
        else:
            raise TypeError(f"Expected time or datetime but got {type(wakeup)}")
        local_datetime_today = dt.combine(dt.now().date(), wakeup_time)
        utc_time = local_datetime_today.astimezone(tzutc()).time()
        # dick needs a dict
        wake_time_dict = {'second': utc_time.second,
                          'minute': utc_time.minute,
                          'hour': utc_time.hour,
                          'day': "EVERY_DAY"}
        pj_check(self.rtcAlarm.SetWakeupEnabled(True), self.raise_errors)
        pj_check(self.rtcAlarm.SetAlarm(wake_time_dict), self.raise_errors)
        LOGGER.info("Set wake at UTC: {} local:{}".format(
            utc_time, wakeup_time))
        LOGGER.info("Check alarm_wakeup_enabled: {} alarm get_time: {}".format(
            pj_call(self.rtcAlarm.GetControlStatus)['alarm_wakeup_enabled'],
            pj_call(self.rtcAlarm.GetAlarm)))
        return utc_time

    def wakeup_disable(self):
        pj_check(self.rtcAlarm.SetWakeupEnabled(False), self.raise_errors)
