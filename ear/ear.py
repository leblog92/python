import speech_recognition as sr
import pygame
import time
import os
import threading

class AudioCommandRecognizer:
    def __init__(self):
        # Initialiser le recognizer
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()
        
        # Initialiser pygame pour l'audio
        pygame.mixer.init()
        
        # Dictionnaire des commandes et fichiers audio associés
        self.commands = {
            "bonjour": "sounds/hello.mp3",
            "salut": "sounds/hello.mp3",
            "au revoir": "sounds/goodbye.mp3",
            "merci": "sounds/thank_you.mp3",
            "bravo": "sounds/applause.mp3",
            "musique": "sounds/music.mp3",
            "rire": "sounds/laugh.mp3",
            "wesh": "sounds/wesh.mp3"
        }
        
        # Créer le dossier des sons s'il n'existe pas
        if not os.path.exists("sounds"):
            os.makedirs("sounds")
            
        self.is_listening = False
        
    def calibrer_micro(self):
        """Calibre le microphone pour le bruit ambiant"""
        print("Calibration du microphone... Parlez maintenant.")
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=2)
        print("Calibration terminée!")
    
    def jouer_audio(self, fichier):
        """Joue un fichier audio"""
        try:
            if os.path.exists(fichier):
                pygame.mixer.music.load(fichier)
                pygame.mixer.music.play()
                print(f"Joue: {fichier}")
                
                # Attendre que la musique se termine
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
            else:
                print(f"Fichier audio non trouvé: {fichier}")
        except Exception as e:
            print(f"Erreur lors de la lecture audio: {e}")
    
    def reconnaitre_commande(self, audio):
        """Reconnaît la parole et retourne la commande"""
        try:
            # Reconnaissance en français
            texte = self.recognizer.recognize_google(audio, language="fr-FR")
            texte = texte.lower()
            print(f"Vous avez dit: {texte}")
            
            # Vérifier chaque commande
            for commande, fichier_audio in self.commands.items():
                if commande in texte:
                    return commande, fichier_audio
            
            return None, None
            
        except sr.UnknownValueError:
            print("Désolé, je n'ai pas compris")
            return None, None
        except sr.RequestError as e:
            print(f"Erreur avec le service de reconnaissance: {e}")
            return None, None
    
    def ecouter_et_repondre(self):
        """Écoute en continu et répond aux commandes"""
        print("Écoute en cours... Dites 'stop' pour arrêter.")
        
        with self.microphone as source:
            while self.is_listening:
                try:
                    # Écouter avec timeout
                    audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=5)
                    
                    # Traiter dans un thread séparé pour ne pas bloquer l'écoute
                    thread = threading.Thread(
                        target=self.traiter_audio, 
                        args=(audio,)
                    )
                    thread.daemon = True
                    thread.start()
                    
                except sr.WaitTimeoutError:
                    # Timeout normal, continue à écouter
                    continue
                except Exception as e:
                    print(f"Erreur d'écoute: {e}")
    
    def traiter_audio(self, audio):
        """Traite l'audio reçu"""
        commande, fichier_audio = self.reconnaitre_commande(audio)
        
        if commande and fichier_audio:
            print(f"Commande détectée: '{commande}'")
            self.jouer_audio(fichier_audio)
        
        # Vérifier la commande d'arrêt
        try:
            texte = self.recognizer.recognize_google(audio, language="fr-FR").lower()
            if "stop" in texte or "arrêt" in texte:
                self.is_listening = False
                print("Arrêt de l'écoute...")
        except:
            pass
    
    def demarrer(self):
        """Démarre le système de reconnaissance"""
        print("=== Système de Reconnaissance Vocale ===")
        print("Commandes disponibles:")
        for commande in self.commands.keys():
            print(f" - {commande}")
        print(" - stop/arrêt (pour quitter)")
        print("=" * 40)
        
        self.calibrer_micro()
        self.is_listening = True
        self.ecouter_et_repondre()

def creer_fichiers_exemple():
    """Crée des fichiers audio d'exemple (à remplacer par vos propres fichiers)"""
    sounds_dir = "sounds"
    
    # Message pour indiquer qu'il faut ajouter des vrais fichiers audio
    for fichier in ["hello.mp3", "goodbye.mp3", "thank_you.mp3", 
                   "applause.mp3", "music.mp3", "laugh.mp3"]:
        chemin = os.path.join(sounds_dir, fichier)
        if not os.path.exists(chemin):
            print(f"Veuillez ajouter le fichier audio: {chemin}")
    
    print("\nPour utiliser l'application:")
    print("1. Ajoutez vos fichiers MP3 dans le dossier 'sounds/'")
    print("2. Modifiez le dictionnaire 'commands' si nécessaire")
    print("3. Lancez le programme")

if __name__ == "__main__":
    # Vérifier les fichiers audio
    creer_fichiers_exemple()
    
    # Démarrer l'application
    app = AudioCommandRecognizer()
    app.demarrer()