import logging
from flask import Flask, send_from_directory
from flask_socketio import SocketIO
from tmv.server import Server
from tmv.camera import DFLT_CAMERA_CONFIG_FILE

# Set this variable to "threading", "eventlet" or "gevent" to test the
# different async modes, or leave it set to None for the application to choose
# the best option based on installed packages.
async_mode = None

# create_app()
app = Flask(__name__,static_url_path="/")  # default to folder: /static

app.config.from_mapping(
    SECRET_KEY="moose",
)
log = logging.getLogger('werkzeug')
log.setLevel(logging.WARNING)

socketio = SocketIO(app, host="0.0.0.0")
server = Server()
server.config(DFLT_CAMERA_CONFIG_FILE)
socketio.on_namespace(server)


@app.route('/')
def index():
    """ Serve index. Others from default /static """
    return send_from_directory("static","index.html")
