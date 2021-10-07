# pylint: disable=line-too-long, logging-fstring-interpolation, dangerous-default-value, logging-not-lazy,

import logging
from pprint import pformat
from sys import argv, stderr
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
from _datetime import datetime as dt

from pkg_resources import resource_filename
import boto3
from boto3.exceptions import S3UploadFailedError
from botocore.exceptions import ClientError
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from tmv.util import LOG_LEVELS, Tomlable, check_internet, LOG_FORMAT, next_mark, not_modified_for
from tmv.camera import ConfigError, SignalException, CAMERA_CONFIG_FILE
from tmv.config import *  # pylint: disable=unused-wildcard-import, wildcard-import


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
    todo: remove boto and replace will lightweight (minio client: https://docs.min.io/docs/python-client-api-reference.html)
    """
    # Uploading *moves* files. It simply tries to upload all
    # files one first run and then on any filesystem change.
    # Therefore if it copies, it would repeatedly upload the same
    # files.
    # The watchbog (on_create) sets a flag that something has changes.
    # daemon() polls AND wakes up on on_create and does a full
    #    upload every time. do this. if necessary "copy" could be done
    #    via a move to a local location

    def __init__(self, destination=None, tmv_root="", profile=None, endpoint=None):
        super().__init__()
        self._ExtraArgs = {'ACL': 'public-read'}
        self._dest_bucket = None
        self._dest_root = None   # starts with "/"
        if destination:
            self.destination = destination
        self.tmv_root = tmv_root
        self.file_filter = "*.jpg"
        self.latest_image = "latest-image.jpg"
        self._s3 = None
        self.profile = profile
        self.endpoint = endpoint
        self.upload_callback = None
        self.upload_required = True
        self.interval = timedelta(seconds=60)

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
            self.setattr_from_dict("extraargs", config)
            self.setattr_from_dict("file_filter", config)
            self.setattr_from_dict("profile", config)
            self.setattr_from_dict("endpoint", config)
            if "interval" in config:
                self.interval = timedelta(seconds=config['interval'])
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
            self.setattr_from_dict("tmv_root", config)
            self.setattr_from_dict("latest_image", config)

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

    def upload_notify(self, filename):
        """ Call the callback (supplied by user). For example, it might blink a light on upload. """
        LOGGER.debug(f"Uploaded {str(filename)}")
        if self.upload_callback is not None:
            pass
            # self.upload_callback()

    def upload(self, src_file_or_dir=None, dest_prefix=""):  # , throw=False):
        """
        Upload a file or directory to s3
        This appears thread-safe but could have a mutex?
        """

        if src_file_or_dir is None:
            src_file_or_dir = self.tmv_root

        src_file_or_dir = Path(src_file_or_dir)

        if src_file_or_dir.is_dir():
            return self._upload_dir(src_file_or_dir, self.file_filter, True, dest_prefix)
        elif src_file_or_dir.is_file():
            return self._upload_file(src_file_or_dir, True, dest_prefix)
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
        if src_dir / self.latest_image in src_files:
            # don't upload the 'latest-image.jpg' copy
            src_files.remove(Path(src_dir / self.latest_image))

        for src_file in src_files:
            src_file_rel = src_file.relative_to(src_dir)
            dest_file = self._dest_root / dest_prefix / src_file_rel

            try:
                dest_file = Path(dest_file)
                self.s3.upload_file(str(src_file), Bucket=self._dest_bucket,
                                    Key=str(dest_file),
                                    ExtraArgs=self._ExtraArgs)
                self.upload_notify(f"Uploaded {src_file.name} to {self._dest_bucket}:{dest_file}")

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

        if self.latest_image == src_file.name:
            # LOGGER.debug(f"Not uploading {src_file}")
            return

        dest_file = self._dest_root / dest_prefix / src_file.name
        not_modified_for(src_file, timedelta(seconds=1))  # wait so we don't upload a file being modified / created
        self.s3.upload_file(str(src_file), Bucket=self._dest_bucket,
                            Key=str(dest_file),
                            ExtraArgs=self._ExtraArgs)
        self.upload_notify(f"Uploaded {src_file.name} to {self._dest_bucket} {dest_file}")
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

        if src_dir / self.latest_image in src_files:
            LOGGER.debug("Removing from list: {src_file}")
            src_files.remove(Path(src_dir / self.latest_image))

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
                self.upload_notify("Uploading {src_file.name} to {self._dest_bucket} {dest_file}")
                uploads += 1
        return uploads

    def daemon(self, use_observer=True):
        LOGGER.info(f"Starting daemon. File system observer: {use_observer}")
        if use_observer:
            observer = Observer()
            observer.schedule(self, self.tmv_root, recursive=True)
            observer.start()

        while True:
            # sleep until next upload mark, or we detect a new file
            next_upload = next_mark(self.interval, dt.now())
            while dt.now() < next_upload and not self.upload_required:
                sleep(1)

            LOGGER.debug(f"Uploading files, interval: {self.interval} connected: {check_internet()} upload_required:{self.upload_required}")

            if check_internet():
                try:
                    self.upload_required = False  # On failure, don't keep trying. Wait til next interval.
                    self.upload()
                except S3UploadFailedError as exc:  # pylint: disable=broad-except
                    LOGGER.debug("Failed to upload.", exc_info=exc)
                    LOGGER.warning(f"Failed to upload: {exc}")
            else:
                LOGGER.debug("No internet. Not uploading")

    # def on_any_event(self, event):
        # LOGGER.debug(f'Ignoring event type: {event.event_type}  path : {event.src_path}')

    def on_created(self, event):
        """
        watchdog for filesystem: signal main loop to upload immediately
        """
        #LOGGER.debug("file created detected")
        if self.upload_required:
            return
        # wait to notify until file is finished creation
        not_modified_for(event.src_path, timedelta(seconds=1))
        self.upload_required = True

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
        except Exception as e:
            print (e, file=stderr)  # cannot do if in a thread (for testing)

        parser = argparse.ArgumentParser("S3 Upload",
                                         description="Upload files to s3. Overwrites existing. Can sense file system creations in daemon mode.")
        parser.add_argument('--log-level', '-ll', default='WARNING', type=lambda s: LOG_LEVELS(s).name, nargs='?',
                            choices=LOG_LEVELS.choices())
        parser.add_argument('src', type=str, nargs="?",
                            help="Directory (recursive) or file e.g. myfile, ./ or /var/here/")
        parser.add_argument('dest', type=str, nargs="?",
                            help="e.g. s3://tmv.brettbeeson.com.au/tmp/")
        parser.add_argument('-c', '--config-file',
                            help="Read [upload] settings. CLI options will override them.", default=CAMERA_CONFIG_FILE)
        parser.add_argument('-i', '--include', type=str,
                            help="When src is a folder, only upload files matching this pattern. Otherwise ignored.")
        parser.add_argument('-d', '--daemon', action='store_true',
                            help="Upload everything, then monitor for file creation and upload them too. Never returns: doesn't make itself background.")
        parser.add_argument('-no', '--no-observer', action='store_true',
                            help="Don't monitor the file system for changes. Just upload periodically.")
        parser.add_argument('-dr', '--dry-run', action='store_true',
                            help="Setup then exit - no upload")
        parser.add_argument("--profile", default=None)
        parser.add_argument("--endpoint", default=None)

        args = parser.parse_args(cl_args)

        logging.basicConfig(format=LOG_FORMAT)
        LOGGER.setLevel(args.log_level)

        uploader = S3Uploader()
        # start with config file options
        if not Path(args.config_file).is_file():
            shutil.copy(resource_filename(__name__, 'resources/camera.toml'), args.config_file)
            LOGGER.info("Writing default config file to {}.".format(args.config_file))
        LOGGER.info(f"Using config file at {args.config_file}")
        uploader.config(args.config_file)

        # override config file with CLI options
        if args.profile:
            uploader.profile = args.profile
        if args.endpoint:
            uploader.endpoint = args.endpoint
        if args.dest:
            uploader.destination = args.dest
        if args.src:
            uploader.tmv_root = args.src
        if args.include:
            uploader.file_filter = args.include
        if args.dry_run:
            LOGGER.debug(pformat(vars(uploader)))
            return 0

        try:
            n = uploader.upload(args.src)
            LOGGER.info(f"Initially uploaded {n} files")
        except Exception as exc:
            if not args.daemon:
                raise
            else:
                LOGGER.warning(f"Initial upload failed, continuing to daemon. Exception: {exc}")

        if not args.daemon:
            return 0

        uploader.daemon(use_observer=not args.no_observer)

    except SignalException:
        LOGGER.info('SIGTERM, SIGINT or CTRL-C detected. Exiting gracefully.')
        return 0
    except Exception as exc:
        LOGGER.error(exc)
        LOGGER.debug(exc, exc_info=True)
        return 1
