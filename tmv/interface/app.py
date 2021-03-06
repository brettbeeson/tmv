#!/usr/bin/env python3
# pylint: disable=line-too-long, logging-fstring-interpolation, dangerous-default-value, logging-not-lazy, global-statement
from sys import stderr, argv
from os import system
from pathlib import Path
from base64 import b64encode
from time import sleep
from shutil import copy
import argparse
from datetime import datetime as dt, timedelta             # dt = class
from subprocess import CalledProcessError
import logging
from socket import gethostname, gethostbyname

from debugpy import breakpoint
from flask_socketio import emit, SocketIO
from flask import Flask, send_from_directory, Response
from toml import loads, TomlDecodeError

from tmv.camera import CAMERA_CONFIG_FILE
from tmv.camera import Interface
from tmv.buttons import OnOffAuto, Speed
from tmv.systemd import Unit
from tmv.util import run_and_capture, unlink_safe, LOG_LEVELS, LOG_FORMAT, ensure_config_exists
from tmv.exceptions import ButtonError, PiJuiceError
from tmv.interface.wifi import scan, reconfigure, info
from tmv.interface.screen import TMVScreen
from tmv.video_camera import VideoCamera

try:
    from tmv.tmvpijuice import TMVPiJuice, pj_call
except (ImportError, NameError) as e:
    print(e, file=stderr)

LOGGER = logging.getLogger("tmv.interface")

app = Flask("tmv.interface.app", static_url_path="/", static_folder="static")
app.config['SECRET_KEY'] = 'secret!'
app.config["EXPLAIN_TEMPLATE_LOADING"] = True
interface = Interface()
socketio = SocketIO(app)
shutdown = False
next_screen_refresh = dt.max


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
    global next_screen_refresh

    refresh_period = timedelta(seconds=60)
    screen = TMVScreen(interface)

    while not shutdown:
        if dt.now() > next_screen_refresh:
            screen.update_display()
            next_screen_refresh = dt.now() + refresh_period
            #LOGGER.debug(f"next refresh is {next_screen_refresh.isoformat()}")
        else:
            sleep(1)


def broadcast_pijuice_status_thread():
    while not shutdown:
        sleep(60)
        req_pj_status()


def broadcast_image_thread():
    """
    Poll / watch for new image and send to all clients
    """
    global next_screen_refresh
    image_mtime_was = None
    image_mtime_is = None
    while not shutdown:
        sleep(1)
        try:
            if interface:
                im = Path(interface.latest_image)
                if im.exists():
                    image_mtime_is = im.stat().st_mtime
                    if image_mtime_was is None or image_mtime_is > image_mtime_was:
                        send_image(broadcast=True)
                        image_mtime_was = image_mtime_is
                        #next_screen_refresh = dt.now() + timedelta(seconds=60)
        except FileNotFoundError as exc:
            socketio.emit('warning', f"{interface.latest_image}: {repr(exc)}")
            LOGGER.warning(exc)


def broadcast_buttons_thread():
    global next_screen_refresh
    mode_was = None
    speed_was = None
    while not shutdown:
        sleep(1)
        if interface and interface.mode_button:
            if interface.mode_button.ready():
                mode_is = interface.mode_button.value
                if mode_was is None or mode_is != mode_was:
                    LOGGER.debug(f"Mode changed to {mode_is}")
                    req_mode()
                    mode_was = mode_is
                    next_screen_refresh = dt.now() + timedelta(seconds=1)

        if interface and interface.speed_button:
            if interface.speed_button.ready():
                speed_is = interface.speed_button.value
                if speed_was is None or speed_is != speed_was:
                    LOGGER.debug(f"speed changed to {speed_is}")
                    req_speed()
                    speed_was = speed_is
                    next_screen_refresh = dt.now() + timedelta(seconds=1)


# index page
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

# all other paths - this is REQUIRED on some environments, others not!


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
    for f in Path(interface.file_root).glob("**/*.jpg"):
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
    emit("n-files", interface.n_images())


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


@socketio.on('req-network-info')
@report_errors
def req_network_info():
    network_info = info()
    emit('network-info', network_info)


@socketio.on('connect')
@report_errors
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
        LOGGER.info(s)
        socketio.emit('pj-status', s)
    except (NameError, PiJuiceError) as e:
        LOGGER.warning(e)
        LOGGER.debug(e, exc_info=e)

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


def start_threads():
    socketio.threads = []
    socketio.threads.append(socketio.start_background_task(manage_screen_interface_thread))
    socketio.threads.append(socketio.start_background_task(broadcast_buttons_thread))
    socketio.threads.append(socketio.start_background_task(broadcast_image_thread))
    if interface.has_pijuice:
        socketio.threads.append(socketio.start_background_task(broadcast_pijuice_status_thread))


def interface_console(cl_args=argv[1:]):
    parser = argparse.ArgumentParser("Interface (screen, web, web-socket server) to TMV interface.")
    parser.add_argument('--log-level', '-ll', default='WARNING', type=lambda s: LOG_LEVELS(s).name, nargs='?', choices=LOG_LEVELS.choices())
    parser.add_argument('--config-file', '-cf', default=CAMERA_CONFIG_FILE)
    args = parser.parse_args(cl_args)

    logging.basicConfig(format=LOG_FORMAT)
    logging.getLogger("tmv").setLevel(args.log_level)
    logging.getLogger('werkzeug').setLevel(logging.WARNING)  # turn off excessive logs (>=WARNING is ok)

    try:
        ensure_config_exists(args.config_file)
        global interface  # pylint: disable=global-statement
        LOGGER.info(f"config file: {Path(args.config_file).absolute()}")
        interface.config(args.config_file)
        interface.mode_button.illuminate()
        interface.speed_button.illuminate()

        # reset to cli values, which override config file
        if args.log_level != 'WARNING':  # str comparison
            logging.getLogger("tmv").setLevel(args.log_level)

        # let's roll!
        start_threads()
        socketio.run(app, host="0.0.0.0", port=interface.port, debug=(args.log_level == logging.DEBUG))
        while True:
            sleep(1)

    except (FileNotFoundError, TomlDecodeError) as exc:
        print(exc, file=stderr)
        return 1
    except KeyboardInterrupt as exc:
        return 0
    except Exception as exc:  # pylint: disable=broad-except
        print(exc, file=stderr)
        LOGGER.debug("Exiting", exc_info=exc)
        return 1
    finally:
        LOGGER.info("Stopping server and threads")
        global shutdown  # pylint:disable = global-statement
        shutdown = True


def buttons_console(cl_args=argv[1:]):
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
        c.mode_button.illuminate()
        c.speed_button.illuminate()

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
                print("Restarting camera and upload")
            ctlr = Unit("tmv-camera.service")
            ctlr.restart()
            ctlr = Unit("tmv-upload.service")
            ctlr.restart()

        exit(0)

    except PermissionError as exc:
        print(f"{exc}: check your file access permissions. Try root.", file=stderr)
        if args.verbose:
            raise  # to get stack trace
        exit(10)
    except CalledProcessError as exc:
        print(f"{exc}: check your execute systemd permissions. Try root.", file=stderr)
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
    interface_console(argv[1:])
