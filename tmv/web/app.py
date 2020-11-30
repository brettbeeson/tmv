#!/usr/bin/env python
# pylint: disable=line-too-long, logging-fstring-interpolation, dangerous-default-value, logging-not-lazy

import os
import sys
from pathlib import Path
from threading import Thread
from base64 import b64encode
from time import sleep
from shutil import copy
import argparse
import logging
from pkg_resources import resource_filename
from flask import Flask, send_from_directory
from flask_socketio import SocketIO, emit #, Namespace
from toml import loads, TomlDecodeError
from tmv.camera import CAMERA_CONFIG_FILE, DLFT_CAMERA_SW_SWITCH_TOML
from tmv.button import get_switch, OnOffAuto
from tmv.systemd import Unit
from tmv.util import run_and_capture, unlink_safe, Tomlable, LOG_LEVELS, LOG_FORMAT, ensure_config_exists

from tmv.web import create_app, cam_config, socketio

LOGGER = logging.getLogger(__name__)


def report_errors(func):
    """ My first decorator: try errors and report to client. Not rul securz """
    def wrappers(*args, **kwargs):
        try:
            func(*args, **kwargs)
        except Exception as exc:
            print("report_errors")
            emit('warning', f"Error: {exc}")
    return wrappers


def send_image(broadcast, binary=True):
    if cam_config is None or cam_config.latest_image is None or not Path(cam_config.latest_image).exists():
        return
    socketio.emit('message', f"Sending image {cam_config.latest_image}")
    with cam_config.latest_image.open(mode='rb') as f:
        image_data_bin = f.read()
    if binary:
        socketio.emit('image', {'src-bin': image_data_bin}, broadcast=True)
    else:
        image_data_b64 = b64encode(image_data_bin)
        socketio.emit('image', {'src-b64': image_data_b64.decode('utf-8')}, broadcast=broadcast)
    socketio.emit('message', f"New image sent: {cam_config.latest_image}")

def broadcast_image_thread():
    """
    Poll / watch for new image and send to all clients
    """
    image_mtime_was = None
    image_mtime_is = None
    while True:
        sleep(1)
        try:
            if cam_config:
                image_mtime_is = cam_config.latest_image.stat().st_mtime
                if image_mtime_was is None or image_mtime_is > image_mtime_was:
                    send_image(broadcast = True)
                    image_mtime_was = image_mtime_is
        except FileNotFoundError as exc:
            socketio.emit('warning', f"{cam_config.latest_image}: {repr(exc)}")
            print(exc, file=sys.stderr)


def broadcast_status():
    camera_was = None
    upload_was = None
    while True:
        sleep(1)
        if cam_config:
            ss = cam_config.switches
            camera_is = ss['camera']
            if camera_was is None or camera_is != camera_was:
                socketio.emit('switches', {'message': "Camera switched", 'camera': str(camera_is)})
                camera_was = camera_is
            upload_is = ss['upload']
            if upload_was is None or upload_is != upload_was:
                socketio.emit('switches', {'message': "Upload switched", 'upload': str(upload_is)})
                upload_was = upload_is


@socketio.on('req-services-status')
def services_status():
    try:
        cl = Unit("tmv-controller.service")
        cam = Unit("tmv-camera.service")
        ul = Unit("tmv-upload.service")
        services = {
            str(cl): cl.status(),
            str(cam): cl.status(),
            str(ul): cl.status(),
        }
        emit("services-status", {"message": "Read service statuses", "services": services})
    except Exception as exc:
        emit('warning', f"Couldn't get service statuses: {exc}")


@socketio.on('restart')
@report_errors
def restart():
    ctlr = Unit("tmv-controller.service")
    ctlr.restart()
    sleep(5)
    emit("message", f"tmv-controller: {ctlr.status()}")


@socketio.on('req-journal')
@report_errors
def req_journal():
    lines = 100
    so, se = run_and_capture(["journalctl", "-u", "tmv*", "-n", str(lines)])
    emit("journal", {"journal": so + se})


@socketio.on('req-files')
@report_errors
def req_files():
    if cam_config:
        fls = []
        for f in cam_config.file_root.glob("*"):
            fls.append(str(f))
        emit("files", {"files": fls})


@socketio.on('switches')
@report_errors
def set_switches(positions):
    if cam_config and cam_config.switches:
        for s_name, s_pos in positions.items():
            cam_config.switches[s_name] = OnOffAuto(s_pos.lower())
    else:
        raise RuntimeError("No switches available")


@socketio.on('req-switches')
@report_errors
def req_switches():
    if cam_config:
        emit('switches', {'camera': str(cam_config.switches['camera']), 'upload': str(cam_config.switches['upload'])})


@socketio.on('req-camera-config')
@report_errors
def req_camera_config():
    print("camera-config requested")
    config_path = Path("/etc/tmv/camera.toml")
    emit('camera-config', {'toml': config_path.read_text()})


@socketio.on('camera-config')
@report_errors
def camera_config(configs):
    if cam_config:
        loads(configs)  # check syntax
        cf = CAMERA_CONFIG_FILE
        unlink_safe(cf + ".bak")
        copy(cf, cf + ".bak")
        Path(cf).write_text(configs)
        # re-read this ourselves, too, to get new file_root, etc
        cam_config.config(cf)
        emit("message", "Saved config. (Consider a restart)")


@socketio.on('connect')
def connect():
    print("Client connected!")
    emit('message', 'Hello from TMV Camera.')
    try:
        send_image(broadcast=False)
    except FileNotFoundError:
        pass
   

def web_console(cl_args=sys.argv[1:]):
    parser = argparse.ArgumentParser("Web server for TMV Camera.")
    parser.add_argument('--log-level', '-ll', default='WARNING', type=lambda s: LOG_LEVELS(s).name, nargs='?', choices=LOG_LEVELS.choices())
    parser.add_argument('--config-file', default=CAMERA_CONFIG_FILE)
    args = parser.parse_args()

    LOGGER.setLevel(args.log_level)
    logging.basicConfig(format=LOG_FORMAT, level=args.log_level)
    try:
        app = create_app(args.config_file)
        socketio.run(app, debug=True)
        print("G")

    except (FileNotFoundError, TomlDecodeError) as exc:
        print(exc)
        sys.exit(1)


if __name__ == '__main__':
    web_console(sys.argv)
    
    