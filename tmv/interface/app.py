#!/usr/bin/env python3
# pylint: disable=line-too-long, logging-fstring-interpolation, dangerous-default-value, logging-not-lazy, global-statement

"""
A Flask application with:
- SocketIO communication (e.g. javascript can subscribe to photo updates)
- HTML/JS server for single page app showing TMV
- Doesn't run a camera
"""
import signal
import sys
from sys import exc_info, stderr, argv
from os import system
from pathlib import Path
from base64 import b64encode
import threading
from time import sleep
from shutil import copy
import argparse
from datetime import datetime as dt
import logging
from socket import gethostname, gethostbyname
import debugpy
from flask_socketio import emit, SocketIO
from flask import Flask, send_from_directory, Response
from toml import loads, TomlDecodeError

from tmv.camera import CAMERA_CONFIG_FILE
from tmv.interface.interface import Interface
from tmv.buttons import OnOffAutoVideo, Speed
from tmv.systemd import Unit
from tmv.util import run_and_capture, unlink_safe, LOG_LEVELS, LOG_FORMAT, ensure_config_exists
from tmv.exceptions import PiJuiceError
from tmv.interface.wifi import scan, reconfigure, info
from tmv.video_camera import VideoCamera

LOGGER = logging.getLogger("tmv.interface")

try:
    from tmv.tmvpijuice import TMVPiJuice, pj_call
except (ImportError, NameError) as e:
    LOGGER.warning(f"No PiJuice available: {e}")

#
# globals
# - flask seems easiest to arrange with 'app' global which
#
app = Flask("tmv.interface.app", static_url_path="/", static_folder="static")
app.config['SECRET_KEY'] = 'secret!'
app.config["EXPLAIN_TEMPLATE_LOADING"] = True
interface = Interface()
socketio = SocketIO(app)

shutdown = False    # socketio threads: required?


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


def broadcast_pijuice_status_thread():
    while not shutdown:
        socketio.sleep(60)
        req_pj_status()


def broadcast_image_thread():
    """
    Poll / watch for new image and send to all clients
    """
    image_mtime_was = None
    image_mtime_is = None
    while not shutdown:
        socketio.sleep(1)
        try:
            if interface and interface.latest_image:
                im = Path(interface.latest_image)
                if im.exists():
                    image_mtime_is = im.stat().st_mtime
                    if image_mtime_was is None or image_mtime_is > image_mtime_was:
                        send_image(broadcast=True)
                        image_mtime_was = image_mtime_is

        except FileNotFoundError as exc:
            socketio.emit('warning', f"{interface.latest_image}: {repr(exc)}")
            socketio.sleep(10)
            LOGGER.warning(exc)


def broadcast_buttons_thread():
    mode_was = None
    speed_was = None
    global interface
    while not shutdown:
        socketio.sleep(1)  # not time.sleep()
        if interface and interface.mode_button:
            if interface.mode_button.ready():
                mode_is = interface.mode_button.value
                if mode_was is None or mode_is != mode_was:
                    LOGGER.debug(f"Mode changed to {mode_is}")
                    interface.poke()
                    req_mode()
                    mode_was = mode_is

        if interface and interface.speed_button:
            if interface.speed_button.ready():
                speed_is = interface.speed_button.value
                if speed_was is None or speed_is != speed_was:
                    LOGGER.debug(f"speed changed to {speed_is}")
                    interface.poke()
                    req_speed()
                    speed_was = speed_is


# Serve the single page app
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route('/<path:path>')
def send_static(path):
    return send_from_directory('static', path)


@socketio.on('req-services-status')
@report_errors
def services_status():
    cl = Unit("tmv-interface.service")
    cam = Unit("tmv-camera.service")
    ul = Unit("tmv-upload.service")
    services = {
        str(cl): cl.status(),
        str(cam): cam.status(),
        str(ul): ul.status(),
    }
    emit("services-status", services)


@socketio.on('restart-camera')
@report_errors
def restart_service():
    c = Unit("tmv-camera.service")
    u = Unit("tmv-upload.service")
    i = Unit("tmv-interface.service")
    emit("message", "Restarting all services.")
    c.restart()
    u.restart()
    sleep(3)
    emit("message", f"Camera status: {c.status()}")
    emit("message", f"Upload status: {u.status()}")
    i.restart()


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
    for f in Path(interface.tmv_root).glob("**/*.jpg"):
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


@socketio.on('req-n-files')
@report_errors
def req_n_files():
    emit("n-files", interface.n_images())


@socketio.on('mode')
@report_errors
def set_mode(pos: str):
    if interface and interface.mode_button:
        interface.mode_button.value = OnOffAutoVideo(pos.lower())
        interface.mode_button.set_LED()
    else:
        raise RuntimeError("No button available")


@socketio.on('req-mode')
@report_errors
def req_mode():
    LOGGER.debug(f"emitting mode: {str(interface.mode_button.value)}")
    socketio.emit('mode', str(interface.mode_button.value))


@socketio.on('speed')
@report_errors
def set_speed(pos: str):
    if interface and interface.speed_button:
        interface.speed_button.value = Speed(pos.lower())
    else:
        raise RuntimeError("No button available")


@socketio.on('req-speed')
@report_errors
def req_speed():
    socketio.emit('speed', str(interface.speed_button.value))


@socketio.on('req-camera-interval')
@report_errors
def req_camera_info():
    socketio.emit('camera-interval', f"{interface.interval.total_seconds():.0f}")


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
        emit('camera-config', config_path.read_text(encoding='utf-8'))


@socketio.on('req-camera-name')
@report_errors
def req_camera_name():
    emit('camera-name', gethostname())


@socketio.on('req-camera-ip')
@report_errors
def req_camera_ip():
    emit('camera-ip', gethostbyname(gethostname()))


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
    loads(configs)  # check syntax
    cf = interface.config_path
    unlink_safe(cf.with_suffix(".bak"))
    copy(cf, cf.with_suffix(".bak"))
    Path(cf).write_text(configs)
    # re-read this ourselves, too, to get new tmv_root, etc
    interface.config(cf)
    emit("message", "Saved config.")


@socketio.on('req-wpa-supplicant')
@report_errors
def req_wpa_supplicant():
    emit('wpa-supplicant', Path("/etc/wpa_supplicant/wpa_supplicant.conf").read_text(encoding='utf-8'))


@socketio.on('wpa-supplicant')
@report_errors
def wpa_supplicant(wpa_supplicant_text):
    fn = Path("/etc/wpa_supplicant/wpa_supplicant.conf")
    fn.write_text(wpa_supplicant_text, encoding='utf-8')
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


@socketio.on('req-network-info')
@report_errors
def req_network_info():
    network_info = info()
    emit('network-info', network_info)


@socketio.on('connect')
#@report_errors
def connect():
    emit('message', 'Hello from TMV!')
    try:
        send_image(broadcast=False)
        req_mode()
        req_speed()
        req_wpa_supplicant()
        if interface.has_pijuice:
            req_pj_status()
    except FileNotFoundError:
        pass


@socketio.on('req-pj-status')
@report_errors
def req_pj_status():
    """Get pijuice information and return as json"""
    try:
        tmv_pj = TMVPiJuice()
        s = pj_call(tmv_pj.status.GetStatus)
        s['chargeLevel'] = pj_call(tmv_pj.status.GetChargeLevel)
        s['batteryVoltage'] = pj_call(tmv_pj.status.GetBatteryVoltage)
        s['batteryCurrent'] = pj_call(tmv_pj.status.GetBatteryCurrent)
        s['ioVoltage'] = pj_call(tmv_pj.status.GetIoVoltage)
        s['ioCurrent'] = pj_call(tmv_pj.status.GetIoCurrent)
        s['wakeupOnCharge'] = pj_call(tmv_pj.power.GetWakeUpOnCharge)
        #LOGGER.debug(s)
        socketio.emit('pj-status', s)
    except (NameError, PiJuiceError) as e:
        LOGGER.warning(e)
        LOGGER.debug(e, exc_info=e)

#
# Video
#


def gen(camera):
    """Video streaming generator function."""
    while True:
        frame = camera.get_frame()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')


@app.route('/video')
def video_feed():
    """Video streaming route. Put this in the src attribute of an img tag."""
    return Response(gen(VideoCamera(interface, socketio)),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/hidescreen')
def screen_down():
    interface.screen._display.hide()
    return Response("ok")


def stop_server(signum, _):
    LOGGER.info(f"Caught {signal.Signals(signum).name}. Stopping server.")
    socketio.stop()


def interface_console(cl_args=argv[1:]):
    """
    Run without gunicorn in development mode. 
    """
    parser = argparse.ArgumentParser("Interface (screen, web, web-socket server) to TMV interface.")
    parser.add_argument('--log-level', '-ll', default='WARNING', type=lambda s: LOG_LEVELS(s).name, nargs='?', choices=LOG_LEVELS.choices())
    parser.add_argument('--config-file', '-cf', default='/etc/tmv/' + CAMERA_CONFIG_FILE)
    parser.add_argument("--debug", default=False, action='store_true')
    args = parser.parse_args(cl_args)

    global interface  # pylint: disable=global-statement

    logging.basicConfig(format=LOG_FORMAT)
    logging.getLogger("tmv").setLevel(args.log_level)
    logging.getLogger('werkzeug').setLevel(logging.WARNING)  # turn off excessive logs (>=WARNING is ok)

    signal.signal(signal.SIGINT, stop_server)
    signal.signal(signal.SIGTERM, stop_server)

    try:
        if args.debug:
            debug_port = 5678
            debugpy.listen(("0.0.0.0", debug_port))
            print(f"Waiting for debugger attach on {debug_port}")
            debugpy.wait_for_client()
            debugpy.breakpoint()

        ensure_config_exists(args.config_file)
        LOGGER.info(f"Using config file: {Path(args.config_file).absolute()}")
        interface.config(args.config_file)

        # reset to cli values, which override config file
        if args.log_level != 'WARNING':  # str comparison
            logging.getLogger("tmv").setLevel(args.log_level)

        # let's roll!
        LOGGER.info(f"Starting socketio threads")
        start_socketio_threads()
        LOGGER.info(f"Starting flask and socketio at 0.0.0.0:{interface.port}")
        socketio.run(app, host="0.0.0.0", port=interface.port, debug=(args.log_level == logging.DEBUG))

    except (FileNotFoundError, TomlDecodeError) as exc:
        LOGGER.debug(exc, exc_info=exc)
        print(exc, file=stderr)
        return 1
    except KeyboardInterrupt as exc:
        LOGGER.debug(exc, exc_info=exc)
        print(exc, file=stderr)
        return 0
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.debug(exc, exc_info=exc)
        print(exc, file=stderr)
        return 1
    finally:
        LOGGER.info("Stopping server and threads")
        # use a thread event?
        global shutdown  # pylint:disable = global-statement
        shutdown = True
        if interface:
            interface.stop()
        sleep(2)  # allow to stop nicely


def start_socketio_threads():
    socketio.start_background_task(target=broadcast_buttons_thread)  # hangs (with eventlet?) so use std threads
    socketio.start_background_task(target=broadcast_image_thread)
    if interface.has_pijuice:
        socketio.start_background_task(target=broadcast_pijuice_status_thread)


if __name__ == '__main__':
    sys.exit(interface_console())
