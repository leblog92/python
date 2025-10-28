import pygame
import pyttsx3
import schedule
import time
import threading
from datetime import datetime
import os

class AudioScheduler:
    def __init__(self):
        # Initialiser pygame pour les sons WAV
        pygame.mixer.init()
        
        # Initialiser le moteur TTS une seule fois
        self.tts_engine = None
        self.init_tts()
        
        # Fichier son
        self.sound_file = "notification.wav"
        
        # Messages TTS différents pour chaque horaire
        self.tts_messages = {
            # 14h00 - 14h58
            "14:00": "Début de session",
            "14:30": "Il reste 30 minutes", 
            "14:45": "Il reste 15 minutes",
            "14:55": "Il reste 5 minutes",
            "14:58": "Fin de session",
            
            # 15h00 - 15h58
            "15:00": "Début de session",
            "15:30": "Il reste 30 minutes",
            "15:45": "Il reste 15 minutes",
            "15:55": "Il reste 5 minutes",
            "15:58": "Fin de session",
            
            # 16h00 - 16h58
            "16:00": "Début de session",
            "16:30": "Il reste 30 minutes",
            "16:45": "Il reste 15 minutes",
            "16:55": "Il reste 5 minutes",
            "16:58": "Fin de session",
            
            # 17h00 - 17h58
            "17:00": "Début de session",
            "17:30": "Il reste 30 minutes",
            "17:45": "Il reste 15 minutes",
            "17:55": "Il reste 5 minutes",
            "17:58": "Fin de session"
        }
    
    def init_tts(self):
        """Initialise le moteur TTS"""
        try:
            self.tts_engine = pyttsx3.init()
            self.tts_engine.setProperty('rate', 150)
            self.tts_engine.setProperty('volume', 0.8)
        except Exception as e:
            print(f"Erreur initialisation TTS: {e}")
            self.tts_engine = None
        
    def check_sound_file(self):
        """Vérifie si le fichier son existe"""
        if not os.path.exists(self.sound_file):
            print(f"Fichier son '{self.sound_file}' non trouvé!")
            return False
        return True
        
    def play_tts(self, message):
        """Joue le texte TTS avec gestion d'erreur"""
        if self.tts_engine is None:
            self.init_tts()
            
        if self.tts_engine:
            try:
                # Créer un nouveau moteur TTS pour chaque appel
                engine = pyttsx3.init()
                engine.setProperty('rate', 150)
                engine.setProperty('volume', 0.8)
                engine.say(message)
                engine.runAndWait()
                # Ne pas garder de référence pour éviter l'erreur
                del engine
            except Exception as e:
                print(f"Erreur TTS: {e}")
                # Réinitialiser le moteur en cas d'erreur
                self.tts_engine = None
        
    def play_sound_and_tts(self, schedule_time):
        """Joue le son WAV puis le texte TTS spécifique à l'horaire"""
        def play_sequence():
            try:
                current_time = datetime.now().strftime('%H:%M:%S')
                message = self.tts_messages.get(schedule_time, "Rappel")
                
                print(f"[{current_time}] Début séquence {schedule_time}")
                print(f"Message: {message}")
                
                # Jouer le son WAV si le fichier existe
                if self.check_sound_file():
                    sound = pygame.mixer.Sound(self.sound_file)
                    sound.play()
                    
                    # Attendre la fin du son
                    while pygame.mixer.get_busy():
                        time.sleep(0.1)
                
                # Lire le texte TTS spécifique
                self.play_tts(message)
                
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Séquence terminée\n")
                
            except Exception as e:
                print(f"Erreur: {e}")
        
        # Lancer dans un thread séparé
        thread = threading.Thread(target=play_sequence)
        thread.daemon = True
        thread.start()
    
    def setup_schedule(self):
        """Configure le planning des lectures"""
        # Liste complète des horaires
        schedules = [
            "14:00", "14:30", "14:45", "14:55", "14:58",
            "15:00", "15:30", "15:45", "15:55", "15:58", 
            "16:00", "16:30", "16:45", "16:55", "16:58",
            "17:00", "17:30", "17:45", "17:55", "17:58"
        ]
        
        for schedule_time in schedules:
            schedule.every().day.at(schedule_time).do(
                lambda st=schedule_time: self.play_sound_and_tts(st)
            )
            print(f"Programmé: {schedule_time} - {self.tts_messages[schedule_time]}")
    
    def run(self):
        """Lance le programme principal"""
        print("Démarrage du programme de notifications audio")
        print("Horaires programmés:")
        
        # Afficher les horaires
        hours = ["14", "15", "16", "17"]
        for hour in hours:
            print(f"{hour}h: 00, 30, 45, 55, 58")
        
        print(f"Fichier son: {self.sound_file}")
        print("Appuyez sur Ctrl+C pour arrêter")
        
        # Configurer le planning
        self.setup_schedule()
        
        try:
            while True:
                schedule.run_pending()
                time.sleep(0.5)
                
        except KeyboardInterrupt:
            print("Arrêt du programme")

if __name__ == "__main__":
    scheduler = AudioScheduler()
    scheduler.run()