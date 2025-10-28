import time
import usb_hid
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keycode import Keycode
from keyboard_layout_win_fr import KeyboardLayout

# Wait for USB to initialize
time.sleep(1)

kbd = Keyboard(usb_hid.devices)
layout = KeyboardLayout(kbd)

# Type "password" (French layout)
layout.write("Eleve2020!mediat")
time.sleep(0.2)  # Small delay between actions

# Press ENTER
kbd.press(Keycode.ENTER)
time.sleep(0.1)
kbd.release_all()