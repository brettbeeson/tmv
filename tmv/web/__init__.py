from pkg_resources import resource_filename
from flask import Flask, send_from_directory
from flask_socketio import SocketIO, emit #, Namespace
from cam_config import CameraConfig

import os

socketio = SocketIO()
cam_config = CameraConfig()
#status_thread = None

def create_app(config_file):
    
    global cam_config
    
    if os.path.isabs(config_file):
        cf =config_file
    else:
        cf = resource_filename("tmv", 'resources/' + config_file)
    
    cam_config.config(cf)
    
   # status_thread = Thread(target=broadcast_status)
   # status_thread.start()
   # image_thread = Thread(target=broadcast_image_thread)
   # image_thread.start()

    app = Flask("tmv")
    #app = Flask(__name__,static_url_path="/")  # default to folder: /static
    app.config['SECRET_KEY'] = 'secret'
    socketio.init_app(app)

    return app