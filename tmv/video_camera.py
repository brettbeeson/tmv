# Adapted from miguel
import time
import threading
import io
from sys import stderr
try:
    from thread import get_ident
except ImportError:
    from _thread import get_ident
import logging
try:
    import picamera  # pylint:disable=import-error
except ModuleNotFoundError as e:
    print(f"Contiuning after {e}", file=stderr)

from tmv.buttons import OFF


LOGGER = logging.getLogger("tmv.video_camera")


class VideoCameraEvent(object):
    """An Event-like class that signals all active clients when a new frame is available. """

    def __init__(self):
        self.events = {}

    def wait(self):
        """Invoked from each client's thread to wait for the next frame."""
        ident = get_ident()
        if ident not in self.events:
            # this is a new client
            # add an entry for it in the self.events dict
            # each entry has two elements, a threading.Event() and a timestamp
            self.events[ident] = [threading.Event(), time.time()]
        return self.events[ident][0].wait()

    def set(self):
        """Invoked by the camera thread when a new frame is available."""
        now = time.time()
        remove = None
        for ident, event in self.events.items():
            if not event[0].isSet():
                # if this client's event is not set, then set it
                # also update the last set timestamp to now
                event[0].set()
                event[1] = now
            else:
                # if the client's event is already set, it means the client
                # did not process a previous frame
                # if the event stays set for more than 3 seconds, then assume
                # the client is gone and remove it
                if now - event[1] > 3:
                    remove = ident
        if remove:
            del self.events[remove]

    def clear(self):
        """Invoked from each client's thread after a frame was processed."""
        self.events[get_ident()][0].clear()


class VideoCamera(object):
    """ Provide frames, with auto-off. Multiple client are possible but we only need one."""
    thread = None  # background thread that reads frames from camera
    frame = None  # current frame is stored here by background thread
    last_access = 0  # time of last client access to the camera
    event = VideoCameraEvent()

    _interface = None
    _socketio = None
    _initial_camera_mode = None

    def __init__(self, interface, socketio):
        """Start the background camera thread if it isn't running yet."""

        if VideoCamera.thread is None:
            VideoCamera._interface = interface
            VideoCamera._socketio = socketio
            LOGGER.debug('Turning off camera to use video. Starting video thread.')
            VideoCamera._socketio.emit("message", f"Turning off camera to use video. Wait {interface.interval.total_seconds()}s.")
            time.sleep(interface.interval.total_seconds())
            
            # save current camera mode and turn off
            # since camera is running in another process (tmv-camera) we can't simulatenously
            # do video and camera
            VideoCamera._initial_camera_mode = VideoCamera._interface.mode_button.value
            VideoCamera._interface.mode_button.value = OFF
            VideoCamera.last_access = time.time()
            # start background frame thread
            VideoCamera.thread = threading.Thread(target=self._thread)
            VideoCamera.thread.start()
            # wait until frames are available
            while self.get_frame() is None:
                time.sleep(0)
        else:
            LOGGER.debug('Camera thread available.')


    def get_frame(self):
        """Return the current camera frame."""
        VideoCamera.last_access = time.time()

        # wait for a signal from the camera thread
        VideoCamera.event.wait()
        VideoCamera.event.clear()

        return VideoCamera.frame

    @staticmethod
    def frames():
        try:
            with picamera.PiCamera() as camera:
                # let camera warm up
                time.sleep(.5)
                stream = io.BytesIO()
                for _ in camera.capture_continuous(stream, 'jpeg',
                                                   use_video_port=True):
                    # return current frame
                    stream.seek(0)
                    yield stream.read()

                    # reset stream for next frame
                    stream.seek(0)
                    stream.truncate()
        except Exception as e:
            LOGGER.error(e)
            try:
                VideoCamera._socketio.emit("error", str(e))
            except:
                pass
            

    @classmethod
    def _thread(cls):
        """Camera background thread."""
        print('Starting camera thread.')
        frames_iterator = cls.frames()
        for frame in frames_iterator:
            VideoCamera.frame = frame
            VideoCamera.event.set()  # send signal to clients
            time.sleep(0)

            # if there hasn't been any clients asking for frames in
            # the last 10 seconds then stop the thread
            # return camera to original mode value
            if time.time() - VideoCamera.last_access > 10:
                frames_iterator.close()
                m = f"Restoring camera mode to {cls._initial_camera_mode.value}"
                LOGGER.debug(m)
                VideoCamera._socketio.emit("message", m)
                cls._interface.mode_button.value = cls._initial_camera_mode.value
                break
        VideoCamera.thread = None
