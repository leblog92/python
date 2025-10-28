import tkinter as tk
import pyttsx3
import datetime
import threading
import pytz
import winsound
import platform
from PIL import Image, ImageTk
import os
import time

# Initialisation du moteur TTS
engine = pyttsx3.init()
engine.setProperty('rate', 125)
engine.setProperty('volume', 2)

# Sons
NOTIF_SOUND = 'notification.wav'

# Heures et sons personnalisés
heure_sons = {
    "14:00": "00.wav",
    "14:45": "45.wav",
    "14:50": "50.wav",
    "14:55": "55.wav",
    "14:58": "58.wav",
    "15:45": "45.wav",
    "15:50": "50.wav",
    "15:55": "55.wav",
    "15:58": "58.wav",
    "16:45": "45.wav",
    "16:50": "50.wav",
    "16:55": "55.wav",
    "16:58": "58.wav",
    "17:45": "45.wav",
    "17:50": "50.wav",
    "17:55": "55.wav",
    "17:58": "55.wav",
}

# Suivi des rappels joués
parlees = set()

# Lecture d'un son
def play_sound(file_path=NOTIF_SOUND):
    if platform.system() == "Windows" and os.path.isfile(file_path):
        winsound.PlaySound(file_path, winsound.SND_FILENAME | winsound.SND_ASYNC)

# Lecture d'un message avec son
def parler_depuis_ui(message="Attention !", son=None):
    def inner():
        # Add 1-2 second delay before playing the sound
        time.sleep(1.5)  # Using 1.5 seconds as a middle ground between 1-2
        if son:
            play_sound(son)
        else:
            play_sound(NOTIF_SOUND)
        try:
            engine.say(message)
            engine.runAndWait()
        except Exception as e:
            print("Erreur TTS :", e)
    threading.Thread(target=inner, daemon=True).start()

# Vérifie l'heure
def boucle_heure():
    while True:
        paris = pytz.timezone('Europe/Paris')
        maintenant = datetime.datetime.now(paris)

        heure_affichee = maintenant.strftime("%H:%M:%S")
        heure_rappel = maintenant.strftime("%H:%M")

        root.after(0, heure_label.config, {'text': heure_affichee})

        if heure_rappel in heure_sons and heure_rappel not in parlees:
            son = heure_sons[heure_rappel]
            parler_depuis_ui(message=f"Heure {heure_rappel}", son=son)
            root.after(0, log_listbox.insert, tk.END, f"✅ {heure_rappel} : {son}")
            parlees.add(heure_rappel)

        threading.Event().wait(1)

# Test vocal
def test_rappel():
    parler_depuis_ui("Les enfants ! Vous faites trop de bruit !")

# GUI
root = tk.Tk()
root.title("Video Game Timer")
root.geometry("500x500")
root.configure(bg="#d94e67")

# Image
try:
    img = Image.open("logo_VGT.png").resize((500, 210))
    photo = ImageTk.PhotoImage(img)
    image_label = tk.Label(root, image=photo, bg="#d94e67")
    image_label.image = photo
    image_label.pack(pady=10)
except Exception as e:
    print("Image non chargée :", e)

# Affichage heure
heure_label = tk.Label(root, text="", font=("Consolas", 16), fg="white", bg="#d94e67")
heure_label.pack(pady=10)

# Bouton test
test_btn = tk.Button(root, text="Test voix", command=test_rappel, bg="#4a4a4a", fg="white")
test_btn.pack(pady=5)

# Log
log_label = tk.Label(root, text="Rappels effectués :", fg="white", bg="#d94e67")
log_label.pack()
log_listbox = tk.Listbox(root, width=60)
log_listbox.pack(pady=10)

# Thread de l'heure
threading.Thread(target=boucle_heure, daemon=True).start()

# Boucle principale
root.mainloop()