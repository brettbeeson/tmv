#!/usr/bin/env python3
# pylint: disable=line-too-long, logging-fstring-interpolation, dangerous-default-value, logging-not-lazy


import sys
from pathlib import Path
from base64 import b64encode
from time import sleep
from shutil import copy
import argparse

import logging
from socket import gethostname, gethostbyname
from debugpy import breakpoint 
from flask_socketio import emit, SocketIO
from flask import Flask, send_from_directory
from subprocess import CalledProcessError
from toml import loads, TomlDecodeError
from tmv.camera import CAMERA_CONFIG_FILE, Camera, SOFTWARE, HARDWARE
from tmv.buttons import OnOffAuto, Speed
from tmv.systemd import Unit
from tmv.util import run_and_capture, unlink_safe, LOG_LEVELS, LOG_FORMAT, ensure_config_exists
from tmv.exceptions import ButtonError

LOGGER = logging.getLogger("tmv.interface")

app = Flask("tmv.interface.app", static_url_path="/", static_folder="static")
app.config['SECRET_KEY'] = 'secret!'
app.config["EXPLAIN_TEMPLATE_LOADING"] = True
interface_camera = Camera(camera_firmness=SOFTWARE, buttons_firmness=HARDWARE)
socketio = SocketIO(app)


def report_errors(func):
    """ My first decorator: try errors and report to client. Not rul securz """
    def wrappers(*args, **kwargs):
        try:
            func(*args, **kwargs)
        except Exception as exc:  # pylint: disable=broad-except
            emit('warning', f"Error: {exc}")
    return wrappers


def send_image(broadcast, binary=True):
    if interface_camera is None or interface_camera.latest_image is None or not Path(interface_camera.latest_image).exists():
        return
    im = Path(interface_camera.latest_image)
    with im.open(mode='rb') as f:
        image_data_bin = f.read()
    if binary:
        socketio.emit('image', {'src-bin': image_data_bin}, broadcast=True)
    else:
        image_data_b64 = b64encode(image_data_bin)
        socketio.emit('image', {'src-b64': image_data_b64.decode('utf-8')}, broadcast=broadcast)


def manage_screen_interface_thread():
    """
     Display key parameters and image on the screen and react to screen button presses
    """
    LOGGER.debug("manage_screen_interface_thread starting")
    while True:
        sleep(10)


def broadcast_image_thread():
    """
    Poll / watch for new image and send to all clients
    """
    image_mtime_was = None
    image_mtime_is = None
    while True:
        sleep(1)
        #breakpoint()
        try:
            if interface_camera:
                im = Path(interface_camera.latest_image)
                if im.exists():
                    image_mtime_is = im.stat().st_mtime
                    if image_mtime_was is None or image_mtime_is > image_mtime_was:
                        send_image(broadcast=True)
                        image_mtime_was = image_mtime_is
                        socketio.emit('message', f"New image sent: {interface_camera.latest_image}")
        except FileNotFoundError as exc:
            socketio.emit('warning', f"{interface_camera.latest_image}: {repr(exc)}")
            print(exc, file=sys.stderr)


def broadcast_buttons_thread():
    mode_was = None
    speed_was = None
    while True:
        sleep(1)
        if interface_camera:
            if interface_camera.mode_button.ready():
                mode_is = interface_camera.mode_button.value
                if mode_was is None or mode_is != mode_was:
                    socketio.emit('message', f"Mode changed to {mode_is}")
                    mode_was = mode_is

            if interface_camera.speed_button.ready():
                speed_is = interface_camera.speed_button.value
                if speed_was is None or speed_is != speed_was:
                    socketio.emit('message', f"speed changed to {speed_is}")
                    speed_was = speed_is


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@socketio.on('req-services-status')
@report_errors
def services_status():
    cl = Unit("tmv-interface.service")
    cam = Unit("tmv-camera.service")
    ul = Unit("tmv-upload.service")
    services = {
        str(cl): cl.status(),
        str(cam): cl.status(),
        str(ul): cl.status(),
    }
    emit("services-status", services)


@socketio.on('restart-camera')
@report_errors
def restart_service():
    ctlr = Unit("tmv-camera.service")
    ctlr.restart()
    sleep(5)
    emit("message", f"Restarted camera.\ntmv-camera: {ctlr.status()}")


@socketio.on('req-journal')
@report_errors
def req_journal():
    lines = 100
    so, se = run_and_capture(["journalctl", "-u", "tmv*", "-n", str(lines)])
    emit("journal", {"journal": so + se})


@socketio.on('req-files')
@report_errors
def req_files():
    if interface_camera:
        fls = []
        for f in Path(interface_camera.file_root).glob("*"):
            fls.append(str(f))
        emit("files", {"files": fls})
    emit('message', 'Send files')


@socketio.on('mode')
@report_errors
def set_mode(pos: str):
    if interface_camera and interface_camera.mode_button:
        interface_camera.mode_button.value = OnOffAuto(pos.lower())
    else:
        raise RuntimeError("No button available")


@socketio.on('req-mode')
@report_errors
def req_mode():
    if interface_camera:
        emit('mode', str(interface_camera.mode_button.value))


@socketio.on('speed')
@report_errors
def set_speed(pos: str):
    if interface_camera and interface_camera.speed_button:
        interface_camera.speed_button.value = Speed(pos.lower())
    else:
        raise RuntimeError("No button available")


@socketio.on('req-speed')
@report_errors
def req_speed():
    if interface_camera:
        emit('speed', str(interface_camera.speed_button.value))


@socketio.on('raise-error')
@report_errors
def raise_error():
    raise RuntimeError("What did you expect?")


@socketio.on('req-camera-config')
@report_errors
def req_camera_config():
    config_path = interface_camera.config_path
    if config_path is None:
        raise RuntimeError("No config path available")
    else:
        emit('camera-config', config_path.read_text())


@socketio.on('req-camera-name')
@report_errors
def req_camera_name():
    emit('camera-name', gethostname())
    emit('message', f"hostname: {gethostname()}")


@socketio.on('req-camera-ip')
@report_errors
def req_camera_ip():
    emit('camera-ip', gethostbyname(gethostname()))
    emit('message', f"IP: {gethostbyname(gethostname())}")


@socketio.on('camera-config')
@report_errors
def camera_config(configs):
    if interface_camera:
        loads(configs)  # check syntax
        cf = interface_camera.config_path
        unlink_safe(cf.with_suffix(".bak"))
        copy(cf, cf.with_suffix(".bak"))
        Path(cf).write_text(configs)
        # re-read this ourselves, too, to get new file_root, etc
        interface_camera.config(cf)
        emit("message", "Saved config.")


@socketio.on('connect')
@report_errors
def connect():
    emit('message', 'Hello from TMV!')
    try:
        send_image(broadcast=False)
    except FileNotFoundError:
        pass


def start_threads():
    socketio.start_background_task(manage_screen_interface_thread)
    socketio.start_background_task(broadcast_buttons_thread)
    socketio.start_background_task(broadcast_image_thread)


def interface_console(cl_args=sys.argv[1:]):
    parser = argparse.ArgumentParser("Interface (screen, web, web-socket server) to TMV interface_camera.")
    parser.add_argument('--log-level', '-ll', default='WARNING', type=lambda s: LOG_LEVELS(s).name, nargs='?', choices=LOG_LEVELS.choices())
    parser.add_argument('--config-file', '-cf', default=CAMERA_CONFIG_FILE)
    args = parser.parse_args(cl_args)

    LOGGER.setLevel(args.log_level)
    logging.getLogger("tmv.util").setLevel(args.log_level)
    logging.getLogger("tmv.buttons").setLevel(args.log_level)
    logging.basicConfig(format=LOG_FORMAT, level=args.log_level)

    try:
        ensure_config_exists(args.config_file)
        global interface_camera  # pylint: disable=global-statement
        LOGGER.info(f"config from {args.config_file}")
        interface_camera.default_buttons_config(config_dir=Path(args.config_file).parent)
        interface_camera.config(args.config_file)
        start_threads()
        socketio.run(app,host="0.0.0.0")
        while True:
            sleep(1)

    except (FileNotFoundError, TomlDecodeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    except Exception as exc:  # pylint: disable=broad-except
        print(exc, file=sys.stderr)
        return 1



def buttons_console(cl_args=sys.argv[1:]):
    try:
        parser = argparse.ArgumentParser(
            "Check and control TMV buttons.")
        parser.add_argument('-c', '--config-file', default=CAMERA_CONFIG_FILE)
        parser.add_argument('-v', '--verbose', action="store_true")
        parser.add_argument('-r', '--restart', action="store_true", help="restart service to (e.g.) re-read config")
        parser.add_argument('mode', type=OnOffAuto, choices=list(OnOffAuto), nargs="?")
        parser.add_argument('speed', type=Speed, choices=list(Speed), nargs="?")
        args = (parser.parse_args(cl_args))

        if args.verbose:
            print(args)

        ensure_config_exists(args.config_file)

        c = Camera(camera_firmness=SOFTWARE, buttons_firmness=HARDWARE)
        c.default_buttons_config(config_dir=Path(args.config_file).parent)
        
        c.config(args.config_file)

        if args.verbose:
            print(c.mode_button)
            print(c.speed_button)

        if args.mode:
            try:
                c.mode_button.value = args.mode
            except ButtonError as e:
                print(e)
        else:
            print(c.mode_button.value)

        if args.speed:
            try:
                c.speed_button.value = args.speed
            except ButtonError as e:
                print(e)
        else:
            print(c.speed_button.value)

        if args.restart:
            if args.verbose:
                print("Restarting camera")
            ctlr = Unit("tmv-camera.service")
            ctlr.restart()
        exit(0)

    except PermissionError as exc:
        print(f"{exc}: check your file access permissions. Try root.", file=sys.stderr)
        if args.verbose:
            raise  # to get stack trace
        exit(10)
    except CalledProcessError as exc:
        print(f"{exc}: check your execute systemd permissions. Try root.", file=sys.stderr)
        if args.verbose:
            raise  # to get stack trace
        exit(20)
    # except Exception as exc:
    #    print(exc, file=stderr)
    #    if args.verbose:
    #        raise  # to get stack trace
    #
    #     exit(30)


if __name__ == '__main__':
    breakpoint()
    interface_console(sys.argv[1:])
