import digitalio
import busio
import board
from adafruit_epd.epd import Adafruit_EPD
from adafruit_epd.ssd1675 import Adafruit_SSD1675
from PIL import Image
from time import sleep


class TMVScreen:
    """Control an adafruit eink bonnet to show tmv stats, images, etc"""

    def __init__(self, interface):
        self._image = None
        self._interface = interface
        spi = busio.SPI(board.SCK, MOSI=board.MOSI, MISO=board.MISO)
        ecs = digitalio.DigitalInOut(board.CE0)
        dc = digitalio.DigitalInOut(board.D22)
        rst = digitalio.DigitalInOut(board.D27)
        busy = digitalio.DigitalInOut(board.D17)
        srcs = None
        self.display = Adafruit_SSD1675(122, 250,        # 2.13" HD mono display
                                        spi,
                                        cs_pin=ecs,
                                        dc_pin=dc,
                                        sramcs_pin=srcs,
                                        rst_pin=rst,
                                        busy_pin=busy,)

        self.display.rotation = 1
        print (self.display)
        
    def update(self):
        self.display.image(self._image)
        self.display.display()

    def image(self) -> Image:
        image = Image.open("/home/pi/blinka.png")

        # Scale the image to the smaller screen dimension
        image_ratio = image.width / image.height
        screen_ratio = self.display.width / self.display.height
        if screen_ratio < image_ratio:
            scaled_width = image.width * self.display.height // image.height
            scaled_height = self.display.height
        else:
            scaled_width = self.display.width
            scaled_height = image.height * self.display.width // image.width
        image = image.resize((scaled_width, scaled_height), Image.BICUBIC)

        # Crop and center the image
        x = scaled_width // 2 - self.display.width // 2
        y = scaled_height // 2 - self.display.height // 2
        self._image = image.crop((x, y, x + self.display.width, y + self.display.height))

        return self._image


if __name__ == '__main__':
    print("h1")
    ts = TMVScreen(None)
    ts.image()
    print(ts._image)
    ts.update()
    sleep(5)
