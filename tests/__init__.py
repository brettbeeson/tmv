from os import uname

def running_on_pi():
    return uname()[4].startswith('arm')
