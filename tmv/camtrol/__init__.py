from flask import Flask, send_from_directory
from flask_socketio import SocketIO
from tmv.camtrol.server import Server
from tmv.camera import DFLT_CAMERA_CONFIG_FILE

# Set this variable to "threading", "eventlet" or "gevent" to test the
# different async modes, or leave it set to None for the application to choose
# the best option based on installed packages.
async_mode = None

# create_app()
app = Flask(__name__,static_url_path="/")  # , instance_relative_config=True)
app.config.from_mapping(
    SECRET_KEY="adev",
)
socketio = SocketIO(app, host="0.0.0.0")
server = Server()
server.config(DFLT_CAMERA_CONFIG_FILE)
socketio.on_namespace(server)


@app.route('/')
def index():
    """ Serve index """
    #return send_from_directory(resource_filename(__name__, 'resources/'), "index.html")
    return send_from_directory("static","index.html")
    
#@app.route('/<path:path>')
#def static_files(path):
    #""" Serve resources (js, etc) """
    # return send_from_directory(resource_filename(__name__, 'resources/'), path)
    #return path
