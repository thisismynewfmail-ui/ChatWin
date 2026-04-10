"""
Simplified GPIO handler for ChatWin.

Handles standard GPIO button input without requiring a WhisPi HAT.
No SPI LCD display, no RGB LED - display is handled via the HTML webview.

Button wiring (standard GPIO):
  - Connect one side of the button to the GPIO pin (default: pin 11, BOARD mode)
  - Connect the other side to GND
  - Internal pull-up resistor is enabled: pressed = LOW, released = HIGH

Set the GPIO_BUTTON_PIN environment variable to change the button pin.
"""

import time
import os
import threading


# ==================== Platform Detection ====================
def _detect_platform():
    """Detect hardware platform type"""
    try:
        with open("/proc/device-tree/model", "r") as f:
            model = f.read().strip("\0").strip()
            if "Raspberry" in model:
                return "rpi", model
            elif "Radxa" in model:
                return "radxa", model
    except Exception:
        pass
    try:
        with open("/proc/device-tree/compatible", "r") as f:
            compat = f.read()
            if "radxa" in compat.lower():
                parts = compat.split("\0")
                model = parts[0] if parts else "Unknown Radxa"
                return "radxa", model
    except Exception:
        pass
    return "unknown", "Unknown"


PLATFORM, PLATFORM_MODEL = _detect_platform()

# Import GPIO library based on platform
_gpio_available = False
GPIO = None
gpiod = None

if PLATFORM == "rpi":
    try:
        import RPi.GPIO as _GPIO

        GPIO = _GPIO
        _gpio_available = True
    except ImportError:
        pass
elif PLATFORM == "radxa":
    try:
        import gpiod as _gpiod

        gpiod = _gpiod
        _gpio_available = True
    except ImportError:
        pass
else:
    # Try auto-detection
    try:
        import RPi.GPIO as _GPIO

        GPIO = _GPIO
        PLATFORM = "rpi"
        PLATFORM_MODEL = "Unknown (RPi.GPIO detected)"
        _gpio_available = True
    except ImportError:
        try:
            import gpiod as _gpiod

            gpiod = _gpiod
            PLATFORM = "radxa"
            PLATFORM_MODEL = "Unknown (gpiod detected)"
            _gpio_available = True
        except ImportError:
            pass


# ==================== Radxa Pin Mappings ====================
# Physical 40-pin header pin number -> (gpiochip number, line offset)

RADXA_ZERO3_PIN_MAP = {
    3: (1, 0),
    5: (1, 1),
    7: (3, 20),
    8: (0, 25),
    10: (0, 24),
    11: (3, 1),
    12: (3, 3),
    13: (3, 2),
    15: (3, 8),
    16: (3, 9),
    18: (3, 10),
    19: (4, 19),
    21: (4, 21),
    22: (3, 17),
    23: (4, 18),
    24: (4, 22),
    26: (4, 25),
    27: (4, 10),
    28: (4, 11),
    29: (3, 11),
    31: (3, 12),
    32: (3, 18),
    33: (3, 19),
    35: (3, 4),
    36: (3, 7),
    37: (1, 4),
    38: (3, 6),
    40: (3, 5),
}

RADXA_CUBIE_A7Z_PIN_MAP = {
    3: (0, 311),
    5: (0, 310),
    7: (0, 32),
    8: (0, 41),
    10: (0, 42),
    11: (0, 33),
    12: (0, 37),
    13: (1, 6),
    15: (1, 7),
    16: (0, 312),
    18: (0, 313),
    19: (0, 108),
    21: (0, 109),
    22: (1, 5),
    23: (0, 107),
    24: (0, 106),
    26: (0, 110),
    27: (0, 113),
    28: (0, 112),
    29: (0, 34),
    31: (0, 35),
    32: (1, 37),
    33: (1, 35),
    35: (0, 38),
    36: (0, 36),
    37: (1, 36),
    38: (0, 40),
    40: (0, 39),
}


def _detect_radxa_board():
    """Detect specific Radxa board variant from device tree compatible string"""
    try:
        with open("/proc/device-tree/compatible", "r") as f:
            compat = f.read().lower()
            if "cubie-a7z" in compat:
                return "cubie-a7z"
            elif "cubie-a7a" in compat:
                return "cubie-a7a"
            elif "cubie-a7s" in compat:
                return "cubie-a7s"
    except Exception:
        pass
    return "zero3w"


class WhisplayBoard:
    """GPIO button handler for ChatWin.

    Uses standard GPIO pins with internal pull-up resistors.
    No WhisPi HAT required - no SPI display, no RGB LED.
    Display is handled via the HTML webview.

    Button wiring: pin -> button -> GND
    Pressed = LOW (0), Released = HIGH (1)
    """

    # Retained for compatibility with code that references display dimensions
    LCD_WIDTH = 240
    LCD_HEIGHT = 280
    CornerHeight = 20

    # Button pin (BOARD numbering), configurable via env var
    BUTTON_PIN = int(os.environ.get("GPIO_BUTTON_PIN", "11"))

    def __init__(self):
        self.platform = PLATFORM
        self.button_press_callback = None
        self.button_release_callback = None

        if not _gpio_available:
            print(f"[GPIO] No GPIO library found. Platform: {PLATFORM_MODEL}")
            print("[GPIO] Button input disabled. Use the web interface button.")
            return

        if self.platform == "rpi":
            self._init_rpi()
        elif self.platform == "radxa":
            self._init_radxa()

        print(f"[GPIO] Platform: {PLATFORM_MODEL}")

    # ==================== Raspberry Pi ====================
    def _init_rpi(self):
        GPIO.setmode(GPIO.BOARD)
        GPIO.setwarnings(False)
        # Standard button with internal pull-up: pressed = LOW, released = HIGH
        GPIO.setup(self.BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(
            self.BUTTON_PIN,
            GPIO.BOTH,
            callback=self._button_event_rpi,
            bouncetime=50,
        )
        print(f"[GPIO] Button on pin {self.BUTTON_PIN} (pull-up, active-low)")

    def _button_event_rpi(self, channel):
        """Raspberry Pi button interrupt callback.
        Internal pull-up: LOW = pressed, HIGH = released.
        """
        if GPIO.input(channel) == GPIO.LOW:
            if self.button_press_callback:
                self.button_press_callback()
        else:
            if self.button_release_callback:
                self.button_release_callback()

    # ==================== Radxa ====================
    def _init_radxa(self):
        self._radxa_board = _detect_radxa_board()
        if self._radxa_board == "cubie-a7z":
            pin_map = RADXA_CUBIE_A7Z_PIN_MAP
        else:
            pin_map = RADXA_ZERO3_PIN_MAP

        if self.BUTTON_PIN not in pin_map:
            print(
                f"[GPIO] Pin {self.BUTTON_PIN} not in Radxa pin map. Button disabled."
            )
            return

        chip_num, line_offset = pin_map[self.BUTTON_PIN]
        chip = gpiod.Chip(f"gpiochip{chip_num}")
        btn_line = chip.get_line(line_offset)
        try:
            btn_line.request(
                consumer="chatwin-btn",
                type=gpiod.LINE_REQ_DIR_IN,
                flags=gpiod.LINE_REQ_FLAG_BIAS_PULL_UP,
            )
        except Exception:
            btn_line.request(consumer="chatwin-btn", type=gpiod.LINE_REQ_DIR_IN)

        self._gpio_chip = chip
        self._btn_line = btn_line
        self._btn_thread_running = True
        self._btn_thread = threading.Thread(
            target=self._button_monitor_radxa, daemon=True
        )
        self._btn_thread.start()
        print(f"[GPIO] Button on pin {self.BUTTON_PIN} (Radxa, pull-up, active-low)")

    def _button_monitor_radxa(self):
        """Button state polling thread for Radxa.
        With pull-up: LOW (0) = pressed, HIGH (1) = released.
        10ms poll interval provides natural debounce.
        """
        btn_line = self._btn_line
        last_state = btn_line.get_value()
        while self._btn_thread_running:
            try:
                state = btn_line.get_value()
                if state != last_state:
                    last_state = state
                    if state == 0:  # Pressed (pulled to GND)
                        if self.button_press_callback:
                            self.button_press_callback()
                    else:  # Released
                        if self.button_release_callback:
                            self.button_release_callback()
            except Exception:
                if self._btn_thread_running:
                    pass
            time.sleep(0.01)

    # ==================== Button Callbacks ====================
    def on_button_press(self, callback):
        self.button_press_callback = callback

    def on_button_release(self, callback):
        self.button_release_callback = callback

    # ==================== No-op stubs for compatibility ====================
    # These methods exist so chatbot-ui.py can call them without errors.
    # The actual display is handled by the HTML webview.

    def set_rgb(self, r, g, b):
        pass

    def set_rgb_fade(self, *args, **kwargs):
        pass

    def set_backlight(self, brightness):
        pass

    def draw_image(self, *args, **kwargs):
        pass

    def fill_screen(self, color):
        pass

    def button_pressed(self):
        if not _gpio_available:
            return False
        if self.platform == "rpi":
            return GPIO.input(self.BUTTON_PIN) == GPIO.LOW
        elif self.platform == "radxa" and hasattr(self, "_btn_line"):
            return self._btn_line.get_value() == 0
        return False

    # ==================== Cleanup ====================
    def cleanup(self):
        if not _gpio_available:
            return
        if self.platform == "rpi":
            GPIO.cleanup()
        elif self.platform == "radxa":
            self._btn_thread_running = False
            if hasattr(self, "_btn_thread"):
                self._btn_thread.join(timeout=2)
            if hasattr(self, "_btn_line"):
                try:
                    self._btn_line.release()
                except Exception:
                    pass
            if hasattr(self, "_gpio_chip"):
                try:
                    self._gpio_chip.close()
                except Exception:
                    pass
