
class TMVError(Exception):
    """ Base exception """


class CameraError(Exception):
    """" Hardware camera problem"""

class ButtonError(Exception):
    """ Problem with (usually hardware) buttons """

class VideoMakerError(Exception):
    """ Problem making images into a video """

class ImageError(Exception):
    """ Problem with an image """

class ConfigError(TMVError):
    """ TOML or config error """


class PiJuiceError(TMVError):
    """ Cound't power off"""


class PowerOff(TMVError):
    """ Camera can power off """


class SignalException(TMVError):
    """ Camera got a sigint """
