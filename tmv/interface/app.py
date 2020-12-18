#!/usr/bin/env python3
# pylint: disable=line-too-long, logging-fstring-interpolation, dangerous-default-value, logging-not-lazy


import sys
from os import system
from pathlib import Path
from base64 import b64encode
from time import sleep
from shutil import copy
import argparse
from datetime import datetime as dt             # dt = class
from subprocess import CalledProcessError
import logging
from socket import gethostname, gethostbyname

from debugpy import breakpoint
from flask_socketio import emit, SocketIO
from flask import Flask, send_from_directory
from toml import loads, TomlDecodeError

from tmv.camera import CAMERA_CONFIG_FILE
from tmv.camera import Interface
from tmv.buttons import OnOffAuto, Speed
from tmv.systemd import Unit
from tmv.util import run_and_capture, unlink_safe, LOG_LEVELS, LOG_FORMAT, ensure_config_exists
from tmv.exceptions import ButtonError
from tmv.interface.wifi import scan, reconfigure

LOGGER = logging.getLogger("tmv.interface")

app = Flask("tmv.interface.app", static_url_path="/", static_folder="static")
app.config['SECRET_KEY'] = 'secret!'
app.config["EXPLAIN_TEMPLATE_LOADING"] = True
interface = Interface()
socketio = SocketIO(app)
shutdown = False


def report_errors(func):
    """ "try"  and report to client. Not rul securz """
    def wrappers(*args, **kwargs):
        try:
            func(*args, **kwargs)
        except Exception as exc:  # pylint: disable=broad-except
            emit('warning', f"Error: {exc}")
    return wrappers


def send_image(broadcast, binary=True):
    if interface is None or interface.latest_image is None or not Path(interface.latest_image).exists():
        return
    im = Path(interface.latest_image)
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

    while not shutdown:
        sleep(1)


def broadcast_image_thread():
    """
    Poll / watch for new image and send to all clients
    """
    image_mtime_was = None
    image_mtime_is = None
    while not shutdown:
        sleep(1)
        # breakpoint()
        try:
            if interface:
                im = Path(interface.latest_image)
                if im.exists():
                    image_mtime_is = im.stat().st_mtime
                    if image_mtime_was is None or image_mtime_is > image_mtime_was:
                        send_image(broadcast=True)
                        image_mtime_was = image_mtime_is
                        # socketio.emit('message', f"New image sent: {interface.latest_image}")
        except FileNotFoundError as exc:
            socketio.emit('warning', f"{interface.latest_image}: {repr(exc)}")
            print(exc, file=sys.stderr)


def broadcast_buttons_thread():
    mode_was = None
    speed_was = None
    while not shutdown:
        sleep(1)
        if interface:
            if interface.mode_button.ready():
                mode_is = interface.mode_button.value
                if mode_was is None or mode_is != mode_was:
                    socketio.emit('message', f"Mode changed to {mode_is}")
                    #socketio.emit('mode', str(mode_is))
                    req_mode()
                    mode_was = mode_is

            if interface.speed_button.ready():
                speed_is = interface.speed_button.value
                if speed_was is None or speed_is != speed_was:
                    socketio.emit('message', f"speed changed to {speed_is}")
                    req_speed()
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
    emit("message", "Warning: services status is not reliable")


@socketio.on('restart-camera')
@report_errors
def restart_service():
    ctlr = Unit("tmv-camera.service")
    emit("message", "Restarting camera.")
    ctlr.restart()
    sleep(3)
    emit("message", f"Camera status: {ctlr.status()}")


@socketio.on('req-journal')
@report_errors
def req_journal():
    lines = 100
    so, se = run_and_capture(["journalctl", "-u", "tmv*", "-n", str(lines)])
    emit("journal", so + se)


@socketio.on('req-files')
@report_errors
def req_files():
    fls = []
    for f in Path(interface.file_root).glob("*"):
        if f.is_file():
            fls.append(str(f))
    fls.sort()
    emit("n-files", len(fls))
    emit("files", fls)


@socketio.on('req-latest-image-time')
@report_errors
def req_latest_image_time():
    ts = interface.latest_image.stat().st_mtime
    mt = dt.fromtimestamp(ts)
    mt_str = mt.isoformat()
    emit("latest-image-time", mt_str)
    #td = dt.now() - mt
    # emit("latest-image-ago", f"{naturaldelta(td)} ago")


@socketio.on('req-n-files')
@report_errors
def req_n_files():
    i = len(Path(interface.file_root).glob("*"))
    emit("n-files", i)


@socketio.on('mode')
@report_errors
def set_mode(pos: str):
    if interface and interface.mode_button:
        interface.mode_button.value = OnOffAuto(pos.lower())
        interface.mode_button.set_LED()
    else:
        raise RuntimeError("No button available")


@socketio.on('req-mode')
@report_errors
def req_mode():
    socketio.emit('mode', str(interface.mode_button.value))


@socketio.on('speed')
@report_errors
def set_speed(pos: str):
    if interface and interface.speed_button:
        interface.speed_button.value = Speed(pos.lower())
        interface.speed_button.set_LED()
    else:
        raise RuntimeError("No button available")


@socketio.on('req-speed')
@report_errors
def req_speed():
    socketio.emit('speed', str(interface.speed_button.value))


@socketio.on('raise-error')
@report_errors
def raise_error():
    raise RuntimeError("What did you expect?")


@socketio.on('req-camera-config')
@report_errors
def req_camera_config():
    config_path = interface.config_path
    if config_path is None:
        raise RuntimeError("No config path available")
    else:
        emit('camera-config', config_path.read_text())


@socketio.on('req-camera-name')
@report_errors
def req_camera_name():
    emit('camera-name', gethostname())
#    emit('message', f"hostname: {gethostname()}")


@socketio.on('req-camera-ip')
@report_errors
def req_camera_ip():
    emit('camera-ip', gethostbyname(gethostname()))
#    emit('message', f"IP: {gethostbyname(gethostname())}")


@socketio.on('restart-hw')
@report_errors
def restart_hw():
    emit('message', 'Restarting in 60s')
    system("sudo shutdown -r 1")
    sleep(50)
    emit('message', 'Restarting')


@socketio.on('shutdown-hw')
@report_errors
def shutdown_hw():
    emit('message', 'Shutdown in 60s')
    system("sudo shutdown 1")
    sleep(55)
    emit('message', 'Shutting down')


@socketio.on('cancel-shutdown')
@report_errors
def cancel_shutdown():
    system("sudo shutdown -c")
    emit('message', 'Shutdown cancelled')


@socketio.on('camera-config')
@report_errors
def camera_config(configs):
    if interface:
        loads(configs)  # check syntax
        cf = interface.config_path
        unlink_safe(cf.with_suffix(".bak"))
        copy(cf, cf.with_suffix(".bak"))
        Path(cf).write_text(configs)
        # re-read this ourselves, too, to get new file_root, etc
        interface.config(cf)
        emit("message", "Saved config.")


@socketio.on('req-wpa-supplicant')
@report_errors
def req_wpa_supplicant():
    emit('wpa-supplicant', Path("/etc/wpa_supplicant/wpa_supplicant.conf").read_text())


@socketio.on('wpa-supplicant')
@report_errors
def wpa_supplicant(wpa_supplicant_text):
    fn = Path("/etc/wpa_supplicant/wpa_supplicant.conf")
    fn.write_text(wpa_supplicant_text)
    emit('message', f"Saved to {fn}. Consider a reconfigure.")


@socketio.on('wpa-reconfigure')
@report_errors
def wpa_reconfigure():
    result = reconfigure()
    emit('message', f"Reconfiguring: {result}")


@socketio.on('req-wpa-scan')
@report_errors
def req_wpa_scan():
    s = scan()
    LOGGER.warning(s)
    emit('wpa-scan', s)


@socketio.on('connect')
@report_errors
def connect():
    emit('message', 'Hello from TMV!')
    try:
        send_image(broadcast=False)
        req_mode()
        req_speed()
        req_wpa_supplicant()
    except FileNotFoundError:
        pass


def start_threads():
    socketio.threads = []
    socketio.threads.append(socketio.start_background_task(manage_screen_interface_thread))
    socketio.threads.append(socketio.start_background_task(broadcast_buttons_thread))
    socketio.threads.append(socketio.start_background_task(broadcast_image_thread))


def interface_console(cl_args=sys.argv[1:]):
    parser = argparse.ArgumentParser("Interface (screen, web, web-socket server) to TMV interface.")
    parser.add_argument('--log-level', '-ll', default='WARNING', type=lambda s: LOG_LEVELS(s).name, nargs='?', choices=LOG_LEVELS.choices())
    parser.add_argument('--port', '-p', default=5000, type=int)
    parser.add_argument('--config-file', '-cf', default=CAMERA_CONFIG_FILE)
    args = parser.parse_args(cl_args)

    LOGGER.setLevel(args.log_level)
    logging.getLogger("tmv.util").setLevel(args.log_level)
    logging.getLogger("tmv.buttons").setLevel(args.log_level)
    logging.basicConfig(format=LOG_FORMAT)
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.WARNING)

    try:
        ensure_config_exists(args.config_file)
        global interface  # pylint: disable=global-statement
        LOGGER.info(f"config file: {Path(args.config_file).absolute()}")
        interface.config(args.config_file)
        interface.illuminate()
        start_threads()
        socketio.run(app, host="0.0.0.0", port=args.port, debug=True)
        while True:
            sleep(1)

    except (FileNotFoundError, TomlDecodeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt as exc:
        return 0
    except Exception as exc:  # pylint: disable=broad-except
        print(exc, file=sys.stderr)
        return 1
    finally:
        LOGGER.info("Stopping server and threads")
        global shutdown  # pylint:disable = global-statement
        shutdown = True


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

        c = Interface()
        c.config(args.config_file)
        c.illuminate()

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
