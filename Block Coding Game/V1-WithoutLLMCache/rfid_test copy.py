import RPi.GPIO as GPIO
import os

# Ultimate monkey-patch to bypass rpi-lgpio bugs on Pi 5
_orig_setup = GPIO.setup
_setup_pins = set()
def _patched_setup(channel, direction, pull_up_down=GPIO.PUD_OFF, initial=None):
    if channel in _setup_pins:
        return
    if direction == GPIO.OUT and initial is None:
        initial = GPIO.HIGH
    try:
        _orig_setup(channel, direction, pull_up_down, initial)
        _setup_pins.add(channel)
    except Exception as e:
        if "busy" in str(e).lower() or "allocated" in str(e).lower():
            _setup_pins.add(channel)
        else:
            raise
GPIO.setup = _patched_setup

_orig_output = GPIO.output
def _patched_output(channel, state):
    try:
        _orig_output(channel, state)
    except RuntimeError:
        # Fallback to pinctrl if RPi.GPIO forgets the pin state
        os.system(f"pinctrl set {channel} op {'dh' if state else 'dl'} >/dev/null 2>&1")
GPIO.output = _patched_output

from mfrc522 import MFRC522
import time

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

RST_SHARED = 25  # one RST wired to all six readers

# (name, CS pin [BCM], sound file)
READERS = [
    ("Reader1", 8,  "/home/unbcroboticslab/sound1.mp3"),  # Pin 24
    ("Reader2", 7,  "/home/unbcroboticslab/sound2.mp3"),  # Pin 26
    ("Reader3", 18, "/home/unbcroboticslab/sound3.mp3"),  # Pin 12
    ("Reader4", 12, "/home/unbcroboticslab/sound4.mp3"),  # Pin 32
    ("Reader5", 13, "/home/unbcroboticslab/sound5.mp3"),  # Pin 33
    ("Reader6", 23,"/home/unbcroboticslab/sound6.mp3"),  # Pin 16
]

class SoftCSReader(MFRC522):
    """MFRC522 with a software (GPIO) chip-select, so many readers share one SPI bus."""
    def __init__(self, cs_pin, pin_rst=RST_SHARED, bus=0, device=0, spd=1000000):
        self.cs_pin = cs_pin
        self.is_hw_cs = False  
        GPIO.setup(cs_pin, GPIO.OUT, initial=GPIO.HIGH)
        device = 0
            
        super().__init__(bus=bus, device=device, spd=spd,
                         pin_mode=GPIO.BCM, pin_rst=pin_rst)
        try:
            self.spi.no_cs = True             # suppress any hardware CS assertion
        except Exception:
            pass

    def Write_MFRC522(self, addr, val):
        try:
            self.spi.no_cs = True
        except OSError:
            pass
            
        GPIO.output(self.cs_pin, GPIO.LOW)
        self.spi.xfer2([(addr << 1) & 0x7E, val])
        GPIO.output(self.cs_pin, GPIO.HIGH)

    def Read_MFRC522(self, addr):
        try:
            self.spi.no_cs = True
        except OSError:
            pass
            
        GPIO.output(self.cs_pin, GPIO.LOW)
        val = self.spi.xfer2([((addr << 1) & 0x7E) | 0x80, 0])
        GPIO.output(self.cs_pin, GPIO.HIGH)
        return val[1]

readers = [(name, SoftCSReader(cs), snd) for (name, cs, snd) in READERS]

def play_sound(f):
    os.system(f"mpg123 '{f}' > /dev/null 2>&1 &")

def scan(reader, name, sound_file):
    GPIO.output(reader.cs_pin, GPIO.LOW)
    status, _ = reader.MFRC522_Request(reader.PICC_REQIDL)
    if status == reader.MI_OK:
        status, uid = reader.MFRC522_Anticoll()
        if status == reader.MI_OK:
            uid_str = "-".join(str(x) for x in uid)
            print(f"[{name}] Card detected! UID: {uid_str}")
            play_sound(sound_file)
            return uid
    GPIO.output(reader.cs_pin, GPIO.HIGH)
    return None

print("Scanning 6 readers... (Ctrl+C to stop)")
try:
    while True:
        for name, reader, snd in readers:
            reader.MFRC522_Init()
            scan(reader, name, snd)
        #time.sleep(0.05)
        #time.sleep(1.00)
except KeyboardInterrupt:
    print("\nStopping...")
    GPIO.cleanup()