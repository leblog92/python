# video_game_timer.py
# Programme : Video Game Timer
# Description : Alerte sonore et vocale pour sessions de jeu avec messages fun/robotiques,
# interface graphique, synchronisation horaire internet, historique non persistant (affichage à l'écran uniquement).

# Librairies requises :
# pip install pyttsx3 requests pillow playsound

import tkinter as tk
import tkinter.font as tkfont
from PIL import Image, ImageTk
import threading
import time
import datetime
import requests
import pyttsx3
import platform

# Pour le son sous Windows
if platform.system() == "Windows":
    import winsound
else:
    from playsound import playsound

# --- CONFIGURATION ---
TIMEZONE_API = 'http://worldtimeapi.org/api/timezone/Europe/Paris'
NTPSYNC_INTERVAL = 3600  # secondes
NOTIF_SOUND = 'notification.wav'

# Planning des rappels : (heure, minute, fin_de_session)
SESSION_TIMES = [
    (14, 0, False), (14, 45, False), (14, 50, False), (14, 55, False), (14, 58, True),
    (15, 0, False), (15, 45, False), (15, 50, False), (15, 55, False), (15, 58, True),
    (16, 0, False), (16, 45, False), (16, 50, False), (16, 55, False), (16, 58, True),
    (17, 0, False), (17, 45, False), (17, 50, False), (17, 55, False), (17, 58, True),
]

# Fonctions utilitaires ---------------------------------

def get_message(hour, minute, is_end):
    if minute == 45:
        return "Il reste 15 minutes."
    elif minute == 50:
        return "Il reste 10 minutes."
    elif minute == 55:
        return "Il reste 3 minutes, terminez votre partie."
    elif is_end:
        return "Fin de session."
    else:
        return "Début de session."

# Synchronisation horaire (fallback silencieux)
time_offset = 0
last_sync = 0

def sync_time():
    global time_offset, last_sync
    try:
        r = requests.get(TIMEZONE_API, timeout=5)
        dt_str = r.json().get('datetime', '')
        if dt_str:
            server_dt = datetime.datetime.fromisoformat(dt_str[:-6])
            local_dt = datetime.datetime.now()
            time_offset = (server_dt - local_dt).total_seconds()
        else:
            time_offset = 0
    except Exception:
        time_offset = 0
    finally:
        last_sync = time.time()


def get_current_time():
    if time.time() - last_sync > NTPSYNC_INTERVAL:
        sync_time()
    return datetime.datetime.now() + datetime.timedelta(seconds=time_offset)

# Affichage de l'historique (mémoire)
def log_event(msg):
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    listbox.insert(tk.END, f"{ts} - {msg}")

# Lecture du fichier son
def play_sound():
    if platform.system() == "Windows":
        winsound.PlaySound(NOTIF_SOUND, winsound.SND_FILENAME | winsound.SND_ASYNC)
    else:
        playsound(NOTIF_SOUND)

# Notification sonore + vocale
def notify(message):
    threading.Thread(target=play_sound, daemon=True).start()
    def _speak():
        engine_local = pyttsx3.init()
        engine_local.say(message)
        engine_local.runAndWait()
        log_event(message)
    threading.Thread(target=_speak, daemon=True).start()

# Planification des rappels
g_triggered = set()
def check_schedule():
    now = get_current_time()
    for h, m, is_end in SESSION_TIMES:
        key = (h, m)
        if key not in g_triggered and now.hour == h and now.minute == m:
            msg = get_message(h, m, is_end)
            notify(msg)
            g_triggered.add(key)
    if now.hour == 0 and now.minute == 0:
        g_triggered.clear()
    root.after(30000, check_schedule)

# Interface graphique Tkinter
root = tk.Tk()
root.title("Video Game Timer")
font = tkfont.Font(family="Consolas", size=10)

# Logo animé
frames = []
try:
    img = Image.open('logo.gif')
    for i in range(getattr(img, 'n_frames', 1)):
        img.seek(i)
        frames.append(ImageTk.PhotoImage(img))
    lbl = tk.Label(root)
    lbl.pack(pady=5)
    def animate(i=0):
        lbl.config(image=frames[i])
        root.after(100, animate, (i+1) % len(frames))
    animate()
except Exception:
    pass

# Affichage de l'heure courante
time_lbl = tk.Label(root, font=font)
time_lbl.pack(pady=5)
def update_clock():
    now = get_current_time().strftime('%H:%M:%S')
    time_lbl.config(text=now)
    root.after(1000, update_clock)

# Bouton test manuel
ctrl_frame = tk.Frame(root)
ctrl_frame.pack(pady=5)
test_btn = tk.Button(ctrl_frame, text="Test", font=font, command=lambda: notify("Ceci est un test de notification !"))
test_btn.pack()

# Liste d'historique
db_frame = tk.Frame(root)
db_frame.pack(fill='both', expand=True)
listbox = tk.Listbox(db_frame, font=font)
listbox.pack(side='left', fill='both', expand=True)
scroll = tk.Scrollbar(db_frame, command=listbox.yview)
scroll.pack(side='right', fill='y')
listbox.config(yscrollcommand=scroll.set)

# Démarrage des routines
sync_time()
update_clock()
check_schedule()
root.mainloop()