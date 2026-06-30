import time
import os
import pygame

MP3 = "notification.mp3"  # <-- change to your file name

here = os.path.dirname(os.path.abspath(__file__))
mp3 = os.path.join(here, MP3)

if not os.path.exists(mp3):
    print(f"File not found: {mp3}")
    raise SystemExit

interval = float(input("Interval in seconds: "))

pygame.mixer.init()
pygame.mixer.music.load(mp3)

print(f"Playing every {interval}s. Press Ctrl+C to stop.")
try:
    while True:
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
        time.sleep(interval)
except KeyboardInterrupt:
    print("\nStopped.")
    pygame.mixer.quit()