
class TMVError(Exception):
    """ Base exception """


class CameraError(Exception):
    """" Hardware camera problem"""


class VideoMakerError(Exception):
    """ Problem making images into a video """


class ConfigError(TMVError):
    """ TOML or config error """


class PiJuiceError(TMVError):
    """ Cound't power off"""


class PowerOff(TMVError):
    """ Camera can power off """


class SignalException(TMVError):
    """ Camera got a sigint """
