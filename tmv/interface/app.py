#!/usr/bin/env python3
# pylint: disable=line-too-long, logging-fstring-interpolation, dangerous-default-value, logging-not-lazy


import sys
from pathlib import Path
from base64 import b64encode
from time import sleep
from shutil import copy
import argparse
from threading import Thread
import logging

#from pkg_resources import resource_filename
#from flask import Flask, send_from_directory
from flask_socketio import emit, SocketIO
from flask import Flask, render_template

from toml import loads, TomlDecodeError
from tmv.camera import CAMERA_CONFIG_FILE, Camera
from tmv.buttons import OnOffAuto
from tmv.systemd import Unit
from tmv.util import run_and_capture, unlink_safe, LOG_LEVELS, LOG_FORMAT, ensure_config_exists

LOGGER = logging.getLogger("tmv.interface")

app = Flask("tmv.interface.app", static_url_path="/",static_folder="static")
app.config['SECRET_KEY'] = 'secret!'
camera = None
socketio = SocketIO(app)


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
    if camera is None or camera.latest_image is None or not Path(camera.latest_image).exists():
        return
    socketio.emit('message', f"Sending image {camera.latest_image}")
    im = Path(camera.latest_image)
    with im.open(mode='rb') as f:
        image_data_bin = f.read()
    if binary:
        socketio.emit('image', {'src-bin': image_data_bin}, broadcast=True)
    else:
        image_data_b64 = b64encode(image_data_bin)
        socketio.emit('image', {'src-b64': image_data_b64.decode('utf-8')}, broadcast=broadcast)
    socketio.emit('message', f"New image sent: {camera.latest_image}")


def manage_screen_interface_thread():
    """
     Display key parameters and image on the screen and react to screen button presses
    """
    LOGGER.debug("manage_screen_interface_thread starting")
    while True:
        sleep(10)
        print(__name__)
            

        socketio.emit('message', 'Ping  from TMV Camera.')


def broadcast_image_thread():
    """
    Poll / watch for new image and send to all clients
    """
    image_mtime_was = None
    image_mtime_is = None
    while True:
        sleep(1)
        try:
            if camera:
                im = Path(camera.latest_image)
                if im.exists():
                    image_mtime_is = im.stat().st_mtime
                    if image_mtime_was is None or image_mtime_is > image_mtime_was:
                        send_image(broadcast=True)
                        image_mtime_was = image_mtime_is
        except FileNotFoundError as exc:
            socketio.emit('warning', f"{camera.latest_image}: {repr(exc)}")
            print(exc, file=sys.stderr)


def broadcast_status_thread():
    mode_was = None
    while True:
        sleep(1)
        if camera:
            mode_is = camera.mode_button.value
            if mode_was is None or mode_is != mode_was:
                socketio.emit('mode', {'message': "Camera mode changed", 'camera': str(mode_is)})
                mode_was = mode_is



@socketio.on('req-services-status')
def services_status():
    try:
        cl = Unit("tmv-interface.service")
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

#@app.route('/')
#def index():
 #   return render_template('index.html')


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
    if camera:
        fls = []
        for f in camera.file_root.glob("*"):
            fls.append(str(f))
        emit("files", {"files": fls})
    emit('message', 'Send files')


@socketio.on('switches')
@report_errors
def set_mode(pos: str):
    if camera and camera.mode_button:
        camera.mode_button.value = OnOffAuto(pos.lower())
    else:
        raise RuntimeError("No button available")


@socketio.on('req-switches')
@report_errors
def req_mode():
    if camera:
        emit('mode', {'camera': str(camera.mode_button.value)})


@socketio.on('req-camera-config')
@report_errors
def req_camera_config():
    print("camera-config requested")
    config_path = Path("/etc/tmv/camera.toml")
    emit('camera-config', {'toml': config_path.read_text()})


@socketio.on('camera-config')
@report_errors
def camera_config(configs):
    if camera:
        loads(configs)  # check syntax
        cf = CAMERA_CONFIG_FILE
        unlink_safe(cf + ".bak")
        copy(cf, cf + ".bak")
        Path(cf).write_text(configs)
        # re-read this ourselves, too, to get new file_root, etc
        camera.config(cf)
        emit("message", "Saved config. (Consider a restart)")


@socketio.on('connect')
@report_errors
def connect():
    print("Client connected!")
    emit('message', 'Hello from TMV Camera.')
    try:
        send_image(broadcast=False)
    except FileNotFoundError:
        pass
    


def start_threads():
  # status_thread = Thread(target=broadcast_status)
        # status_thread.start()
        # image_thread = Thread(target=broadcast_image_thread)
        # image_thread.start()
        # unsure of decorator
    socketio.start_background_task(manage_screen_interface_thread)
    socketio.start_background_task(broadcast_status_thread)
    socketio.start_background_task(broadcast_status_thread)
 
def create_camera(config_file):
    global camera
    camera = Camera(fake=True)
    camera.config(config_file)

def web_console():
    # cl_args=sys.argv[1:]
    parser = argparse.ArgumentParser("Interface (screen, web, web-socket server) to TMV Camera.")
    parser.add_argument('--log-level', '-ll', default='WARNING', type=lambda s: LOG_LEVELS(s).name, nargs='?', choices=LOG_LEVELS.choices())
    parser.add_argument('--config-file', '-cf', default=CAMERA_CONFIG_FILE)
    args = parser.parse_args()

    LOGGER.setLevel(args.log_level)
    logging.getLogger("tmv.util").setLevel(args.log_level)
    logging.basicConfig(format=LOG_FORMAT, level=args.log_level)
  
    try:
        ensure_config_exists(args.config_file)       
        create_camera(args.config_file)
        start_threads()
        socketio.run(app)
        while True:
            sleep(1)

    except (FileNotFoundError, TomlDecodeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    except Exception as exc:
        print(exc, file=sys.stderr)
        return 1

if __name__ == '__main__':
    # sys.exit(web_console(sys.argv))
    web_console()
