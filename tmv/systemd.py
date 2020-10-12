# pylint: disable=logging-fstring-interpolation,logging-not-lazy, dangerous-default-value
#
# Manipulate systemd services from python
# 

import logging
from shutil import which
from posix import geteuid
from subprocess import CalledProcessError
# to enable monkeypatching, don't import "from tmv.util", but instead:
import tmv.util
from tmv.util import  service_details

LOGGER = logging.getLogger("tmv.systemd")


class Unit:
    """
    subprocess/systemdctl based control of systemd units, similiar interface as psytemd.systemd1.Unit
    """

    def __init__(self, service_full_name):
        """ e.g. Unit("tmv-camera.service") """
        self._service = service_full_name

    def __str__(self):
        return self._service

    @staticmethod
    def can_systemd():
        if not which("systemctl"):
            LOGGER.warning("Cannot find systemctl to run services")
            return False
        if geteuid() != 0:
            LOGGER.warning(
                f"Running as non-root (euid {geteuid()}): may not be able to run systemd!")
            return False
        return True

    def active(self):
        """
        true if status is 'active (...)'
        false otherwise or non-existant
        """
        try:
            return service_details(self._service)['status'].startswith('active')
        except (CalledProcessError, KeyError):
            return False

    def status(self):
        try:
            return service_details(self._service)['status']
        except KeyError:
            return 'unknown'

    def start(self, time_out=10):
        LOGGER.info(f"execute: systemctl start {self._service}")
        tmv.util.run_and_capture(["sudo", "systemctl", "start", self._service], timeout=time_out)

    def stop(self, time_out=10):
        LOGGER.info(f"execute: systemctl stop {self._service}")
        tmv.util.run_and_capture(["sudo", "systemctl", "stop", self._service], timeout=time_out)

    def restart(self, time_out=10):
        LOGGER.info(f"execute: systemctl restart {self._service}")
        tmv.util.run_and_capture(["sudo", "systemctl", "restart", self._service], timeout=time_out)

