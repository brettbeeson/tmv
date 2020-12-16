# pylint: disable=line-too-long, logging-fstring-interpolation, protected-access, unused-argument, import-error
from socket import gethostname
import logging
import threading
import shutil
from pathlib import Path
from datetime import datetime as dt, timedelta
from time import sleep
from pprint import pformat
import os
from tempfile import mkdtemp
import pytest

from tmv.util import not_modified_for
from tmv.upload import S3Uploader, upload_console, ConfigError

TEST_DATA = Path(__file__).parent / "testdata"
TEST_FILES_1 = Path("upload_1")
TEST_FILES_2 = Path("upload_2")
TEST_FILES_3 = Path("upload_3")
TEST_FILES_4 = Path("upload_4")

PROFILE = 'minio'
ENDPOINT = 'http://home.brettbeeson.com.au:9000'
BUCKET = 's3://tmv.brettbeeson.com.au'
BUCKET_NAME = 'tmv.brettbeeson.com.au'

LOGGER = logging.getLogger("tmv.upload")


def setup_function():
    """ setup any state specific to the execution of the given module."""
    logging.basicConfig()
    logging.getLogger("tmv.upload").setLevel(logging.DEBUG)
    os.chdir(mkdtemp())
    print("Setting cwd to {}".format(os.getcwd()))
    shutil.copytree(TEST_DATA / TEST_FILES_1, TEST_FILES_1)
    shutil.copytree(TEST_DATA / TEST_FILES_2, TEST_FILES_2)
    shutil.copytree(TEST_DATA / TEST_FILES_3, TEST_FILES_3)
    shutil.copytree(TEST_DATA / TEST_FILES_4, TEST_FILES_4)


def test_s3():
    s3ft = S3Uploader(BUCKET + "/tmp/", profile=PROFILE, endpoint=ENDPOINT)
    s3ft.rm_dest("", recursive=True)
    assert s3ft._upload_dir(TEST_FILES_1, "*.jpg") == 3
    assert s3ft._upload_dir(TEST_FILES_1) == 4
    with pytest.raises(FileNotFoundError):
        s3ft._upload_dir(TEST_FILES_1 / "*")  # wrong syntax
    assert s3ft.rm_dest("", recursive=False) == 2  # 1.jpg, 2.jpg
    assert s3ft.rm_dest("dir1",
                        recursive=False) == 0  # empty
    assert s3ft.rm_dest("/dir1/dir2",
                        recursive=False, file_filter="*.jpg") == 1  # 3.jpg
    # dir1/dir2/nfiles
    assert s3ft.rm_dest("", recursive=True) == 1

    # recursively delete tmp/tests/upload/test_files_2/
    s3ft.rm_dest("", recursive=True)
    assert s3ft._sync(TEST_FILES_2, True, "*") == 4  # 3 jpgs + nfiles
    assert s3ft.rm_dest("", True, "*.jpg") == 3
    assert s3ft._sync(TEST_FILES_2, True, "*.jpg") == 3  # nfiles remains
    # 2 jpgs in /test_files_2
    assert s3ft.rm_dest("", False, "*.jpg") == 2
    # 1 jpgs in /test_files_2/dir2/dir1
    assert s3ft.rm_dest("", True, "*.jpg") == 1

    # reset
    s3ft.rm_dest("", True, "*")
    console_args = ["--config-file=./config.toml", "--endpoint=" + ENDPOINT, "--profile=" + PROFILE, "--log-level=DEBUG", "--include=*.jpg",
                    str(TEST_FILES_2), BUCKET + "/tmp/"]
    # with pytest.raises(SystemExit) as excinfo:
    #    upload_console(console_args)
    #    assert excinfo.value.code == 0
    assert upload_console(console_args) == 0
    # uploaded 3 jpgs
    assert s3ft.rm_dest("", True, "*.jpg") == 3
    # and nothing else
    assert s3ft.rm_dest("", True, "*") == 0


def test_daemon(caplog):

    console_args = ["--config-file=./config.toml", "--endpoint=" + ENDPOINT, "--profile=" + PROFILE,
                    "--daemon", "--log-level=DEBUG", "--include=*.jpg",
                    str(TEST_FILES_3), "s3://tmv.brettbeeson.com.au/tmp/"]

    LOGGER.debug("START COUNT")
    sleep(1)
    root = TEST_FILES_3
    s3ft = S3Uploader("s3://tmv.brettbeeson.com.au/tmp/",
                      profile=PROFILE, endpoint=ENDPOINT)

    s3ft.rm_dest("", True)
    s3ft_thread = threading.Thread(
        target=upload_console, args=(console_args,), daemon=True)
    s3ft_thread.start()  # upload 1,2,3 jpgs
    (root / "touched1.jpg").touch()  # 4
    (root / "touched2.jpg").touch()
    sleep(2)
    (root / "touched2.jpg").touch()  # ignore
    (root / "touched2.jpg").unlink()  # ignore
    (root / "touched2.jpg").touch()  # 5
    (root / "touched2.not-to-be-uploaded").touch()  # ignore via file filter
    (root / "newdir").mkdir()
    (root / "newdir/touched3.jpg").touch()  # 6
    sleep(8)  # let daemon work
    # can be flaky
    # assert sum(("Uploading" in m) == 1 for m in caplog.messages) == 6
    files = [f['Key']
             for f in s3ft.list_bucket_objects("tmv.brettbeeson.com.au", "tmp/")]
    LOGGER.info(pformat(files))
    assert 'tmp/touched2.jpg' in files
    assert 'tmp/newdir/touched3.jpg' in files
    assert s3ft.rm_dest("", True) == 6
    # not possible to do
    # s3ft_thread.terminate()


def test_no_mod():
    """
    Test waiting until a file is no being modified, before uploading
    """
    f = TEST_FILES_3 / "poke1"
    start = dt.now()
    Path(f).touch()
    poker = threading.Thread(
        target=poke, args=[f, timedelta(seconds=2)], daemon=True)
    LOGGER.debug(f"Waiting on {f}")
    poker.start()
    not_modified_for(f, timedelta(seconds=3))
    LOGGER.debug(f'Finished waiting on {f}')
    assert 4 < (dt.now() - start).total_seconds() < 6

    start = dt.now()
    f = TEST_FILES_3 / "poke2"
    Path(f).touch()
    poker = threading.Thread(
        target=poke, args=[f, timedelta(seconds=2)], daemon=True)
    LOGGER.debug(f"Waiting on {f}")
    poker.start()
    not_modified_for(f, timedelta(seconds=3))
    LOGGER.debug(f'Finished waiting on {f}')
    assert 4 < (dt.now() - start).total_seconds() < 6


def poke(file, period=timedelta(seconds=5), freq=timedelta(seconds=0.5)):
    start = dt.now()
    while dt.now() < start + period:
        Path(file).touch()
        LOGGER.debug(f"Poking {file}")
        sleep(freq.total_seconds())
    LOGGER.debug(f"Finished poking {file}")


def test_config():
    c = """
    [camera]
        file_root = '/tmp/tmv-images/camera1'
        image_suffix = '.jpg'
    [upload]
        # source = camera.file_root
        destination = '""" + BUCKET + """/desto'
        extraargs.ACL = 'public-read'
    """
    s3ft = S3Uploader()
    s3ft.configs(c)
    assert s3ft._dest_bucket == BUCKET_NAME
    assert s3ft._dest_root == 'desto'


def test_S3Uploader():
    c = """
    [camera]
        file_root = 'upload_3/'
        file_filter = '*.jpg'
    [upload]
        destination = '""" + BUCKET + """/tmp/'
        extraargs.ACL = 'public-read'
        move = true
        profile = '""" + PROFILE + """'
        endpoint = '""" + ENDPOINT + """'
    """
    up = S3Uploader()
    up.configs(c)
    assert up._dest_bucket == BUCKET_NAME
    assert up._dest_root == 'tmp'
    up.rm_dest("", True)
    up.upload()
    files_uploaded = up.list_bucket_objects()
    assert len(files_uploaded) == 3  # 3 jpgs, not nfiles

    up_daemon = threading.Thread(target=up.daemon, daemon=True)
    up_daemon.start()
    sleep(1)  # daemon starts
    (TEST_FILES_3 / "new1.jpg").touch()
    (TEST_FILES_3 / "new2.jpg").touch()
    (TEST_FILES_3 / "dir1" / "new3.jpg").touch()
    sleep(5)  # daemon runs
    files_uploaded = up.list_bucket_objects()
    assert len(files_uploaded) == 6  # 3 new files
    up.rm_dest("", True)


def test_latest_image(caplog):
    """ check we don't update latest-image.jpg """
    c = """
    [camera]
        file_root = 'upload_4/'

        file_filter = '*.jpg'
    [upload]
        destination = '""" + BUCKET + """/tmp/'
        move = true
        profile = '""" + PROFILE + """'
        endpoint = '""" + ENDPOINT + """'
    """
    up = S3Uploader()
    up.configs(c)
    up.upload()
    assert Path("upload_4/latest-image.jpg").exists()
    up.rm_dest("", True)


def test_errors():
    up = S3Uploader()
    with pytest.raises(ConfigError):
        up.upload()
    up.destination = "s3://tmv.brettbeeson.com.au/"
    with pytest.raises(ConfigError):
        up.rm_dest("")

    c = """
    [camera]
        file_root = './test_files_3/'
        image_suffix = '.jpg'
    #[upload]
        # source = camera.file_root
    #    destination = BUCKET + '/tmp/'
    #    extraargs.ACL = 'public-read'
    #    move = true
    """
    up = S3Uploader()
    with pytest.raises(ConfigError):
        up.configs(c)


def test_upload_console(caplog):
    c = """
    [upload]
    destination = "s3://bucketname/dir1"
    src = "/local/dir"
    move=true
    file_filter="*.png"
    """
    Path("camera.toml").write_text(c)
    console_args = ["--config-file=./camera.toml",
                    "--log-level=DEBUG",
                    "--include=*.jpg",  # should override!
                    "--config-file={}".format("camera.toml"),  # the *.png here
                    "--dry-run"]


    assert         upload_console(console_args)==0
        
    assert "*.jpg" in (caplog.records[1]).message
    Path("camera.toml").write_text(c)
    console_args = ["--log-level=DEBUG",
                    "--config-file={}".format(TEST_DATA / "config-1.toml"),
                    "--dry-run"]

    assert upload_console(console_args) == 0



def test_id():
    c = """
    [camera]
        file_root = './upload_3/'
    [upload]
         destination = '""" + BUCKET + "/tmp/HOSTNAME" + "'"

    up = S3Uploader()
    up.configs(c)
    assert up.destination == "tmv.brettbeeson.com.au/tmp/" + str(gethostname())
    c = """
    [camera]
        file_root = './upload_3/'
    [upload]
         destination = '""" + BUCKET + """/tmp/xxx'
    """
    up = S3Uploader()
    up.configs(c)
    assert up.destination == "tmv.brettbeeson.com.au/tmp/xxx"


def failing_test_no_internet_2(monkeypatch):
    up = S3Uploader(BUCKET + "/tmp/", './upload_3/',
                    profile=PROFILE, endpoint=ENDPOINT)
    up.internet_check_period = timedelta(seconds=0.5)
    up.move = True
    up.rm_dest("", recursive=True)
    up.upload()
    daemon = threading.Thread(target=up.daemon, daemon=True)
    daemon.start()
    sleep(2)
    (TEST_FILES_3 / "touched1.jpg").touch()  # upload this
    sleep(4)
    files_uploaded = up.list_bucket_objects()
    assert len(files_uploaded) == 4
    # force internet to fail
    up.internet = lambda: False
    # internet fails in daemon
    sleep(6)
    (TEST_FILES_3 / "touched2.jpg").touch()  # don't upload this yet
    sleep(6)
    files_uploaded = up.list_bucket_objects()
    assert len(files_uploaded) == 4
    # restart - should upload touched2
    up.internet = lambda: True
    sleep(5)
    files_uploaded = up.list_bucket_objects()
    assert len(files_uploaded) == 5
    (TEST_FILES_3 / "touched3.jpg").touch()  # upload this
    sleep(3)
    files_uploaded = up.list_bucket_objects()
    assert len(files_uploaded) == 5
