# pylint: disable=line-too-long, logging-fstring-interpolation, dangerous-default-value, logging-not-lazy

import logging
from pprint import pformat
import sys
from sys import argv
import socket  # gethostname, monkeypatchable
import uuid  # getnode, monkeypatchable
import argparse
from datetime import timedelta
from signal import SIGINT, SIGTERM, signal
import shutil
from bisect import bisect_left
from urllib.parse import urlparse
from pathlib import Path
from time import sleep

from pkg_resources import resource_filename
import boto3
from botocore.exceptions import ClientError
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from tmv.util import log_level_string_to_int, LOG_LEVEL_STRINGS, Tomlable, not_modified_for, check_internet
from tmv.camera import ConfigError, SignalException
try:
    from tmv.pijuice import Blink, TMVPiJuice
except ImportError as exc:
    print(exc)


LOGGER = logging.getLogger(__name__)


class S3Uploader(FileSystemEventHandler, Tomlable):
    """
    Upload local files to s3
    - Set the destination root (e.g. s3://bucket/root)
    - Upload directories (e.g /any/uploadme/ which has file1 and dir1/file2)
    - Ends up at s3 (e.g. s3://bucket/root/file1)
    - Ends up at s3 (e.g. s3://bucket/root/dir1/file2)
    - watches file system for new files to upload
    - config via toml
    """
    # There is a watchdog for new files, and a backlog mechanism
    # Perhaps a simple "upload any files you see" would be better
    # It would have the disadvantage of requiring a *move* and
    # But the 'backlog' state and watchdog could be removed: just poll and
    # upload!
    # 1. Could split the class  to have "EventUploader" and "PollingUploader"
    # 2. or on_create sets a thread-flag or simple flag or wakeup
    #    and daemon() polls AND wakes up on on_create and does a full
    #    upload every time. do this. if necessary "copy" could be done
    #    via a move to a local location
    #

    def __init__(self, destination=None, file_root="", profile=None, endpoint=None):
        super().__init__()
        self._ExtraArgs = {'ACL': 'public-read'}
        self._dest_bucket = None
        self._dest_root = None   # starts with "/"
        if destination:
            self.destination = destination
        self.file_root = file_root
        self.file_filter = "*.jpg"
        self.move = True  # generally want to move, otherwise every run we upload again
        self.internet_check_period = timedelta(minutes=1)
        self._s3 = None
        self.profile = profile
        self.endpoint = endpoint
        self.backlog = False  # is there a backlog of images we should upload, due to s3 or internet down, etc?
        try:
            self._pj = None
            self._pj = TMVPiJuice()
        except NameError as exc:
            LOGGER.warning(f"No PiJuice available: {exc}")
        except BaseException as exc:
            # Not TEOTWAWKI - warn and move on
            LOGGER.warning(f"No PiJuice available: {exc}")

    @property
    def s3(self):
        if not self._s3:
            session = boto3.session.Session(profile_name=self.profile)
            self._s3 = session.client(
                service_name='s3', endpoint_url=self.endpoint)
        return self._s3

    def configd(self, config_dict):
        if 'upload' in config_dict:
            config = config_dict['upload']
            self.setattr_from_dict("move", config)
            self.setattr_from_dict("extraargs", config)
            self.setattr_from_dict("file_filter", config)
            self.setattr_from_dict("profile", config)
            self.setattr_from_dict("endpoint", config)
            if "internet_check_period" in config:
                self.internet_check_period = timedelta(seconds=config['internet_check_period'])
            if "destination" in config:
                d = config['destination']
                self.destination = d.replace("HOSTNAME", socket.gethostname()).replace("UUID", str(uuid.getnode()))
            else:
                raise ConfigError("No setting found for: [upload] destination .")
            if 'log_level' in config:
                LOGGER.setLevel(config['log_level'])

        else:
            raise ConfigError("No [upload] configuration section.")
        if 'camera' in config_dict:
            config = config_dict['camera']
            # todo: should be in controller
            self.setattr_from_dict("file_root", config)

    @property
    def destination(self):
        if not self._dest_bucket:
            return None
        return "{}/{}".format(self._dest_bucket, self._dest_root)

    @destination.setter
    def destination(self, destination):
        # s3://bucket-name/folder1/folder2/
        d = urlparse(destination)
        if d.scheme != 's3':
            raise ConfigError("Can't understand destination '{}'".format(d))
        self._dest_bucket = d.netloc.strip("/")
        self._dest_root = d.path.strip("/")

    def upload(self, src_file_or_dir=None, dest_prefix=""):  # , throw=False):
        """
        Upload a file or directory to s3
        This appears(?) thread-safe but could have a mutex?
        """
        if src_file_or_dir is None:
            src_file_or_dir = self.file_root

        src_file_or_dir = Path(src_file_or_dir)

        if src_file_or_dir.is_dir():
            return self._upload_dir(src_file_or_dir, self.file_filter, self.move, dest_prefix)
        elif src_file_or_dir.is_file():
            return self._upload_file(src_file_or_dir, self.move, dest_prefix)
        else:
            raise FileNotFoundError(f"{src_file_or_dir} is not a file or dir")

    def _upload_dir(self, src_dir, file_filter="*", move=False, dest_prefix=""):
        """
        Upload all files in a folder and subfolders, retaining their folder locations
        e.g. source="/tmp/blah/dir/ uploads all files in dir to s3://bucket/root/
        Arguments:
            source -- a folder

        Keyword Arguments:
            file_filter -- upload only these files (override class default), eg. "*.jpg". Ignored if source is a file.
            dest_prefix -- add this prefix (e.g.) local_dir -> s3://bucket/root/dest_prefix/

        Returns:
            [type] -- Number of files uploaded
        """
        if not self.destination:
            raise ConfigError("No destination set for upload")
        src_dir = Path(src_dir)
        if not src_dir.is_dir():
            raise FileNotFoundError(f'{src_dir} is not a directory')

        n_uploads = 0
        dest_prefix = bare_path(dest_prefix)

        src_files = sorted(i for i in Path(src_dir).rglob(
            file_filter) if i.is_file())

        for src_file in src_files:
            src_file_rel = src_file.relative_to(src_dir)
            dest_file = self._dest_root / dest_prefix / src_file_rel
            LOGGER.info("Uploading file (from dir) {} to {}:{}".format(
                src_file, self._dest_bucket, dest_file))
            try:
                dest_file = Path(dest_file)
                self.s3.upload_file(str(src_file), Bucket=self._dest_bucket,
                                    Key=str(dest_file),
                                    ExtraArgs=self._ExtraArgs)
                if self._pj:
                    self._pj.blink(Blink.UPLOAD, True)
            except FileNotFoundError as exc:
                # when uploading a directory, a file may be moved by another process: log and continue
                LOGGER.warning(exc)
            if move:
                src_file.unlink()
            n_uploads += 1
        return n_uploads

    def _upload_file(self, src_file, move=False, dest_prefix=""):
        """
        Upload a file
        Exaqmple:
            src_file="/tmp/blah/file1 uploads to s3://bucket/root/dest_prefix/file1

        Keyword Arguments:
            dest_prefix -- add this prefix to dest

        Returns:
            True if the file was uploaded
        """
        if not self.destination:
            raise ConfigError("No destination set for upload")
        src_file = Path(src_file)
        dest_prefix = Path(dest_prefix)

        dest_file = self._dest_root / dest_prefix / src_file.name
        LOGGER.info("Uploading file {} to {} {}".format(
            src_file, self._dest_bucket, dest_file))
        self.s3.upload_file(str(src_file), Bucket=self._dest_bucket,
                            Key=str(dest_file),
                            ExtraArgs=self._ExtraArgs)
        if self._pj:
            self._pj.blink(Blink.UPLOAD, True)
        if move:
            src_file.unlink()

        return True  # otherwise would throw

    def rm_dest(self, dest_prefix: str, recursive=False, file_filter="*") -> int:
        """
        Delete files below 'dest' prefix at an s3 location (relative self.dest_folder)
        """
        n_rm = 0
        if not self.destination:
            raise ConfigError("No destination set")
        # prefixes don't have leading '/'
        dest_prefix = Path(str(dest_prefix).strip("/"))
        # safety catch
        if (self._dest_root / dest_prefix) == Path("."):
            raise ConfigError("Top-level deletes not allowed")
        # get all files at destination
        dest_files = self.list_bucket_objects(
            self._dest_bucket, str(self._dest_root / dest_prefix))
        dest_keys = [Path(obj['Key']) for obj in dest_files]
        dest_keys.sort()

        # see if they match the requested unlink
        for dest_key in dest_keys:
            rel = dest_key.relative_to(
                self._dest_root / dest_prefix)
            if len(rel.parents) == 1 or recursive:
                if dest_key.match(file_filter):
                    try:
                        self.s3.delete_object(Bucket=self._dest_bucket,
                                              Key=str(dest_key))
                        n_rm += 1
                    except ClientError as exc:
                        LOGGER.warning(exc)
        return n_rm

    def sync(self, src_dir, recursive=False, dest_prefix=""):
        return self._sync(src_dir, recursive, self.file_filter, dest_prefix)

    def _sync(self, src_dir, recursive=False, file_filter="*", dest_prefix=""):
        """
        Upload source files to dest, only if they don't exist in dest
        No elements will be deleted. No date/time checking.
        :return: N files uploaded
        """
        uploads = 0
        src_dir = Path(src_dir)
        dest_prefix = Path(dest_prefix)

        if not src_dir.is_dir():
            raise FileNotFoundError(f'{src_dir} is not a directory')
        if recursive:
            src_files = sorted(
                f for f in src_dir.rglob(file_filter) if f.is_file())
        else:
            src_files = sorted(
                f for f in src_dir.glob(file_filter) if f.is_file())
        dest_files = self.list_bucket_objects(
            self._dest_bucket, str(self._dest_root / dest_prefix))  # dest_dir_name

        # Getting the keys and ordering to perform binary search
        # each time we want to check if any paths is already there.
        dest_keys = [obj['Key'] for obj in dest_files]
        dest_keys.sort()
        dest_keys_len = len(dest_keys)

        for src_file in src_files:
            # Search for existing file in destination
            src_file_rel = src_file.relative_to(src_dir)
            dest_file = self._dest_root / dest_prefix / src_file_rel  # / dest_dir_name /
            index = bisect_left(dest_keys, str(dest_file))
            if index != dest_keys_len and dest_keys[index] == dest_file:
                # found it: ignore
                pass
            else:
                # path not found in object_keys, it has to be sync-ed.
                self.s3.upload_file(
                    str(src_file), Bucket=self._dest_bucket,
                    Key=str(dest_file), ExtraArgs=self._ExtraArgs)
                if self._pj:
                    self._pj.blink(Blink.UPLOAD, True)
                uploads += 1
        return uploads

    def daemon(self):

        if check_internet():
            LOGGER.debug("Starting daemon")
            observer = Observer()
            observer.schedule(self, self.file_root, recursive=True)
            observer.start()
            observer_active = True
        else:
            observer_active = False
        if self._pj:
            self._pj.blink(Blink.WIFI, observer_active)
        while True:
            the_internets = check_internet()
            if observer_active:
                if the_internets:
                    # all good
                    observer_active = True
                else:
                    LOGGER.debug("No internet: stopping watchdog")
                    observer.stop()
                    observer.join()
                    observer_active = False
            else:   # observer not active
                if the_internets:
                    LOGGER.debug(
                        "Internet back baby: reloading and starting watchdog")
                    self.backlog = True
                    observer = Observer()
                    observer.schedule(self, self.file_root, recursive=True)
                    observer.start()
                    observer_active = True
                else:
                    # continue to wait for internet
                    observer_active = False

            if self._pj:
                self._pj.blink(Blink.WIFI, observer_active)
            if the_internets and self.backlog:
                try:
                    n = self.upload()
                    n = + self.upload()  # pick up stragerlers which came in during the last call (post glob)!
                    self.backlog = False
                    LOGGER.debug(f"Uploaded backlog of {n} files")
                except Exception as exc:
                    LOGGER.debug(f"Failed to upload backlog: {exc}")

            sleep(self.internet_check_period.total_seconds())

    # def on_any_event(self, event):
        # LOGGER.debug(f'Ignoring event type: {event.event_type}  path : {event.src_path}')

    def on_created(self, event):
        """
        watchdog for filesystem: upload new local files to s3
        """
        # Be careful here, as files could have been change before we
        # process the event. Wait for a second of non-modification
        # to let processes finish writing.

        if self.backlog:
            # if in a backlog state, don't keep hitting head: wait for daemon() to clear it
            return

        try:
            if event.is_directory:
                return None  # Irrelevant for uploading to s3
            if Path(event.src_path).match(self.file_filter):
                not_modified_for(event.src_path, timedelta(seconds=1))
                # eg.
                # src_path = /tmp/who/cares/test_files_3/dir1/dir2/file
                # root_name = test_files_3
                # dest_prefix = test_files_3/dir1/dir2/file
                dest_prefix = Path(event.src_path).relative_to(
                    self.file_root).parent
                # LOGGER.debug(f'dest_prefix={dest_prefix} event.src_path={event.src_path} self.file_root={self.file_root}')
                self.upload(event.src_path, dest_prefix=dest_prefix)
        except FileNotFoundError as exc:
            LOGGER.debug(f"Ignoring missing file to upload. Exception: {exc}")
        except BaseException as exc:
            if self._pj:
                self._pj.blink(Blink.UPLOAD, False)
            LOGGER.warning(f"Ignoring unexpected exception during on_created: {exc}")
            # signal to daemon thread we should do a upload() when possible to upload the backlog
            self.backlog = True

    def list_bucket_objects(self, bucket=None, prefix=None) -> [dict]:
        """
        List all objects for the given bucket, or []
        """
        # Add delimiter to match objects in this 'folder' but not
        # objects starting with the prefix
        # eg prefix = 'test' will match 'test/o1' but not 'test.object'
        if prefix is None:
            prefix = self._dest_root
        if bucket is None:
            bucket = self._dest_bucket
        prefix = str(prefix)
        if prefix != '' and prefix[-1] != '/':
            prefix += '/'
        try:
            contents = self.s3.list_objects_v2(
                Bucket=bucket, Prefix=prefix)['Contents']
        except KeyError:
            # No Contents Key, empty bucket.
            return []
        else:
            return contents


def bare_path(p):
    return Path(str(p).strip("/"))


def bare_str(p):
    return str(p).strip("/")


def sig_handler(signal_received, frame):
    raise SignalException


def upload_console(cl_args=argv[1:]):
    # pylint: disable=broad-except
    try:
        logging.basicConfig()
        try:
            signal(SIGINT, sig_handler)
            signal(SIGTERM, sig_handler)
        except Exception:
            pass  # cannot do if in a thread (for testing)

        parser = argparse.ArgumentParser("S3 Upload",
                                         description="Upload files to s3. Overwrites existing. Can sense file system creations in daemon mode.")
        parser.add_argument('-ll', '--log-level', default='INFO', dest='log_level',
                            type=log_level_string_to_int, nargs='?',
                            help='levels: {0}'.format(LOG_LEVEL_STRINGS))
        parser.add_argument('src', type=str, nargs="?",
                            help="Directory (recursive) or file e.g. myfile, ./ or /var/here/")
        parser.add_argument('dest', type=str, nargs="?",
                            help="e.g. s3://tmv.brettbeeson.com.au/tmp/")
        parser.add_argument('--config-file',
                            help="Read [upload] settings. CLI options will override them.", default="./camera.toml")
        parser.add_argument('-i', '--include', type=str,
                            help="When src is a folder, only upload files matching this pattern. Otherwise ignored.")
        parser.add_argument('-mv', '--move', action='store_true',
                            help="Remove local copies of successful upload")
        parser.add_argument('-d', '--daemon', action='store_true',
                            help="Upload everything, then monitor for file creation and upload them too. Never returns: doesn't make itself background.")
        parser.add_argument('-dr', '--dry-run', action='store_true',
                            help="Setup then exit - no upload")
        parser.add_argument("--profile", default=None)
        parser.add_argument("--endpoint", default=None)

        args = parser.parse_args(cl_args)
        LOGGER.setLevel(args.log_level)

        uploader = S3Uploader()
        # start with config file options
        if not Path(args.config_file).is_file():
            shutil.copy(resource_filename(__name__, 'resources/camera.toml'), args.config_file)
            LOGGER.info("Writing default config file to {}.".format(args.config_file))
        uploader.config(args.config_file)

        # override config file with CLI options
        if args.profile:
            uploader.profile = args.profile
        if args.endpoint:
            uploader.endpoint = args.endpoint
        if args.dest:
            uploader.destination = args.dest
        if args.src:
            uploader.file_root = args.src
        if args.include:
            uploader.file_filter = args.include
        if args.move:
            uploader.move = args.move
        if args.dry_run:
            LOGGER.debug(pformat(vars(uploader)))
            sys.exit(0)

        try:
            n = uploader.upload(args.src)
            LOGGER.info(f"Initially uploaded {n} files")
        except BaseException as exc:
            if not args.daemon:
                raise
            else:
                LOGGER.warning(f"Initial upload failed, continuing to daemon. Exception: {exc}")

        if not args.daemon:
            sys.exit(0)

        uploader.daemon()

    except SignalException:
        LOGGER.info('SIGTERM, SIGINT or CTRL-C detected. Exiting gracefully.')
        sys.exit(0)
    except BaseException as exc:
        LOGGER.error(exc)
        LOGGER.debug(exc, exc_info=exc)
        sys.exit(1)
