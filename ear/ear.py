import speech_recognition as sr
import pygame
import time
import os
import subprocess
import threading
import platform
import webbrowser
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
            "approximatif": "sounds/oh.mp3",
            "approximative": "sounds/oh.mp3",
            "approximativement": "sounds/oh.mp3",
            "assistante": "sounds/assistante.mp3",
            "astucieux": "sounds/debile.mp3",
            "attention au matériel": "sounds/pete.mp3",
            "au revoir": "sounds/au_revoir.mp3",
            "bière": "sounds/biere.mp3",
            "biscuit": "sounds/biscuit.mp3",
            "bisou": "sounds/bisou.mp3",
            "bisous": "sounds/bisou.mp3",
            "bonne année": "sounds/new-year.mp3",
            "castlevania": "sounds/castlevania.mp3",
            "cavalier": "sounds/cheval.mp3",
            "c'est nul": "sounds/cnul.mp3",
            "j'ai vu ça sur internet": "sounds/vrai.mp3",
            "tu as vu ça sur internet": "sounds/vrai.mp3",
            "chat": "sounds/miaou.mp3",
            "cheval": "sounds/cheval.mp3",
            "chewbacca": "sounds/chewbacca.mp3",
            "chiffrement": "sounds/pasfaux.mp3",
            "ciao": "sounds/ciao.mp3",
            "communiste": "sounds/coco.mp3",
            "coucou": "sounds/coucou.mp3",
            "dark souls": "sounds/darksouls.mp3",
            "dernière minute": "sounds/countdown.mp3",
            "dernières minutes": "sounds/countdown.mp3",
            "dominique": "sounds/michel.mp3",
            "erreur": "sounds/erreur.mp3",
            "expire": "sounds/expire.mp3",
            "expiré": "sounds/expire.mp3",
            "expirer": "sounds/expire.mp3",
            "facebook": "sounds/facebook.mp3",
            "faim": "sounds/faim.mp3",
            "fc 24": "sounds/fifa.mp3",
            "fc 25": "sounds/fifa.mp3",
            "fc 26": "sounds/fifa.mp3",
            "fifa": "sounds/fifa.mp3",
            "fin de partie": "sounds/fin.mp3",
            "fin de session": "sounds/final_countdown.mp3",
            "final countdown": "sounds/final_countdown.mp3",
            "fortnite": "sounds/robocop.mp3",
            "français": "sounds/french.mp3",
            "frère": "sounds/frere.mp3",
            "from software": "sounds/darksouls.mp3",
            "gérard": "sounds/michel.mp3",
            "gévaudan": "sounds/bete.mp3",
            "goodbye": "sounds/goodbye.mp3",
            "grève": "sounds/greve.mp3",
            "hello": "sounds/hello.mp3",
            "heure de code": "sounds/hoc.mp3",
            "hitler": "sounds/nein.mp3",
            "houston": "sounds/problem.mp3",
            "incongru": "sounds/pasfaux.mp3",
            "injuste": "sounds/pauvre.mp3",
            "inscription": "sounds/inscription.mp3",
            "inscrire": "sounds/inscription.mp3",
            "italie": "sounds/italie.mp3",
            "j'ai une théorie": "sounds/chagrin.mp3",
            "je suis choqué": "sounds/shock.mp3",
            "j'en ai marre": "sounds/marre.mp3",
            "jérémy": "sounds/souffrance.mp3",
            "johnny": "sounds/coucou2.mp3",
            "léon": "sounds/leon.mp3",
            "malheur": "sounds/malheur.mp3",
            "malheureuse": "sounds/malheur.mp3",
            "malheureux": "sounds/malheur.mp3",
            "mario": "sounds/mario.mp3",
            "mathieu": "sounds/matthieu.mp3",
            "maurice": "sounds/maurice.mp3",
            "merci beaucoup": "sounds/merci.mp3",
            "mes profs": "sounds/demon.mp3",
            "miaou": "sounds/miaou.mp3",
            "michel": "sounds/michel.mp3",
            "microsoft": "sounds/microsoft.mp3",
            "minecraft": "sounds/minecraft.mp3",
            "modalité": "sounds/modalites.mp3",
            "modalités": "sounds/modalites.mp3",
            "mouton": "sounds/mouton.mp3",
            "moutons": "sounds/mouton.mp3",
            "mortal kombat": "sounds/mortal_kombat.mp3",
            "mozzarella": "sounds/italie.mp3",
            "nathalie": "sounds/bisou.mp3",
            "nazi": "sounds/hitler.mp3",
            "neige": "sounds/neige.mp3",
            "nintendo": "sounds/nintendo.mp3",
            "nurgle": "sounds/nurgle.mp3",
            "olivier": "sounds/olivier.mp3",
            "papa": "sounds/papa.mp3",
            "paradoxal": "sounds/pasfaux.mp3",
            "parmesan": "sounds/italie.mp3",
            "pauvres": "sounds/pauvres.mp3",
            "pénible": "sounds/penible.mp3",
            "perceval": "sounds/chagrin.mp3",
            "père": "sounds/papa.mp3",
            "périmé": "sounds/perime.mp3",
            "périmée": "sounds/perime.mp3",
            "périmer": "sounds/perime.mp3",
            "philippe": "sounds/philippe.mp3",
            "pikachu": "sounds/pikachu.mp3",
            "pilotage": "sounds/pilote.mp3",
            "pilote": "sounds/pilote.mp3",
            "playstation": "sounds/playstation.mp3",
            "pleurer": "sounds/pleurer.mp3",
            "pleurnicher": "sounds/pleurer.mp3",
            "poilu": "sounds/chewbacca.mp3",
            "pokémon": "sounds/pikachu.mp3",
            "poney": "sounds/poney.mp3",
            "predator": "sounds/predator.mp3",
            "gros problème": "sounds/problem.mp3",
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
            "samouraï": "sounds/samurai.mp3",
            "saxophone": "sounds/saxophone.mp3",
            "seul": "sounds/solitude.mp3",
            "seule": "sounds/solitude.mp3",
            "solitude": "sounds/solitude.mp3",
            "sonic": "sounds/sonic.mp3",
            "star wars": "sounds/star.mp3",
            "staying alive": "sounds/staying.mp3",
            "suffisant": "sounds/suffisant.mp3",
            "switch": "sounds/nintendo.mp3",
            "tu as entendu": "sounds/bonjour.mp3",
            "twitter": "sounds/twitter.mp3",
            "usine": "sounds/biscuit.mp3",
            "vainqueur": "sounds/yeah.mp3",
            "vampire": "sounds/castlevania.mp3",
            "venu d'ailleurs": "sounds/xfiles.mp3",
            "venus d'ailleurs": "sounds/xfiles.mp3",
            "une autre galaxie": "sounds/xfiles.mp3",
            "une autre planète": "sounds/xfiles.mp3",
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
                    "mac": "Calculator"
                },
                "action": "launch_app"
            },
            "bloc-note": {
                "type": "app",
                "command": {
                    "windows": "notepad.exe",
                    "linux": "gedit",
                    "mac": "open -a 'TextEdit'"
                },
                "action": "launch_app"
            },
            "explorateur de fichiers": {
                "type": "app",
                "command": {
                    "windows": "explorer.exe",
                    "linux": "nautilus",
                    "mac": "open ."
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
        
    def calibrer_micro(self):
        """microphone calibration"""
        print("")
        print("=====================")
        print("microphone calibration... speak now.")
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=2)
        print("calibration completed!")
        print("=====================")
    
    def jouer_audio(self, fichier):
        """Joue un fichier audio"""
        try:
            if os.path.exists(fichier):
                # Notifier l'interface graphique
                if self.on_audio_playing:
                    self.on_audio_playing(fichier)
                
                pygame.mixer.music.load(fichier)
                pygame.mixer.music.play()
                print(f"Joue: {fichier}")
                
                # Attendre que la musique se termine
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
                    
                print("Lecture terminée, reprise de l'écoute...")
            else:
                print(f"Fichier audio non trouvé: {fichier}")
        except Exception as e:
            print(f"Erreur lors de la lecture audio: {e}")
            # Notifier l'erreur à l'interface graphique
            if self.on_error:
                self.on_error(f"Erreur audio: {str(e)}")
    
    def ouvrir_fichier(self, chemin_fichier):
        """Ouvre un fichier avec l'application par défaut"""
        try:
            system = platform.system().lower()
            
            # Convertir en chemin absolu
            if not os.path.isabs(chemin_fichier):
                chemin_absolu = os.path.abspath(chemin_fichier)
            else:
                chemin_absolu = chemin_fichier
            
            print(f"Ouverture du fichier: {chemin_absolu}")
            
            if not os.path.exists(chemin_absolu):
                print(f"ERREUR: Fichier introuvable: {chemin_absolu}")
                # Notifier l'erreur à l'interface graphique
                if self.on_error:
                    self.on_error(f"Fichier introuvable: {chemin_absolu}")
                return False
            
            if system == "windows":
                # Sous Windows, utiliser start pour les fichiers batch
                subprocess.Popen(f'start "" "{chemin_absolu}"', shell=True)
                
            elif system == "darwin":  # macOS
                subprocess.Popen(["open", chemin_absolu])
            else:  # Linux
                subprocess.Popen(["xdg-open", chemin_absolu])
            
            print(f"✓ Fichier ouvert avec succès")
            return True
            
        except Exception as e:
            print(f"✗ Erreur lors de l'ouverture: {e}")
            # Notifier l'erreur à l'interface graphique
            if self.on_error:
                self.on_error(f"Erreur ouverture fichier: {str(e)}")
            return False
    
    def lancer_programme(self, commande):
        """Lance un programme"""
        try:
            system = platform.system().lower()
            
            if system == "windows":
                # Pour Windows
                subprocess.Popen(commande, shell=True)
            elif system == "darwin":  # macOS
                subprocess.Popen(commande, shell=True)
            else:  # Linux
                subprocess.Popen(commande, shell=True)
            
            print(f"Programme lancé: {commande}")
            return True
            
        except Exception as e:
            print(f"Erreur lors du lancement du programme: {e}")
            # Notifier l'erreur à l'interface graphique
            if self.on_error:
                self.on_error(f"Erreur lancement programme: {str(e)}")
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
                print(f"Fichier non trouvé: {chemin}")
                # Notifier l'erreur à l'interface graphique
                if self.on_error:
                    self.on_error(f"Fichier système non trouvé: {chemin}")
                return False
                
        elif action == "launch_app" and action_type == "app":
            system = platform.system().lower()
            commande = action_info["command"].get(system)
            
            if commande:
                return self.lancer_programme(commande)
            else:
                print(f"Commande non disponible pour {system}")
                # Notifier l'erreur à l'interface graphique
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
            print(f"Vous avez dit: {texte}")
            
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
            print("Désolé, je n'ai pas compris")
            # Notifier l'erreur à l'interface graphique
            if self.on_error:
                self.on_error("Reconnaissance vocale: Audio non compris")
            return None, None, None
        except sr.RequestError as e:
            print(f"Erreur avec le service de reconnaissance: {e}")
            # Notifier l'erreur à l'interface graphique
            if self.on_error:
                self.on_error(f"Erreur service reconnaissance: {str(e)}")
            return None, None, None
        except Exception as e:
            print(f"Erreur inattendue: {e}")
            # Notifier l'erreur à l'interface graphique
            if self.on_error:
                self.on_error(f"Erreur inattendue: {str(e)}")
            return None, None, None
    
    def traiter_commande(self, commande, fichier_audio, action_info):
        """Traite la commande détectée"""
        if commande == "stop":
            self.is_listening = False
            print("Arrêt de l'écoute...")
            return
            
        elif action_info:
            print(f"Action système détectée: '{commande}'")
            
            # Notifier l'interface graphique
            if self.on_command_detected:
                self.on_command_detected(commande, None, action_info)
                
            success = self.executer_action_systeme(action_info)
            if success and commande in self.commands:
                # Si une commande audio est aussi associée, la jouer
                self.jouer_audio(self.commands[commande])
            
        elif commande and fichier_audio:
            print(f"Commande audio détectée: '{commande}'")
            
            # Notifier l'interface graphique
            if self.on_command_detected:
                self.on_command_detected(commande, fichier_audio, None)
                
            self.jouer_audio(fichier_audio)
    
    def ecouter_et_repondre(self):
        """Écoute en continu et répond aux commandes"""
        print("Écoute en cours...")
        
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
                    
                    # Écouter avec timeout
                    print("En écoute...")
                    audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=5)
                    
                    # Traiter l'audio
                    commande, fichier_audio, action_info = self.reconnaitre_commande(audio)
                    if commande:
                        self.traiter_commande(commande, fichier_audio, action_info)
                    
                except sr.WaitTimeoutError:
                    continue
                except Exception as e:
                    print(f"Erreur d'écoute: {e}")
                    # Notifier l'erreur
                    if self.on_error:
                        self.on_error(f"Erreur écoute: {str(e)}")
        
        # Notifier l'arrêt de l'écoute
        if self.on_listening_stop:
            self.on_listening_stop()
    
    def ajouter_commande_systeme(self, commande, chemin_fichier=None, programme=None):
        """Ajoute une nouvelle commande système"""
        if chemin_fichier:
            self.system_actions[commande] = {
                "type": "fichier",
                "path": chemin_fichier,
                "action": "open_file"
            }
            print(f"Commande système ajoutée: '{commande}' -> {chemin_fichier}")
            
        elif programme:
            self.system_actions[commande] = {
                "type": "app",
                "command": programme,
                "action": "launch_app"
            }
            print(f"Commande système ajoutée: '{commande}' -> {programme}")
    
    def demarrer(self):
        """Démarre le système de reconnaissance"""
        print("=== Système de Reconnaissance Vocale ===")
        print("Commandes disponibles:")
        
        print("\nCommandes audio:")
        for commande in self.commands.keys():
            print(f" - {commande}")
        
        print("\nCommandes système:")
        for commande in self.system_actions.keys():
            print(f" - {commande}")
        
        self.calibrer_micro()
        self.is_listening = True
        
        # Démarrer dans un thread pour permettre l'arrêt propre
        self.thread_ecoute = threading.Thread(target=self.ecouter_et_repondre)
        self.thread_ecoute.daemon = True
        self.thread_ecoute.start()
        
        # Maintenir le programme actif
        try:
            while self.is_listening:
                time.sleep(0.1)
        except KeyboardInterrupt:
            self.is_listening = False
            print("\nProgramme arrêté par l'utilisateur")
        finally:
            pygame.mixer.quit()


def creer_fichiers_exemple():
    """Crée des fichiers audio d'exemple (à remplacer par vos propres fichiers)"""
    sounds_dir = "sounds"
    
    # Message pour indiquer qu'il faut ajouter des vrais fichiers audio
    fichiers_necessaires = [
        "au_revoir.mp3", "bonjour.mp3", "expire.mp3", 
        "inscription.mp3", "matthieu.mp3", "merci.mp3",
        "modalites.mp3", "olivier.mp3", "playstation.mp3",
        "nintendo.mp3", "xbox.mp3", "mario.mp3", "sonic.mp3",
        "vous_ne_passerez_pas.mp3", "coucou.mp3", "hoc.mp3",
        "windows.mp3"
    ]
    
    fichiers_manquants = []
    for fichier in fichiers_necessaires:
        chemin = os.path.join(sounds_dir, fichier)
        if not os.path.exists(chemin):
            fichiers_manquants.append(fichier)
    
    if fichiers_manquants:
        print("\n⚠️ Fichiers audio manquants:")
        for fichier in fichiers_manquants:
            print(f"   - {fichier}")
        print("\nPour utiliser l'application:")
        print("1. Ajoutez vos fichiers MP3 dans le dossier 'sounds/'")
        print("2. Modifiez le dictionnaire 'commands' si nécessaire")
        print("3. Lancez le programme")
    else:
        print("✓ Tous les fichiers audio sont présents. Lancement possible.")


if __name__ == "__main__":
    # Changer le répertoire de travail vers le dossier du script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    # Vérifier si on doit lancer avec interface graphique
    launch_gui = "--gui" in sys.argv or len(sys.argv) == 1
    
    if launch_gui:
        try:
            # Essayer d'importer l'interface graphique
            from ear_gui import VoiceAssistantGUI
            
            print("=== Lancement avec interface graphique ===")
            creer_fichiers_exemple()
            
            # Démarrer l'application
            app = AudioCommandRecognizer()
            
            # Démarrer l'interface graphique
            gui = VoiceAssistantGUI(app)
            gui.run()
            
        except ImportError as e:
            print(f"⚠️ Interface graphique non disponible: {e}")
            print("Lancement en mode console...")
            creer_fichiers_exemple()
            app = AudioCommandRecognizer()
            app.demarrer()
    else:
        # Mode console explicite
        print("=== Lancement en mode console ===")
        creer_fichiers_exemple()
        app = AudioCommandRecognizer()
        app.demarrer()