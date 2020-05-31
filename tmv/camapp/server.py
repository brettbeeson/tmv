import sys
from pathlib import Path
from threading import Thread
from base64 import b64encode
from time import sleep
from datetime import datetime  as dt, date 
import logging
from shutil import copy
from toml import loads
from flask_socketio import Namespace, emit
from tmv.camera import DFLT_CAMERA_CONFIG_FILE
from tmv.controller import Switches, OnOffAuto, Unit
from tmv.util import run_and_capture, unlink_safe, Tomlable, dt2str

LOGGER = logging.getLogger(__name__)

def report_errors(func):
    """ My first decorator: try errors and report to client. Not rul securz """
    def wrappers(*args, **kwargs):
        try:
            func(*args, **kwargs)
        except Exception as exc:
            LOGGER.warn(exc)
            emit('warning', f"Error: {exc}")
    return wrappers


class Server(Namespace, Tomlable):
    """ Flask-based web and websocket server to configure camera """

    def __init__(self):
        super().__init__()
        self.file_root = Path(".")
        self.switches = None
        self.latest_image = None
        self.status_thread = None

        self.status_thread = Thread(target=self.broadcast_status)
        self.status_thread.start()
        self.image_thread = Thread(target=self.broadcast_image_thread)
        self.image_thread.start()

    def configd(self, config_dict):
        self.switches = Switches()
        self.switches.configd(config_dict)  # [controlller]
        self.file_root = Path(config_dict['camera']['file_root'])
        self.latest_image = self.file_root / config_dict['camera'].get('latest_image', 'latest-image.jpg')

    def send_image(self, broadcast, binary=True):
        with self.latest_image.open(mode='rb') as f:
            image_data_bin = f.read()
        if binary:
            self.emit('image', {'src-bin': image_data_bin})  # , broadcast=True)
        else:
            image_data_b64 = b64encode(image_data_bin)
            self.emit('image', {'src-b64': image_data_b64.decode('utf-8')})  # , broadcast=broadcast)

    def broadcast_image_thread(self):
        """
        Poll / watch for new image and send to all clients
        """
        image_mtime_was = None
        image_mtime_is = None
        while True:
            sleep(1)
            if self.latest_image and self.latest_image.exists:
                try:
                    image_mtime_is = self.latest_image.stat().st_mtime
                    if image_mtime_was is None or image_mtime_is > image_mtime_was:
                        self.send_image(broadcast=True)
                        image_mtime_was = image_mtime_is
                except FileNotFoundError:
                    # No image to send - do nothing
                    pass
                    

    def broadcast_status(self):
        camera_was = None
        upload_was = None
        while True:
            sleep(1)
            if self.switches:
                camera_is = self.switches['camera']
                if camera_was is None or camera_is != camera_was:
                    self.emit('switches', {'message': "Camera switched", 'camera': str(camera_is)})
                    camera_was = camera_is
                upload_is = self.switches['upload']
                if upload_was is None or upload_is != upload_was:
                    self.emit('switches', {'message': "Upload switched", 'upload': str(upload_is)})
                    upload_was = upload_is

    @report_errors
    def on_req_services_status(self):
        cl = Unit("tmv-controller.service")
        cam = Unit("tmv-camera.service")
        ul = Unit("tmv-upload.service")
        services = {
            str(cl): cl.status(),
            str(cam): cl.status(),
            str(ul): cl.status(),
        }
        emit("services_status", {"message": "Read service statuses", "services": services})

    @report_errors
    def on_restart_service(self):
        LOGGER.debug("Restarting service")
        ctlr = Unit("tmv-controller.service")
        ctlr.restart()
        emit("message", "Restarting camera")
        sleep(3)
        emit("message", f"Restarted camera {ctlr.status()}")

    @report_errors
    def on_req_journal(self):
        lines = 100
        so, se = run_and_capture(["journalctl", "-u", "tmv*", "-n", str(lines)])
        emit("journal", {"journal": so + se})

    @report_errors
    def on_req_files(self):
        """ Send file_root's contents to one level deep """
        if self.file_root:
           # today = dt2str(dt.now().date())
            fls = []
            for d in self.file_root.glob("**/*"):
                fls.append(str(d.relative_to(self.file_root)))
         #       if d.name == today:
         #           for f in d.glob("*"):
         #               fls.append(f"  -- {f}")


            emit("files", {"files": fls})

    @report_errors
    def on_switches(self, positions):
        if self.switches:
            for s_name, s_pos in positions.items():
                self.switches[s_name] = OnOffAuto(s_pos.lower())
        else:
            raise RuntimeError("No switches available")

    @report_errors
    def on_req_switches(self):
        if self.switches:
            emit('switches', {'camera': str(self.switches['camera']), 'upload': str(self.switches['upload'])})

    @report_errors
    def on_req_camera_config(self):
        print("camera_config requested")
        config_path = Path("/etc/tmv/camera.toml")
        emit('camera_config', {'toml': config_path.read_text()})

    @report_errors
    def on_raise_error(self):
        raise RuntimeError("Yes, Jim, it's a error you moron.")

    @report_errors
    def on_camera_config(self, configs):
        loads(configs)  # check syntax
        cf = DFLT_CAMERA_CONFIG_FILE
        unlink_safe(cf + ".bak")
        copy(cf, cf + ".bak")
        Path(cf).write_text(configs)
        # re-read this ourselves, too, to get new file_root, etc
        self.config(cf)
        emit("message", "Saved config")

    def on_connect(self):
        try:
            self.send_image(broadcast=False)
        except OSError:
            pass
