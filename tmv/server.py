#!/usr/bin/env python
from pathlib import Path
from threading import Thread
from subprocess import CalledProcessError
from time import sleep
from shutil import copy
from flask import Flask, send_from_directory
from flask_socketio import SocketIO, emit
from pkg_resources import resource_filename
from tmv.camera import DFLT_CAMERA_CONFIG_FILE
from tmv.controller import Switches, OnOffAuto, Unit, Controller
from tmv.util import run_and_capture, unlink_safe, Tomlable
from toml import loads, TomlDecodeError

# Set this variable to "threading", "eventlet" or "gevent" to test the
# different async modes, or leave it set to None for the application to choose
# the best option based on installed packages.
async_mode = None

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, host="0.0.0.0")
status_thread = None
server = None


class Server(Tomlable):
    """ Proxy-style to read camera config and remember file locations """

    def __init__(self):
        self.file_root = "."
        self.switches = None

    def configd(self, config_dict):
        self.switches = Switches()
        self.switches.configd(config_dict)  # [controlller]
        self.file_root = config_dict['camera']['file_root']


def report_errors(func):
    """ My first decorator: try errors and report to client. Not rul securz """
    def wrappers(*args, **kwargs):
        try:
            func(*args, **kwargs)
        except Exception as exc:
            print("report_errors")
            emit('warning', f"Error: {exc}")
    return wrappers


def broadcast_status():
    camera_was = None
    upload_was = None
    while True:
        sleep(1)
        if (server):
            ss = server.switches
            camera_is = ss['camera']
            if camera_was is None or camera_is != camera_was:
                socketio.emit('switches', {'message': "Camera switched", 'camera': str(camera_is)})
                camera_was = camera_is
            upload_is = ss['upload']
            if upload_was is None or upload_is != upload_was:
                socketio.emit('switches', {'message': "Upload switched", 'upload': str(upload_is)})
                upload_was = upload_is


@app.route('/')
def index():
    """ Serve index """
    return send_from_directory(resource_filename(__name__, 'resources/'), "index.html")


@app.route('/<path:path>')
def static_files(path):
    """ Serve resources (js, etc) """
    return send_from_directory(resource_filename(__name__, 'resources/'), path)


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
    emit("message",f"tmv-controller: {ctlr.status()}")
    

@socketio.on('req-journal')
@report_errors
def req_journal():
    lines = 100
    so, se = run_and_capture(["journalctl", "-u", "tmv*", "-n", str(lines)])
    emit("journal", {"journal": so + se})


@socketio.on('req-files')
@report_errors
def req_files():
    if server:
        fls = []
        for f in Path(server.file_root).glob("*"):
            fls.append(str(f))
        emit("files", {"files": fls})


@socketio.on('switches')
@report_errors
def set_switches(positions):
    if server and server.switches:
        for s_name, s_pos in positions.items():
            server.switches[s_name] = OnOffAuto(s_pos.lower())
    else:
        raise RuntimeError("No switches available")
    

@socketio.on('req-switches')
@report_errors
def req_switches():
    if server:
        emit('switches', {'camera': str(server.switches['camera']), 'upload': str(server.switches['upload'])})


@socketio.on('req-camera-config')
@report_errors
def req_camera_config():
    print("camera-config requested")
    config_path = Path("/etc/tmv/camera.toml")
    emit('camera-config', {'toml': config_path.read_text()})
    

@socketio.on('camera-config')
@report_errors
def camera_config(configs):
    if server:
        loads(configs)  # check syntax
        cf = DFLT_CAMERA_CONFIG_FILE
        unlink_safe(cf + ".bak")
        copy(cf, cf + ".bak")
        Path(cf).write_text(configs)
        # re-read this ourselves, too, to get new file_root, etc
        server.config(cf)
        emit("message","Saved config. (Consider a restart)")

    

@socketio.on('connect')
def connect():
    print("Client connected!")
    emit('message', 'Connected.')

try:
    server = Server()
    server.config(DFLT_CAMERA_CONFIG_FILE)
except (FileNotFoundError, TomlDecodeError) as exc:
    print(exc)
    

status_thread = Thread(target=broadcast_status)
status_thread.start()

    

@app.before_first_request
def start_status_broadcast():
    pass
# if __name__ == '__main__':
    # socketio.run(app, host="0.0.0.0", debug=True)
