# pylint: disable=line-too-long, logging-fstring-interpolation, dangerous-default-value, import-error,redefined-outer-name, unused-argument


import os
import socket
import logging
from datetime import datetime as dt, timedelta
from socket import socket
import threading
import time
from pathlib import Path
from tempfile import mkdtemp
from dateutil.parser import parse

import pytest

from tmv.camera import Camera
from tmv.config import OFF, ON, VIDEO
from tmv.util import LOG_FORMAT, today_at

from freezegun import freeze_time

TEST_DATA = Path(__file__).parent / "testdata"

FDT = None


def sleepless(s):
    """ instead of really sleeping, just move frozen time forward """
    # pytest or something used 0.01s sleeps during the test: ignore these
    # or our times will get stuffed
    if s > 0.1:
        FDT.tick(timedelta(seconds=s))
        # for _ in range(int(s * 10)):
        #    fdt_global.tick(timedelta(milliseconds=100))


@pytest.fixture(scope="function")
def setup_test():
    os.chdir(mkdtemp())
    print("Setting cwd to {}".format(os.getcwd()))
    logging.basicConfig(format=LOG_FORMAT)
    logging.getLogger("tmv.streamer").setLevel(logging.DEBUG)


def test_video(monkeypatch, setup_test):
    c = Camera(sw_cam=True)
    c.file_by_date = False
    with freeze_time(parse("2000-01-01 12:00:00")) as fdt:
        global FDT
        FDT = fdt
        real_sleep = time.sleep
        monkeypatch.setattr(time, 'sleep', sleepless)
        # start normally
        c.mode_button.value = ON
        c._interval = timedelta(seconds=60)

        while dt.now() < today_at(13):
            c.run(1)
            fdt.tick(timedelta(seconds=1))

        # switch to video mode
        c.mode_button.value = VIDEO
        vtd = threading.Thread(target=video_server, args=(c, fdt), daemon=True)
        vtd.start()
        real_sleep(3)
        c.mode_button.value = OFF
        vtd.join()
        real_sleep(1)

        # switch to video mode agina : ok
        c.mode_button.value = VIDEO
        vtd = threading.Thread(target=video_server, args=(c, fdt), daemon=True)
        vtd.start()
        real_sleep(3)
        c.mode_button.value = OFF
        vtd.join()


def video_server(c: Camera, fdt):
    while c.mode_button.value != VIDEO:
        c.run(1)

