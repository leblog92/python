import time
import datetime
import winsound
import pyttsx3
import threading
from datetime import datetime
import queue
import msvcrt

class SessionNotifier:
    def __init__(self):
        self.engine = pyttsx3.init()
        self.running = True
        self.last_announcement = None
        self.announcement_queue = queue.Queue()
        self.tts_lock = threading.Lock()
        
        # Configuration des annonces (heure: (fichier_son, message))
        self.schedule = {
            (14, 0): (None, "Début de session"),
            (14, 30): ("son1.wav", "Il reste 30 minutes"),
            (14, 45): ("son1.wav", "Il reste 15 minutes"),
            (14, 50): ("son1.wav", "Il reste 10 minutes"),
            (14, 58): ("son2.wav", "Fin de session"),
            (15, 30): ("son1.wav", "Il reste 30 minutes"),
            (15, 45): ("son1.wav", "Il reste 15 minutes"),
            (15, 50): ("son1.wav", "Il reste 10 minutes"),
            (15, 58): ("son2.wav", "Fin de session"),
            (16, 30): ("son1.wav", "Il reste 30 minutes"),
            (16, 45): ("son1.wav", "Il reste 15 minutes"),
            (16, 50): ("son1.wav", "Il reste 10 minutes"),
            (16, 58): ("son2.wav", "Fin de session"),
            (17, 30): ("son1.wav", "Il reste 30 minutes"),
            (17, 45): ("son1.wav", "Il reste 15 minutes"),
            (17, 50): ("son1.wav", "Il reste 10 minutes"),
            (17, 58): ("son2.wav", "Fin de session")
        }
        
        # Démarrer le worker de traitement des annonces
        self.worker_thread = threading.Thread(target=self._process_announcements)
        self.worker_thread.daemon = True
        self.worker_thread.start()
        
    def set_voice_hortense(self):
        """Configure la voix Microsoft Hortense"""
        try:
            voices = self.engine.getProperty('voices')
            
            # Chercher Microsoft Hortense
            for voice in voices:
                if "hortense" in voice.name.lower():
                    self.engine.setProperty('voice', voice.id)
                    # Ajuster les paramètres pour une meilleure qualité
                    self.engine.setProperty('rate', 150)  # Vitesse moyenne
                    self.engine.setProperty('volume', 0.9)  # Volume élevé
                    print(f"✓ Voix configurée : {voice.name}")
                    return True
            
            print("✗ Microsoft Hortense non trouvée, utilisation de la voix par défaut")
            return False
            
        except Exception as e:
            print(f"Erreur configuration voix : {e}")
            return False
    
    def play_sound(self, sound_file):
        """Joue un fichier WAV"""
        if sound_file:
            try:
                winsound.PlaySound(sound_file, winsound.SND_FILENAME)
                print(f"🔊 Son joué : {sound_file}")
                return True
            except Exception as e:
                print(f"❌ Erreur lecture son {sound_file}: {e}")
                # Test avec un son système en cas d'erreur
                try:
                    print("🔄 Essai avec un son système...")
                    winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS)
                    print("✓ Son système joué à la place")
                    return True
                except:
                    print("❌ Impossible de jouer aucun son")
                    return False
        return True
    
    def speak_text(self, text):
        """Prononce le texte avec la voix synthétique (thread-safe)"""
        with self.tts_lock:
            try:
                # Recréer le moteur TTS à chaque fois pour éviter les blocages
                temp_engine = pyttsx3.init()
                self.set_voice_hortense()
                temp_engine.say(text)
                temp_engine.runAndWait()
                temp_engine.stop()
                print(f"🗣️ Message prononcé : {text}")
                return True
            except Exception as e:
                print(f"❌ Erreur synthèse vocale : {e}")
                return False
    
    def _process_announcements(self):
        """Worker thread pour traiter les annonces en séquence"""
        while self.running:
            try:
                # Attendre une annonce avec timeout
                announcement = self.announcement_queue.get(timeout=1.0)
                if announcement is None:  # Signal d'arrêt
                    break
                    
                sound_file, message = announcement
                
                # Jouer le son si présent
                if sound_file:
                    if self.play_sound(sound_file):
                        time.sleep(2.0)  # ⏱️ Attend la fin du son
                
                # Prononcer le message
                self.speak_text(message)
                
                self.announcement_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"❌ Erreur dans le worker d'annonces : {e}")
    
    def make_announcement(self, sound_file, message):
        """Ajoute une annonce à la file d'attente"""
        try:
            self.announcement_queue.put((sound_file, message))
            print(f"📨 Annonce ajoutée à la file : {message}")
        except Exception as e:
            print(f"❌ Erreur ajout annonce à la file : {e}")
    
    def get_paris_time(self):
        """Retourne l'heure actuelle de Paris"""
        return datetime.now()
    
    def should_announce(self, current_time):
        """Vérifie si une annonce doit être faite à l'heure actuelle"""
        current_key = (current_time.hour, current_time.minute)
        
        if current_key in self.schedule:
            announcement_id = f"{current_key}_{current_time.date()}"
            
            # Éviter les annonces répétées dans la même minute
            if announcement_id != self.last_announcement:
                self.last_announcement = announcement_id
                return True
        
        return False
    
    def test_all_sequences(self):
        """Teste toutes les séquences d'annonces les unes après les autres"""
        print("\n" + "="*60)
        print("🧪 TEST DE TOUTES LES SÉQUENCES D'ANNONCES")
        print("="*60)
        
        # Obtenir toutes les annonces triées par heure
        sorted_schedule = sorted(self.schedule.items())
        
        print(f"🎯 {len(sorted_schedule)} annonces à tester...")
        print("⏳ Démarrage dans 3 secondes...")
        time.sleep(3)
        
        for i, ((hour, minute), (sound_file, message)) in enumerate(sorted_schedule):
            print(f"\n[{i+1}/{len(sorted_schedule)}] Test annonce {hour:02d}h{minute:02d} :")
            print(f"   🔊 Son : {sound_file if sound_file else 'Aucun'}")
            print(f"   🗣️ Message : '{message}'")
            
            # Traitement direct sans file d'attente pour le test
            if sound_file:
                print("   🔈 Lecture du son...")
                self.play_sound(sound_file)
                time.sleep(2)  # Pause après le son
            
            print("   🗣️ Synthèse vocale...")
            self.speak_text(message)
            
            # Pause plus longue entre les annonces
            if i < len(sorted_schedule) - 1:  # Pas de pause après la dernière
                print("   ⏳ Pause de 3 secondes...")
                time.sleep(3)
            
            print("   ✅ Annonce traitée")
        
        print("\n" + "="*60)
        print("✅ TOUS LES TESTS TERMINÉS !")
        print("="*60)
    
    def test_simple_voice(self):
        """Test simple de la voix sans file d'attente"""
        print("\n🔊 TEST SIMPLE DE LA VOIX")
        test_messages = [
            "Test voix un",
            "Test voix deux", 
            "Test voix trois"
        ]
        
        for msg in test_messages:
            print(f"🎯 Test: {msg}")
            self.speak_text(msg)
            time.sleep(1)
    
    def test_simple_sound(self):
        """Test simple des sons"""
        print("\n🔊 TEST SIMPLE DES SONS")
        # Test avec sons système
        system_sounds = ["SystemExclamation", "SystemAsterisk", "SystemQuestion"]
        for sound in system_sounds:
            print(f"🎵 Test son: {sound}")
            try:
                winsound.PlaySound(sound, winsound.SND_ALIAS)
                time.sleep(1)
            except Exception as e:
                print(f"❌ Erreur: {e}")
    
    def run(self):
        """Boucle principale du programme"""
        print("🚀 Démarrage du programme de notifications de session")
        print("⏰ Fuseau horaire : Paris")
        print("📅 Notifications programmées :")
        
        for time_key, (sound, message) in sorted(self.schedule.items()):
            print(f"  {time_key[0]:02d}h{time_key[1]:02d} : {message} ({sound if sound else 'pas de son'})")
        
        print("\n🔊 Configuration de la voix...")
        self.set_voice_hortense()
        
        print("\n🎮 CONTROLES :")
        print("  • Appuyez sur 'T' pour tester toutes les séquences")
        print("  • Appuyez sur 'V' pour tester la voix seule")
        print("  • Appuyez sur 'S' pour tester les sons seuls")
        print("  • Appuyez sur Ctrl+C pour arrêter le programme")
        print("\n✅ Le programme tourne en arrière-plan...")
        
        try:
            while self.running:
                # Vérifier si une touche est pressée
                if msvcrt.kbhit():
                    key = msvcrt.getch().decode('utf-8').lower()
                    if key == 't':
                        self.test_all_sequences()
                        print("\n✅ Retour au mode normal...")
                    elif key == 'v':
                        self.test_simple_voice()
                        print("\n✅ Retour au mode normal...")
                    elif key == 's':
                        self.test_simple_sound()
                        print("\n✅ Retour au mode normal...")
                
                current_time = self.get_paris_time()
                
                if self.should_announce(current_time):
                    sound_file, message = self.schedule[(current_time.hour, current_time.minute)]
                    print(f"\n🎯 [{current_time.strftime('%H:%M:%S')}] Annonce déclenchée !")
                    self.make_announcement(sound_file, message)
                
                # Vérifier toutes les 0.5 secondes pour une meilleure réactivité
                time.sleep(0.5)
                
        except KeyboardInterrupt:
            print("\n🛑 Arrêt du programme demandé...")
        except Exception as e:
            print(f"❌ Erreur inattendue : {e}")
        finally:
            self.running = False
            # Signal d'arrêt pour le worker
            self.announcement_queue.put(None)
    
    def __del__(self):
        """Nettoyage"""
        self.running = False
        if hasattr(self, 'engine'):
            try:
                self.engine.stop()
            except:
                pass

if __name__ == "__main__":
    # Vérification des dépendances
    try:
        import pyttsx3
        import winsound
        import msvcrt
    except ImportError as e:
        print(f"❌ Dépendance manquante : {e}")
        print("💡 Installez avec : pip install pyttsx3")
        exit(1)
    
    # Lancement du programme
    notifier = SessionNotifier()
    notifier.run()