from tmv.interface.screen import TMVScreen
from tmv.camera import Interface

def test_screen():
    interface = Interface()
    screen = TMVScreen(interface)
    screen.update()