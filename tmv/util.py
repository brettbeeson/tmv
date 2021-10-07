
# pylint: disable=line-too-long, logging-fstring-interpolation, dangerous-default-value, logging-not-lazy

from re import search, sub
from pathlib import Path
from collections import Counter
import time  # not "from" to allow monkeypatch
from shutil import copyfile
import datetime
from datetime import datetime as dt, timezone, timedelta, date
from subprocess import CalledProcessError, PIPE, run
import argparse
import logging
import os
from sys import stderr
import glob
import shutil
import socket
import unicodedata
import subprocess
from enum import Enum
from pkg_resources import resource_filename
import toml
import pytimeparse
from functools import lru_cache, wraps
from time import monotonic

from tmv.config import SLOW, MEDIUM, FAST


class LOG_LEVELS(Enum):
    """ Convenience for argparse / logging modules """
    DEBUG = 'DEBUG'
    INFO = 'INFO'
    WARNING = 'WARNING'
    ERROR = 'ERROR'
    CRITICAL = 'CRITICAL'

    @staticmethod
    def choices():
        return [l.name for l in list(LOG_LEVELS)]


LOG_LEVEL_STRINGS = ['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG']

LOGGER = logging.getLogger("tmv.util")

LOG_FORMAT = '%(levelname)-8s %(filename)-8s: %(message)s'
LOG_FORMAT_DETAILED = '%(levelname)-8s pid %(process)s in %(filename)s,%(lineno)d (%(funcName)s): %(message)s'
# Log time:
#LOG_FORMAT = '%(asctime)s ' + LOG_FORMAT
#LOG_FORMAT_DETAILED = '%(asctime)s ' + LOG_FORMAT_DETAILED


# Like RFC3339 but replace ':' with '-' to not wreck filenames
DATETIME_FORMAT = "%Y-%m-%dT%H-%M-%S"
DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT = "%H:%M:%S"


class Tomlable:
    """
    Convenience class for configuring classes via Toml
    """

    def __init__(self):
        self.config_path = None  # if available, where the instance was config'd

    def configs(self, config_string):
        config_dict = toml.loads(config_string)
        self.configd(config_dict)

    def config(self, config_pathname):
        try:
            config_dict = toml.load(str(config_pathname))
            self.configd(config_dict)
            self.config_path = Path(config_pathname)
        except Exception as ex:
            LOGGER.warning(f"error reading config file: {config_pathname}")
            raise ex

    def configd(self, config_dict):
        raise NotImplementedError

    def setattr_from_dict(self, attr_name: str, new_attrs: dict, default_value=None):
        """ If attr_name exists in self, set it to new_attrs[name_of_attr]
            Note that attr_names are made safe. For example, "this-name" is changed to "this_name"
            default_value: if specified, use this if not in dict; otherwise do nothing (see dict.getattr())
            """
        try:
            # throws if doesn't exist in new attrs
            attr_value = new_attrs[attr_name]
            safe_attr_name = attr_name.replace("-", "_")
            setattr(self, safe_attr_name, attr_value)
        except AttributeError:      # doesn't exist in self: ignore with warning
            LOGGER.warning("Ignoring unknown setting: '{}'".format(attr_name))
        except KeyError:            # doesn't exist in new attrs
            if default_value:
                setattr(self, attr_name, default_value)


def log_level_string_to_int(log_level_string):

    if log_level_string not in LOG_LEVEL_STRINGS:
        message = 'invalid choice: {0} (choose from {1})'.format(
            log_level_string, LOG_LEVEL_STRINGS)
        raise argparse.ArgumentTypeError(message)

    log_level_int = getattr(logging, log_level_string, logging.INFO)
    # check the logging log_level_choices have not changed from our expected
    # values
    assert isinstance(log_level_int, int)

    return log_level_int

def timed_lru_cache(
    _func=None, *, seconds: int = 600, maxsize: int = 128, typed: bool = False
):
    """Extension of functools lru_cache with a timeout
        
    Parameters:
    seconds (int): Timeout in seconds to clear the WHOLE cache, default = 10 minutes
    maxsize (int): Maximum Size of the Cache
    typed (bool): Same value of different type will be a different entry
    Source: https://gist.github.com/Morreski/c1d08a3afa4040815eafd3891e16b945
    """

    def wrapper_cache(f):
        f = lru_cache(maxsize=maxsize, typed=typed)(f)
        f.delta = seconds
        f.expiration = monotonic() + f.delta

        @wraps(f)
        def wrapped_f(*args, **kwargs):
            if monotonic() >= f.expiration:
                f.cache_clear()
                f.expiration = monotonic() + f.delta
            return f(*args, **kwargs)

        wrapped_f.cache_info = f.cache_info
        wrapped_f.cache_clear = f.cache_clear
        return wrapped_f

    # To allow decorator to be used without arguments
    if _func is None:
        return wrapper_cache
    else:
        return wrapper_cache(_func)



def td2str(td):
    """ Return a str from a timedelta, in iso-ish style. """
    if isinstance(td, timedelta):
        return td.strftime(TIME_FORMAT)
    else:
        raise TypeError


def dt2str(d):
    """ Return a str from a datetime or date, in RFC3399-ish style (YYYY-MM-DDTHH-MM-SS or YYYY-MM-DD). Timezones ignored. """
    if isinstance(d, dt):
        return d.strftime(DATETIME_FORMAT)
    elif isinstance(d, date):
        return d.strftime(DATE_FORMAT)
    else:
        raise TypeError


def dt2iso(d):
    """ https://stackoverflow.com/questions/8556398/generate-rfc-3339-timestamp-in-python
    eg '2015-01-16T16:52:58.547366+01:00'
    """
    local_time = d(timezone.utc).astimezone()
    return local_time.isoformat()


def str2dt(filename: str, throw=True) -> dt:
    """Returns the datetime of string.
       Uses first 14 digits = 4,2,2,2,2,2 and ignores non-digits.
       Expects RFC3399 order of %Y%m%d%H%M%S
       If no time is given, 00:00:00 is returned as the datetime's time.
      """
    datetime_pattern = '%Y%m%d%H%M%S'
    datetime_length = 14
    date_pattern = "%Y%m%d"
    date_length = 8
    datetime_digits = ''
    date_digits = ''

    for c in os.path.basename(filename):
        if c.isdigit():
            datetime_digits = datetime_digits + c
    datetime_digits = datetime_digits[0:datetime_length]
    date_digits = datetime_digits[0:date_length]
    try:
        file_datetime = dt.strptime(datetime_digits, datetime_pattern)
        return file_datetime
    except ValueError:
        try:
            # LOGGER.warning(e)
            file_date_only = dt.strptime(date_digits, date_pattern)
            return file_date_only
        except ValueError:
            if throw:
                raise
            return None


def today_at(hours, minutes=0, seconds=0):
    return dt.combine(dt.today(), datetime.time(hours, minutes, seconds))


def tomorrow_at(hours, minutes=0, seconds=0):
    return dt.combine(dt.today(), datetime.time(hours, minutes, seconds)) + timedelta(days=1)


def penultimate_unique(l):
    rl = list(reversed(l))
    try:
        return next(i for i in rl if i != rl[0])
    except StopIteration:
        return None


def list_of_dates(start: datetime, end: datetime):
    dates = []
    delta = end - start
    for i in range(delta.days + 1):
        day = start + timedelta(days=i)
        dates.append(day.date())
    return dates


def unlink_safe(f):
    # pylint: disable=broad-except
    try:
        if f is not None:
            os.unlink(str(f))
        return True
    except BaseException:
        return False


def file_by_day(file_list, dest, move):
    """ Given a list of files, move/copy then to YYYY-MM-DD/ directories in the cwd, based on the timestamp of file_list elements"""
    n_errors = 0
    n_moved = 0
    LOGGER.debug("Reading dates of {} files...".format(len(file_list)))
    for fn in file_list:
        try:
            fn = str(fn)  # handle Path
            try:
                # Filename date
                datetime_taken = str2dt(fn)
            except ValueError as e:
                # Try to get EXIF
                raise NotImplementedError("No exif library availble") from e
                #datetime_taken = exif_datetime_taken(fn)
            # got a date. Move it
            n_moved += 1
            folder_name = os.path.join(dest, str(datetime_taken.date()))
            move_to = os.path.join(folder_name, os.path.basename(fn))
            if not os.path.exists(folder_name):
                os.mkdir(folder_name)
            LOGGER.debug("Copying {} to {}".format(fn, folder_name))
            copyfile(fn, move_to)

            if move:
                LOGGER.debug("Deleting {}".format(fn))
                os.unlink(fn)
        # pylint: disable=broad-except
        except Exception as exc:
            n_errors += 1
            LOGGER.warning("Error getting date for %s: %s" % (fn, exc))

    LOGGER.debug("Got {} dated file from {} files with {} errors".format(
        n_moved, len(file_list), n_errors))
    if n_errors:
        LOGGER.warning(
            "No dates available for {}/{}. Ignoring them.".format(n_errors, len(file_list)))


def files_from_glob(file_glob: list):
    """
        Return a list of files from a list of globs
        e.g files_from_glob(([*.jpg,*.JPG"]) = ["1.jpg","2.jpg","3.JPG"]
    """
    assert isinstance(file_glob, list)
    file_list = []
    for fg in file_glob:
        file_list.extend(glob.glob(fg))
    # LOGGER.info("Globbed %d files" % (len(file_list)))
    return file_list


def magic_filename():
    home_files = [f for f in os.listdir(Path.home()) if f[0] != "."]
    home_files.sort()
    return home_files[0]


def setattrs_from_dict(o, settings):
    """ Given a dictionary of settings, set object's attributes, where they
        exist """
    for k, v in settings.items():
        try:
            getattr(o, k)           # throw if doesn't exist
            setattr(o, k, v)
        except AttributeError:      # doesn't exist in object: ignore
            LOGGER.warning("Ignoring unknown setting {}:{}".format(k, v))
        # except Exception as e:  # find "missing item attribute"
        #    LOGGER.warning("Could not set {}:{}. Exception: {}".format(k, v, e))


def not_modified_for(file, period):
    """
    Return only when the file hasn't be modified for 'period'
    """
    last_mod = dt.now()

    while dt.now() - last_mod < period:
        time.sleep(0.1)
        try:
            stats = Path(file).stat()
        except FileNotFoundError:
            # oh no, must of been deleted
            return
        last_mod = dt.fromtimestamp(stats.st_mtime)
    # LOGGER.debug("Waited for {:.1f}s".format(
    #    (dt.now()-start).total_seconds()))
    return


def check_internet(host="8.8.8.8", port=53, timeout=5):
    """
    Host: 8.8.8.8 (google-public-dns-a.google.com)
    OpenPort: 53/tcp
    Service: domain (DNS/TCP)
    """
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except socket.error as exc:
        LOGGER.debug(exc)
        return False


def run_and_capture(cl: list, log_filename=None, timeout=None):
    """
    Only for python <=3.6. Use "capture" keyword for >3.6
    cl: list of parameters, or str (will be split on " "; quotes are respected
    log_filename: on process error (i.e. runs but fails), log it's output.
    """
    if isinstance(cl, str):
        cl = cl.split(" ")  # shlex
    try:
        proc = run(cl, encoding="UTF-8", stdout=PIPE, stderr=PIPE, check=False, timeout=timeout)
    except OSError as e:
        raise OSError("Subprocess failed to even run") from e

    if proc.returncode != 0:
        if log_filename:
            Path(log_filename).write_text(f"*** command ***\n{cl}\n{' '.join(cl)}\n*** returned ***\n{proc.returncode}\n" +
                                          f"*** stdout ***\n{proc.stdout}\n*** stderr ***\n{proc.stderr}\n")
        raise CalledProcessError(proc.returncode, cl, proc.stdout, proc.stderr)

    return str(proc.stdout), str(proc.stderr)


def cpe2str(cpe):
    return f"Subprocess ran but failed. command: '{' '.join(cpe.cmd)}' return: {cpe.returncode} stdout: {cpe.stdout} stderr: {cpe.stderr}"


def subprocess_stdout(cl):
    """
      Only for python <=3.6. Use "capture" keyword for >3.6
      Throws OSError or CalledProcessError
    """
    if isinstance(cl, str):
        cl = cl.split(" ")
    try:
        proc = run(cl, encoding="UTF-8", stdout=PIPE, stderr=PIPE, check=True)
    except OSError as e:
        raise OSError("Subprocess failed to run") from e

    return str(proc.stdout)


def add_stem_suffix(p: Path, s: str) -> Path:
    """ eg. ("/path/to/file.ext","-suffix") -> ("/path/to/file-suffix.ext")"""
    return p.parent / Path(p.stem + s + p.suffix)


def slugify(value, allow_unicode=False):
    """
    from: https://github.com/django/django/blob/master/django/utils/text.py
    Convert to ASCII if 'allow_unicode' is False. Convert spaces to hyphens.
    Remove characters that aren't alphanumerics, underscores, or hyphens.
    Convert to lowercase. Also strip leading and trailing whitespace.
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize('NFKC', value)
    else:
        value = unicodedata.normalize('NFKD', value).encode(
            'ascii', 'ignore').decode('ascii')
    value = sub(r'[^\w\s-]', '', value.lower()).strip()
    return sub(r'[-\s]+', '-', value)


def next_mark(delta: timedelta, instant):
    """
    Return the next mark. For example instant = 11:00:01, delta = 5, returns 11:00:05
    """
    assert timedelta(days=1) >= delta >= timedelta(
        seconds=1)  # rounding may break
    round_to = delta.total_seconds()
    seconds = (instant - dt.min).seconds
    rounded_seconds = (seconds) // round_to * \
        round_to  # // is a floor division
    rounded_time = instant + \
        timedelta(0, rounded_seconds - seconds, -instant.microsecond)
    if rounded_time == instant:
        return rounded_time
    else:
        return rounded_time + delta
    # return instant + timedelta(0, rounded_seconds - seconds + round_to, -instant.microsecond)


def sleep_until(mark: dt, instant: dt):
    delta = mark - instant
    if delta.total_seconds() > 0:
        # logger.debug("Sleep for {:.1f}s".format(delta.total_seconds()))
        time.sleep(delta.total_seconds())


def service_details(service):
    """
    Return systemd service detail
        active
        inactive
        activating
        deactivating
        failed
        not-found
        dead
    """
    # stderr ignored; return can be non-zero
    p = run(["systemctl", "status", service], encoding='UTF-8', capture_output=True, check=False)
    output = p.stdout
    service_regx = r"Loaded:.*\/(.*service);"
    status_regx = r"Active:(.*) since (.*);(.*)"
    deets = {}
    for line in output.splitlines():
        service_search = search(service_regx, line)
        status_search = search(status_regx, line)

        if service_search:
            deets['service'] = service_search.group(1)
        elif status_search:
            deets['status'] = status_search.group(1).strip()
            deets['since'] = status_search.group(2).strip()
            deets['uptime'] = status_search.group(3).strip()

    return deets


def strptimedelta(s: str):
    return timedelta(seconds=pytimeparse.parse(s))


def prev_mark(delta: timedelta, instant):
    """
    Return the previous mark. For example instant = 11:00:01, delta = 5, returns 11:00:00
    """
    assert timedelta(days=1) >= delta >= timedelta(seconds=1)  # rounding may break
    round_to = delta.total_seconds()
    seconds = (instant - dt.min).seconds
    rounded_seconds = (seconds) // round_to * round_to  # // is a floor division
    rounded_time = instant + timedelta(0, rounded_seconds - seconds, -instant.microsecond)
    if rounded_time == instant:
        return rounded_time
    else:
        return rounded_time - delta


def neighborhood(iterable):
    iterator = iter(iterable)
    prev = None
    item = next(iterator)  # throws StopIteration if empty.
    for nextone in iterator:
        yield (prev, item, nextone)
        prev = item
        item = nextone
    yield (prev, item, None)


def ensure_config_exists(config_file):
    """
    Make config_file if it doesn't exist.
    """
    try:
        cf = Path(config_file)
        if not cf.is_file():
            raise FileNotFoundError("Found {cf} but not it is not a file")
    except FileNotFoundError:
        default_config_path = Path(resource_filename(__name__, 'resources/camera.toml'))
        LOGGER.info("Writing default config file to {} (from {})".format(config_file, default_config_path.absolute()))
        Path(config_file).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(default_config_path, config_file)


def file_by_day_console():
    parser = argparse.ArgumentParser("File files into dated subfolders")
    parser.add_argument("file_glob", nargs='+')
    parser.add_argument('--log-level', default='WARNING', dest='log_level', type=log_level_string_to_int, nargs='?',
                        help='Set the logging output level. {0}'.format(LOG_LEVEL_STRINGS))
    parser.add_argument("--dryrun", action='store_true', default=False)
    parser.add_argument("--move", action='store_true', default=False,
                        help="After successful copy, delete the original")
    parser.add_argument("--dest", default='.',
                        help="root folder to store filed files(!)")

    args = parser.parse_args()
    LOGGER.setLevel(args.log_level)
    logging.basicConfig(format='%(levelname)s:%(message)s')

    file_list = files_from_glob(args.file_glob)
    if not os.path.exists(args.dest):
        os.mkdir(args.dest)
    file_by_day(file_list, args.dest, args.move)

@timed_lru_cache(seconds=60, maxsize=10)
def wifi_ssid():
    """ Use iwgetid to get ssid in typical form: 'wlan0     ESSID:"NetComm 0405"\n'"""
    try:
        p = subprocess.run(['sudo', 'iwgetid'], check=True, encoding="UTF-8", capture_output=True)
        if p.stdout:
            return p.stdout.split('"')[1]
        else:
            return None
    except (CalledProcessError, TypeError) as e:
        LOGGER.warning(e)
        return None


def ap_clients(interface='ap0'):
    """ Return a list of mac addresses. Only on pi-ish. """
    try:
        p = run(["iw", "dev", interface, "station", "dump"], encoding="UTF-8", check=True, capture_output=True)
        stations = list(Counter([line for line in p.stdout if "Station" in line]).elements())
        LOGGER.debug(stations)
        return stations
    except CalledProcessError as e:
        LOGGER.warning(e)
        return []


def strike(text):
    result = ''
    for c in text:
        result = result + c + '\u0336'
    return result


def stats_console():
    from tmv.tmvpijuice import TMVPiJuice, pj_call  # pylint: disable=import-outside-toplevel
    from tmv.exceptions import PiJuiceError         # pylint: disable=import-outside-toplevel
    from statistics import mean                     # pylint: disable=import-outside-toplevel

    p = TMVPiJuice()


    parser = argparse.ArgumentParser("Interrogate TMV for battery level, etc and print as CSV")
    parser.add_argument("--interval","-i", type=int, default=10, help="Reading interval in seconds")
    parser.add_argument("--readings","-n", type=int, default=6, help="Readings to average")
    args = parser.parse_args()
    interval = timedelta(seconds=args.interval)

    io_current = []
    batt_current = []
    charge = []
    #print ("datetime,io_current,batt_current,charge")

    for _ in range(args.readings):
        mark = next_mark(interval, dt.now())
        sleep_until(mark, dt.now())
        io_current.append(pj_call(p.status.GetIoCurrent))
        batt_current.append(pj_call(p.status.GetBatteryCurrent))
        charge.append(pj_call(p.status.GetChargeLevel))

    try:
        print (f"{dt2str(mark)},{int(mean(io_current))},{int(mean(batt_current))},{int(mean(charge))}")
    except PiJuiceError as e:
        print(e, file=stderr)


def interval_speeded(interval, speed):
    # Factor between intervals wrt speeds
    SPEED_MULTIPLIER = 10

    if speed.value == SLOW:
        return interval * SPEED_MULTIPLIER
    if speed.value == MEDIUM:
        return interval
    if speed.value == FAST:
        return interval / SPEED_MULTIPLIER
    raise RuntimeError("Logic error on speed and intervals")



@timed_lru_cache(seconds=10, maxsize=10)
def uptime():  
    with open('/proc/uptime', 'r') as f:
        uptime_seconds = float(f.readline().split()[0])
        return uptime_seconds