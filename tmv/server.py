#!/usr/bin/env python
from pathlib import Path
from threading import Thread
from time import sleep
from flask import Flask, send_from_directory
from flask_socketio import SocketIO, emit
from pkg_resources import resource_filename

from tmv.controller import Switches

# Set this variable to "threading", "eventlet" or "gevent" to test the
# different async modes, or leave it set to None for the application to choose
# the best option based on installed packages.
async_mode = None

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, host="0.0.0.0")


def broadcast_status():
    camera_was = None
    upload_was = None
    while True:
        sleep(1)
        ss = Switches()
        ss.configs(Switches.DLFT_SW_CONFIG)  # todo: read toml, put in constructor, poll
        camera_is = ss['camera'] 
        if camera_was is None or camera_is != camera_was:
            socketio.emit('switch-status', {'success': True, 'message': "Camera switched",'camera': str(camera_is)})
            camera_was = camera_is
        upload_is = ss['upload'] 
        if upload_was is None or upload_is != upload_was:
            socketio.emit('switch-status', {'success': True, 'message': "Upload switched",'upload': str(upload_is)})
            upload_was = upload_is

status_t = Thread(target=broadcast_status)
status_t.start()


@app.route('/')
def index():
    """ Serve index """
    return send_from_directory(resource_filename(__name__, 'resources/'), "index.html")


@app.route('/<path:path>')
def static_files(path):
    """ Serve resources (js, etc) """
    return send_from_directory(resource_filename(__name__, 'resources/'), path)

# raw echo
# @socketio.on('message')
# def on_message(message):
#    send(message)
#    return message


@socketio.on('switch-status')
def switch_status():
    ss = Switches()
    ss.configs(Switches.DLFT_SW_CONFIG)  # todo: read toml, put in constructor, poll
    emit('switch-status', {'success': True, 'message': "Status retrieved",
                           'camera': str(ss['camera']), 'upload': str(ss['upload'])})


@socketio.on('camera-config')
def camera_config():
    print("camera-config requested")
    config_path = Path("/etc/tmv/camera.toml")
    if config_path.is_file():
        emit('camera-config', {'success': True, 'message': "Config retrieved", 'toml': config_path.read_text()})
    else:
        emit('camera-config', {'success': True, 'message': f"No config file at {str(config_path)}"})


@socketio.on('connect')
def connect():
    print("Client connected!")
    emit('message', 'Connected!')


# if __name__ == '__main__':
    # socketio.run(app, host="0.0.0.0", debug=True)
