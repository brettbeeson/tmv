import sys
from pathlib import Path
from threading import Thread
from base64 import b64encode
from time import sleep
from shutil import copy
from toml import loads
from flask_socketio import Namespace, emit
#from flask import Flask, send_from_directory
#from pkg_resources import resource_filename
from tmv.camera import DFLT_CAMERA_CONFIG_FILE

from tmv.util import run_and_capture, unlink_safe, Tomlable
from tmv.systemd import Unit
from tmv.switch import get_switch, OnOffAuto

def report_errors(func):
    """ My first decorator: try errors and report to client. Not rul securz """
    def wrappers(*args, **kwargs):
        try:
            func(*args, **kwargs)
        except Exception as exc:
            print("report_errors")
            emit('warning', f"Error: {exc}")
    return wrappers

class Server(Namespace, Tomlable):
    """ Flask-based web and websocket server to configure camera """

    def __init__(self):
        super().__init__()
        self.file_root = Path(".")
        self.camera_switch = None
        self.upload_switch = None
        self.latest_image = None
        self.status_thread = None

        self.status_thread = Thread(target=self.broadcast_status, args=(self,))
        self.status_thread.start()
        self.image_thread = Thread(target=self.broadcast_image_thread, args=(self,))
        self.image_thread.start()

    def configd(self, config_dict):
        self.camera_switch = get_switch(config_dict['camera'])
        self.upload_switch = get_switch(config_dict['upload'])
        self.file_root = Path(config_dict['camera']['file_root'])
        self.latest_image = self.file_root / config_dict['camera'].get('latest_image', 'latest-image.jpg')

    def send_image(self, broadcast, binary=True):
        self.socketio.emit('message', f"Sending image {self.latest_image}")
        with self.latest_image.open(mode='rb') as f:
            image_data_bin = f.read()
        if binary:
            emit('image', {'src-bin': image_data_bin}, broadcast=True)
        else:
            image_data_b64 = b64encode(image_data_bin)
            emit('image', {'src-b64': image_data_b64.decode('utf-8')}, broadcast=broadcast)
        emit('message', f"New image sent: {self.latest_image}")

    def broadcast_image_thread(self):
        """
        Poll / watch for new image and send to all clients
        """
        image_mtime_was = None
        image_mtime_is = None
        while True:
            sleep(1)
            if self.latest_image:
                try:
                    image_mtime_is = self.latest_image.stat().st_mtime
                    if image_mtime_was is None or image_mtime_is > image_mtime_was:
                        self.send_image(broadcast=True)
                        image_mtime_was = image_mtime_is
                except FileNotFoundError as exc:
                    emit('warning', f"{self.latest_image}: {repr(exc)}")
                    print(exc, file=sys.stderr)

    def broadcast_status(self):
        camera_was = None
        upload_was = None
        while True:
            sleep(1)
            
            camera_is = self.camera_switch.position
            if camera_was is None or camera_is != camera_was:
                emit('switches', {'message': "Camera switched", 'camera': str(camera_is)})
                camera_was = camera_is
        
            upload_is = self.upload_switch.position
            if upload_was is None or upload_is != upload_was:
                emit('switches', {'message': "Upload switched", 'upload': str(upload_is)})
                upload_was = upload_is

    @report_errors
    def on_req_services_status(self):
        cam = Unit("tmv-camera.service")
        ul = Unit("tmv-upload.service")
        services = {           
            str(cam): cam.status(),
            str(ul): ul.status(),
        }
        emit("services_status", {"message": "Read service statuses", "services": services})


    @report_errors
    def on_restart(self):
        cam = Unit("tmv-camera.service")
        ul = Unit("tmv-upload.service")
        cam.restart()
        ul.restart()
        sleep(5)
        self.on_req_services_status()

    @report_errors
    def on_req_journal(self):
        lines = 100
        so, se = run_and_capture(["journalctl", "-u", "tmv*", "-n", str(lines)])
        emit("journal", {"journal": so + se})

    @report_errors
    def on_req_files(self):
        if self.file_root:
            fls = []
            for f in self.file_root.glob("*"):
                fls.append(str(f))
            emit("files", {"files": fls})

    @report_errors
    def on_camera_switch(self, position):  
        self.camera_switch = OnOffAuto(position.lower())

    def on_upload_switch(self, position):  
        self.upload_switch = OnOffAuto(position.lower())

    @report_errors
    def on_req_camera_switch(self):
        emit('camera_switch', str(self.camera_switch.position))

    @report_errors
    def on_req_upload_switch(self):
        emit('upload_switch', str(self.upload_switch.position))

    @report_errors
    def on_req_camera_config(self):
        print("camera_config requested")
        config_path = Path("/etc/tmv/camera.toml")
        emit('camera_config', {'toml': config_path.read_text()})

    @report_errors
    def on_raise_error(self):
        raise RuntimeError("Yes, Jim, it's a fucking error you moron.")
    
    @report_errors
    def on_camera_config(self, configs):
        loads(configs)  # check syntax
        cf = DFLT_CAMERA_CONFIG_FILE
        unlink_safe(cf + ".bak")
        copy(cf, cf + ".bak")
        Path(cf).write_text(configs)
        # re-read this ourselves, too, to get new file_root, etc
        self.config(cf)
        emit("message", "Saved config. (Consider a restart)")

    def on_connect(self):
        print("Client connected!")
        emit('message', 'Connected.')
        self.send_image(broadcast=False)