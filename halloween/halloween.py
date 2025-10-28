import os
import random
import time
import pygame

def halloween_ambiance(sounds_folder="halloween_sounds", min_minutes=2, max_minutes=4):
    """Version simple pour lancer et oublier"""
    
    pygame.mixer.init()
    
    if not os.path.exists(sounds_folder):
        print(f"Créez le dossier '{sounds_folder}' avec vos bruitages MP3")
        return
    
    mp3_files = [f for f in os.listdir(sounds_folder) if f.endswith('.mp3')]
    
    if not mp3_files:
        print("Aucun fichier MP3 trouvé!")
        return
    
    print(f"🎃 Ambiance Halloween démarrée! Intervalle: {min_minutes}-{max_minutes} min")
    print("🛑 Ctrl+C pour arrêter")
    
    try:
        while True:
            # Attendre un délai aléatoire
            delay = random.randint(min_minutes * 60, max_minutes * 60)
            minutes, seconds = divmod(delay, 60)
            print(f"Prochain son dans {minutes:02d}:{seconds:02d}")
            time.sleep(delay)
            
            # Jouer un son aléatoire
            sound_file = random.choice(mp3_files)
            print(f"🎃 Diffusion: {sound_file}")
            
            pygame.mixer.music.load(os.path.join(sounds_folder, sound_file))
            pygame.mixer.music.play()
            
            # Attendre la fin
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
                
    except KeyboardInterrupt:
        print("\n🔇 Ambiance arrêtée")

if __name__ == "__main__":
    halloween_ambiance()