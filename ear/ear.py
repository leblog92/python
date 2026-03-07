import speech_recognition as sr
import pygame
import time
import os
import subprocess
import threading
import platform
import sys

class AudioCommandRecognizer:
    def __init__(self):
        # Initialiser le recognizer
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()
        
        # Initialiser pygame pour l'audio
        pygame.mixer.init()
        
        # Dictionnaire des commandes et fichiers audio associés
        self.commands = {
            "anne": "sounds/no.mp3",
            "alarme": "sounds/alarme.mp3",
            "approximatif": "sounds/oh.mp3",
            "approximative": "sounds/oh.mp3",
            "approximativement": "sounds/oh.mp3",
            "assistante": "sounds/assistante.mp3",
            "astucieux": "sounds/debile.mp3",
            "attention au matériel": "sounds/pete.mp3",
            "au revoir": "sounds/au_revoir.mp3",
            "banana": "sounds/banane.mp3",
            "banane": "sounds/banane.mp3",
            "bananes": "sounds/banane.mp3",
            "barbara": "sounds/barbara.mp3",
            "basile": "sounds/souffrance.mp3",
            "bière": "sounds/biere.mp3",
            "biscuit": "sounds/biscuit.mp3",
            "biscuits": "sounds/biscuit.mp3",
            "bisou": "sounds/bisou.mp3",
            "bisous": "sounds/bisou.mp3",
            "boîte à coucou": "sounds/bac.mp3",
            "bonne année": "sounds/new-year.mp3",
            "bye": "sounds/bye.mp3",
            "calimero": "sounds/calimero.mp3",
            "castlevania": "sounds/castlevania.mp3",
            "cavalier": "sounds/cheval.mp3",
            "c'est nul": "sounds/nul0.mp3",
            "j'ai vu ça sur": "sounds/vrai.mp3",
            "tu as vu ça sur": "sounds/vrai.mp3",
            "ça m'énerve": "sounds/enerve.mp3",
            "canard": "sounds/quack.mp3",
            "cependant": "sounds/cependant.mp3",
            "chat": "sounds/miaou.mp3",
            "cheval": "sounds/cheval.mp3",
            "chewbacca": "sounds/chewbacca.mp3",
            "chiffrement": "sounds/pasfaux.mp3",
            "chine": "sounds/chine.mp3",
            "chinois": "sounds/chinois.mp3",
            "ciao": "sounds/ciao.mp3",
            "clignote": "sounds/urgence.mp3",
            "communiste": "sounds/coco.mp3",
            "coucou": "sounds/coucou.mp3",
            "crise de nerfs": "sounds/mb.mp3",
            "dark souls": "sounds/darksouls.mp3",
            "dernière minute": "sounds/countdown.mp3",
            "dernières minutes": "sounds/countdown.mp3",
            "discret": "sounds/clang.mp3",
            "dominique": "sounds/michel.mp3",
            "doom": "sounds/doom.mp3",
            "échec": "sounds/motus.mp3",
            "erreur": "sounds/erreur.mp3",
            "expire": "sounds/expire.mp3",
            "expiré": "sounds/expire.mp3",
            "expirer": "sounds/expire.mp3",
            "facebook": "sounds/facebook.mp3",
            "faim": "sounds/faim.mp3",
            "fc 24": "sounds/fifa.mp3",
            "fc 25": "sounds/fifa.mp3",
            "fc 26": "sounds/fifa.mp3",
            "j'ai faim": "sounds/faim.mp3",
            "fifa": "sounds/fifa.mp3",
            "fin de partie": "sounds/fin.mp3",
            "fin de session": "sounds/final_countdown.mp3",
            "final countdown": "sounds/final_countdown.mp3",
            "fortnite": "sounds/robocop.mp3",
            "français": "sounds/french.mp3",
            "frère": "sounds/frere.mp3",
            "from software": "sounds/darksouls.mp3",
            "gérard": "sounds/michel.mp3",
            "bestiole": "sounds/bete.mp3",
            "goodbye": "sounds/goodbye.mp3",
            "grève": "sounds/greve.mp3",
            "hanté": "sounds/ghost.mp3",
            "hello": "sounds/hello.mp3",
            "heure de code": "sounds/hoc.mp3",
            "hitler": "sounds/nein.mp3",
            "houston": "sounds/problem.mp3",
            "incongru": "sounds/pasfaux.mp3",
            "complication": "sounds/calimero.mp3",
            "complications": "sounds/calimero.mp3",
            "injuste": "sounds/calimero.mp3",
            "inscription": "sounds/inscription.mp3",
            "inscrire": "sounds/inscription.mp3",
            "invocation": "sounds/lovecraft.mp3",
            "invoquer": "sounds/lovecraft.mp3",
            "italie": "sounds/italie.mp3",
            "j'ai une théorie": "sounds/chagrin.mp3",
            "j'ai raison": "sounds/pas faux.mp3",
            "je suis choqué": "sounds/shock.mp3",
            "j'en ai marre": "sounds/marre.mp3",
            "jérémy": "sounds/souffrance.mp3",
            "jésus": "sounds/jesus.mp3",
            "johnny": "sounds/bac.mp3",
            "jouet": "sounds/toy.mp3",
            "laurent": "sounds/psycho.mp3",
            "je reviens": "sounds/terminator.mp3",
            "que coucou": "sounds/bac.mp3",
            "la direction": "sounds/direction.mp3",
            "lamentable": "sounds/cnul.mp3",
            "léon": "sounds/leon.mp3",
            "loïc": "sounds/loik.mp3",
            "lovecraft": "sounds/lovecraft.mp3",
            "malheur": "sounds/malheur.mp3",
            "malheureuse": "sounds/malheur.mp3",
            "malheureux": "sounds/malheur.mp3",
            "mal payé": "sounds/pauvres.mp3",
            "mal payés": "sounds/pauvres.mp3",
            "mario": "sounds/mario.mp3",
            "mars": "sounds/mars.mp3",
            "massacre": "sounds/doom.mp3",
            "mathieu": "sounds/matthieu.mp3",
            "maurice": "sounds/maurice.mp3",
            "merci beaucoup": "sounds/merci.mp3",
            "mes profs": "sounds/demon.mp3",
            "miaou": "sounds/miaou.mp3",
            "michel": "sounds/michel.mp3",
            "mignon": "sounds/mignon.mp3",
            "microsoft": "sounds/microsoft.mp3",
            "minecraft": "sounds/minecraft.mp3",
            "modalité": "sounds/modalites.mp3",
            "modalités": "sounds/modalites.mp3",
            "mouton": "sounds/mouton.mp3",
            "moutons": "sounds/mouton.mp3",
            "mortal kombat": "sounds/mortal_kombat.mp3",
            "mozzarella": "sounds/italie.mp3",
            "nathalie": "sounds/nathalie.mp3",
            "nazi": "sounds/hitler.mp3",
            "neige": "sounds/neige.mp3",
            "nintendo": "sounds/nintendo.mp3",
            "nurgle": "sounds/nurgle.mp3",
            "olivier": "sounds/olivier.mp3",
            "papa": "sounds/papa.mp3",
            "paradoxal": "sounds/pasfaux.mp3",
            "parmesan": "sounds/italie.mp3",
            "pas assez payer": "sounds/pauvres.mp3",
            "pas assez payé": "sounds/pauvres.mp3",
            "pas assez payés": "sounds/pauvres.mp3",
            "pauvres": "sounds/pauvres.mp3",
            "pénible": "sounds/penible.mp3",
            "perceval": "sounds/chagrin.mp3",
            "père": "sounds/papa.mp3",
            "périmé": "sounds/perime.mp3",
            "périmée": "sounds/perime.mp3",
            "périmer": "sounds/perime.mp3",
            "perdu": "sounds/perime.mp3",
            "philippe": "sounds/philippe.mp3",
            "pikachu": "sounds/pikachu.mp3",
            "pilotage": "sounds/pilote.mp3",
            "pilote": "sounds/pilote.mp3",
            "playstation": "sounds/playstation.mp3",
            "pleurer": "sounds/pleurer.mp3",
            "pleurnicher": "sounds/pleurer.mp3",
            "poilu": "sounds/chewbacca.mp3",
            "pourri": "sounds/pourri.mp3",
            "pokémon": "sounds/pikachu.mp3",
            "poney": "sounds/poney.mp3",
            "predator": "sounds/predator.mp3",
            "gros problème": "sounds/problem.mp3",
            "pizza": "sounds/italie.mp3",
            "ps5": "sounds/playstation.mp3",
            "putin": "sounds/russia.mp3",
            "rembobine": "sounds/rewind.mp3",
            "rembobiner": "sounds/rewind.mp3",
            "rembobines": "sounds/rewind.mp3",
            "réserver": "sounds/resa.mp3",
            "reste en vie": "sounds/staying.mp3",
            "réunion": "sounds/nono.mp3",
            "rire": "sounds/nelson.mp3",
            "romantique": "sounds/romantique.mp3",
            "russe": "sounds/cnormal.mp3",
            "russie": "sounds/cnormal.mp3",
            "samourai": "sounds/samurai.mp3",
            "samouraï": "sounds/samurai.mp3",
            "saxophone": "sounds/saxophone.mp3",
            "seul": "sounds/solitude.mp3",
            "seule": "sounds/solitude.mp3",
            "solitude": "sounds/solitude.mp3",
            "souffrir": "sounds/souffrir.mp3",
            "sonic": "sounds/sonic.mp3",
            "star wars": "sounds/star.mp3",
            "staying alive": "sounds/staying.mp3",
            "suffisant": "sounds/suffisant.mp3",
            "super génial": "sounds/super.mp3",
            "switch": "sounds/nintendo.mp3",
            "tout est super": "sounds/super.mp3",
            "tout est super génial": "sounds/super.mp3",
            "tu as entendu": "sounds/bonjour.mp3",
            "twitter": "sounds/twitter.mp3",
            "une autre galaxie": "sounds/xfiles.mp3",
            "usine": "sounds/biscuit.mp3",
            "urgence": "sounds/urgence.mp3",
            "urgences": "sounds/urgence.mp3",
            "vainqueur": "sounds/yeah.mp3",
            "vampire": "sounds/castlevania.mp3",
            "velu": "sounds/chewbacca.mp3",
            "venu d'ailleurs": "sounds/xfiles.mp3",
            "venus d'ailleurs": "sounds/xfiles.mp3",
            "virus": "sounds/virus.mp3",
            "vomir": "sounds/vomir.mp3",
            "vous ne passerez pas": "sounds/vous_ne_passerez_pas.mp3",
            "warhammer": "sounds/warhammer.mp3",
            "wehrmacht": "sounds/hitler.mp3",
            "wesh": "sounds/wesh.mp3",
            "windows": "sounds/windows.mp3",
            "xbox": "sounds/xbox.mp3",
            "yoshi": "sounds/yoshi.mp3",
            "zombie": "sounds/zombie.mp3"
        }
        
        # Dictionnaire des actions système
        self.system_actions = {
            # Fichiers spécifiques
            "fichier heure de code": {
                "type": "fichier",
                "path": r"L:\Groups\mediatheque\06- SECTEUR INFORMATIQUE\9- HEURE DE CODE\Inscription HOC.xlsx",
                "action": "open_file"
            },
            "fichier jeux vidéo": {
                "type": "fichier",
                "path": r"L:\Groups\mediatheque\06- SECTEUR INFORMATIQUE\7- SALLE JVO\SERVICE PUBLIC\INSCRIPTION CRENEAUX JEUX VIDEO 2024.xlsx",
                "action": "open_file"
            },
            "lance streaming": {
                "type": "fichier",
                "path": r"apps/cam.bat",
                "action": "open_file"
            },
            "capture audio": {
                "type": "fichier",
                "path": r"apps/audio.bat",
                "action": "open_file"
            },
            "capture vidéo": {
                "type": "fichier",
                "path": r"apps/video.bat",
                "action": "open_file"
            },
            "gmail": {
                "type": "fichier",
                "path": r"apps/gma.lnk",
                "action": "open_file"
            },
            "numérique pour tous": {
                "type": "fichier",
                "path": r"apps/npm.lnk",
                "action": "open_file"
            },
            "catalogue médiathèque": {
                "type": "fichier",
                "path": r"apps/cat.lnk",
                "action": "open_file"
            },
            "modification programme": {
                "type": "fichier",
                "path": r"apps/mod.bat",
                "action": "open_file"
            },
            "contournement": {
                "type": "fichier",
                "path": r"apps/psiphon.exe",
                "action": "open_file"
            },
            "redémarrer": {
                "type": "fichier",
                "path": r"apps/restart.bat",
                "action": "open_file"
            },
            "météo": {
                "type": "fichier",
                "path": r"meteo/launch_direct.bat",
                "action": "open_file"
            },
            "météo demain": {
                "type": "fichier",
                "path": r"meteo/launch_direct.bat",
                "action": "open_file"
            },
            "prévision météo": {
                "type": "fichier",
                "path": r"meteo/launch_direct.bat",
                "action": "open_file"
            },
            "quel temps fera-t-il demain": {
                "type": "fichier",
                "path": r"meteo/launch_direct.bat",
                "action": "open_file"
            },
            "redémarrage": {
                "type": "fichier",
                "path": r"apps/restart.bat",
                "action": "open_file"
            },
            "retouche photo": {
                "type": "fichier",
                "path": r"apps/gimp.lnk",
                "action": "open_file"
            },
            "modification photo": {
                "type": "fichier",
                "path": r"apps/gimp.lnk",
                "action": "open_file"
            },
            "retouche audio": {
                "type": "fichier",
                "path": r"apps/auda.lnk",
                "action": "open_file"
            },
            "modification audio": {
                "type": "fichier",
                "path": r"apps/auda.lnk",
                "action": "open_file"
            },
            "ouvre caméra": {
                "type": "fichier",
                "path": r"L:\Groups\mediatheque\06- SECTEUR INFORMATIQUE\7- SALLE JVO\cam.html",
                "action": "open_file"
            },
            "internet": {
                "type": "fichier",
                "path": r"apps/brave.lnk",
                "action": "open_file"
            },
            "spotify": {
                "type": "fichier",
                "path": r"apps/spo.lnk",
                "action": "open_file"
            },
            "recherche profonde": {
                "type": "fichier",
                "path": r"apps/ds.lnk",
                "action": "open_file"
            },
            "outlook": {
                "type": "fichier",
                "path": r"apps/out.lnk",
                "action": "open_file"
            },
            # Applications système
            "calculatrice": {
                "type": "app",
                "command": {
                    "windows": "calc.exe",
                    "linux": "gnome-calculator",
                    "darwin": "Calculator"
                },
                "action": "launch_app"
            },
            "bloc-note": {
                "type": "app",
                "command": {
                    "windows": "notepad.exe",
                    "linux": "gedit",
                    "darwin": "open -a 'TextEdit'"
                },
                "action": "launch_app"
            },
            "explorateur de fichiers": {
                "type": "app",
                "command": {
                    "windows": "explorer.exe",
                    "linux": "nautilus",
                    "darwin": "open ."
                },
                "action": "launch_app"
            }
        }
        
        # Créer le dossier des sons s'il n'existe pas
        if not os.path.exists("sounds"):
            os.makedirs("sounds")
            
        self.is_listening = False
        
        # Callbacks pour l'interface graphique
        self.on_command_detected = None
        self.on_audio_playing = None
        self.on_error = None
        self.on_listening_start = None
        self.on_listening_stop = None
        self.on_word_heard = None  # Nouveau callback pour les mots entendus
        
    def calibrer_micro(self):
        """microphone calibration"""
        # Notifier l'interface graphique
        if self.on_word_heard:
            self.on_word_heard("Calibration audio en cours... parlez maintenant.")
            
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=2)
        
        if self.on_word_heard:
            self.on_word_heard("Calibration terminée!")
    
    def jouer_audio(self, fichier):
        """Joue un fichier audio"""
        try:
            if os.path.exists(fichier):
                # Notifier l'interface graphique
                if self.on_audio_playing:
                    self.on_audio_playing(fichier)
                
                if self.on_word_heard:
                    self.on_word_heard(f"▶️ Lecture: {os.path.basename(fichier)}")
                
                pygame.mixer.music.load(fichier)
                pygame.mixer.music.play()
                
                # Attendre que la musique se termine
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
            else:
                if self.on_error:
                    self.on_error(f"Fichier audio non trouvé: {fichier}")
        except Exception as e:
            if self.on_error:
                self.on_error(f"Erreur lors de la lecture audio: {str(e)}")
    
    def ouvrir_fichier(self, chemin_fichier):
        """Ouvre un fichier avec l'application par défaut"""
        try:
            system = platform.system().lower()
            
            # Convertir en chemin absolu
            if not os.path.isabs(chemin_fichier):
                chemin_absolu = os.path.abspath(chemin_fichier)
            else:
                chemin_absolu = chemin_fichier
            
            if not os.path.exists(chemin_absolu):
                if self.on_error:
                    self.on_error(f"Fichier introuvable: {chemin_absolu}")
                return False
            
            if system == "windows":
                subprocess.Popen(f'start "" "{chemin_absolu}"', shell=True)
            elif system == "darwin":
                subprocess.Popen(["open", chemin_absolu])
            else:
                subprocess.Popen(["xdg-open", chemin_absolu])
            
            if self.on_word_heard:
                self.on_word_heard(f"📂 Fichier ouvert: {os.path.basename(chemin_absolu)}")
            return True
            
        except Exception as e:
            if self.on_error:
                self.on_error(f"Erreur lors de l'ouverture: {str(e)}")
            return False
    
    def lancer_programme(self, commande):
        """Lance un programme"""
        try:
            system = platform.system().lower()
            
            if system == "windows":
                subprocess.Popen(commande, shell=True)
            elif system == "darwin":
                subprocess.Popen(commande, shell=True)
            else:
                subprocess.Popen(commande, shell=True)
            
            if self.on_word_heard:
                self.on_word_heard(f"🚀 Programme lancé: {commande}")
            return True
            
        except Exception as e:
            if self.on_error:
                self.on_error(f"Erreur lors du lancement: {str(e)}")
            return False
    
    def executer_action_systeme(self, action_info):
        """Exécute une action système"""
        action_type = action_info["type"]
        action = action_info["action"]
        
        if action == "open_file" and action_type == "fichier":
            chemin = action_info["path"]
            if os.path.exists(chemin):
                return self.ouvrir_fichier(chemin)
            else:
                if self.on_error:
                    self.on_error(f"Fichier système non trouvé: {chemin}")
                return False
                
        elif action == "launch_app" and action_type == "app":
            system = platform.system().lower()
            commande = action_info["command"].get(system)
            
            if commande:
                return self.lancer_programme(commande)
            else:
                if self.on_error:
                    self.on_error(f"Commande non disponible pour {system}")
                return False
        
        return False
    
    def reconnaitre_commande(self, audio):
        """Reconnaît la parole et retourne la commande"""
        try:
            # Reconnaissance en français
            texte = self.recognizer.recognize_google(audio, language="fr-FR")
            texte = texte.lower()
            
            # Afficher le texte reconnu dans l'interface
            if self.on_word_heard:
                self.on_word_heard(f"🗣️ Mot détecté: \"{texte}\"")
            
            # Vérifier les actions système d'abord
            for commande, action_info in self.system_actions.items():
                if commande in texte:
                    return commande, None, action_info
            
            # Vérifier les commandes audio
            for commande, fichier_audio in self.commands.items():
                if commande in texte:
                    return commande, fichier_audio, None
         
            return None, None, None
            
        except sr.UnknownValueError:
            if self.on_error:
                self.on_error("Voice recognition: Audio not understood")
            return None, None, None
        except sr.RequestError as e:
            if self.on_error:
                self.on_error(f"Erreur avec le service de reconnaissance: {str(e)}")
            return None, None, None
        except Exception as e:
            if self.on_error:
                self.on_error(f"Erreur inattendue: {str(e)}")
            return None, None, None
    
    def traiter_commande(self, commande, fichier_audio, action_info):
        """Traite la commande détectée"""
        if commande == "stop":
            self.is_listening = False
            return
            
        elif action_info:
            # Notifier l'interface graphique
            if self.on_command_detected:
                self.on_command_detected(commande, None, action_info)
                
            success = self.executer_action_systeme(action_info)
            if success and commande in self.commands:
                self.jouer_audio(self.commands[commande])
            
        elif commande and fichier_audio:
            # Notifier l'interface graphique
            if self.on_command_detected:
                self.on_command_detected(commande, fichier_audio, None)
                
            self.jouer_audio(fichier_audio)
    
    def ecouter_et_repondre(self):
        """Écoute en continu et répond aux commandes"""
        # Notifier le démarrage de l'écoute
        if self.on_listening_start:
            self.on_listening_start()
        
        with self.microphone as source:
            while self.is_listening:
                try:
                    # Ne pas écouter pendant la lecture audio
                    if pygame.mixer.music.get_busy():
                        time.sleep(0.1)
                        continue
                    
                    audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=5)
                    
                    # Traiter l'audio
                    commande, fichier_audio, action_info = self.reconnaitre_commande(audio)
                    if commande:
                        self.traiter_commande(commande, fichier_audio, action_info)
                    
                except sr.WaitTimeoutError:
                    continue
                except Exception as e:
                    if self.on_error:
                        self.on_error(f"Erreur d'écoute: {str(e)}")
        
        # Notifier l'arrêt de l'écoute
        if self.on_listening_stop:
            self.on_listening_stop()
    
    def demarrer(self):
        """Démarre le système de reconnaissance"""
        self.calibrer_micro()
        self.is_listening = True
        
        # Démarrer dans un thread
        self.thread_ecoute = threading.Thread(target=self.ecouter_et_repondre)
        self.thread_ecoute.daemon = True
        self.thread_ecoute.start()


def verifier_fichiers_audio():
    """Vérifie la présence des fichiers audio (sans affichage console)"""
    sounds_dir = "sounds"
    fichiers_manquants = []
    
    if os.path.exists(sounds_dir):
        return True
    else:
        os.makedirs(sounds_dir)
        return False


if __name__ == "__main__":
    # Toujours lancer avec l'interface graphique
    try:
        from ear_gui import VoiceAssistantGUI
        
        # Cacher la console Windows
        if platform.system() == "Windows":
            import ctypes
            ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
        
        verifier_fichiers_audio()
        
        # Démarrer l'application
        app = AudioCommandRecognizer()
        gui = VoiceAssistantGUI(app)
        gui.run()
        
    except ImportError as e:
        # En cas d'erreur, afficher une boîte de dialogue
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Erreur", f"Impossible de lancer l'interface graphique:\n{e}")