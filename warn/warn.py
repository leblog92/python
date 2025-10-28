import pyaudio
import numpy as np
import pygame
import threading
import time
import os

class SoundMonitorWithVisualization:
    def __init__(self):
        self.threshold = 20000  # Seuil pour la parole normale
        self.is_running = False
        self.pyaudio = pyaudio.PyAudio()
        self.max_level = 0
        self.detection_count = 0
        
        # Initialisation pygame pour l'audio
        pygame.mixer.init()
        
    def safe_rms(self, data):
        """Calcul RMS totalement sécurisé"""
        if not data or len(data) < 2:
            return 0
        try:
            audio_data = np.frombuffer(data, dtype=np.int16)
            if len(audio_data) == 0:
                return 0
            squared = np.square(audio_data.astype(np.float64))
            mean_squared = np.mean(squared)
            return np.sqrt(abs(mean_squared)) if mean_squared > 0 else 0
        except:
            return 0
    
    def draw_volume_bar(self, current_level, threshold, max_level=32768):
        """Crée une visualisation graphique du volume"""
        width = 50  # Largeur de la barre en caractères
        
        # Niveau actuel en pourcentage
        current_percent = min(current_level / max_level, 1.0)
        threshold_percent = min(threshold / max_level, 1.0)
        
        # Calcul des positions
        current_pos = int(current_percent * width)
        threshold_pos = int(threshold_percent * width)
        
        # Construction de la barre
        bar = ""
        for i in range(width):
            if i == threshold_pos:
                bar += "|"  # Marqueur du seuil
            elif i < current_pos:
                if i < threshold_pos:
                    bar += "█"  # En dessous du seuil
                else:
                    bar += "▒"  # Au dessus du seuil (détection)
            else:
                bar += " "  # Vide
        
        return bar, current_percent, threshold_percent
    
    def show_help(self):
        """Affiche les commandes disponibles"""
        print("\n" + "="*60)
        print("🎵 COMMANDES DISPONIBLES PENDANT LA SURVEILLANCE:")
        print("="*60)
        print("s : Afficher les statistiques actuelles")
        print("t : Changer le seuil manuellement")
        print("h : Afficher cette aide")
        print("q : Quitter le programme")
        print("="*60)
    
    def start_interactive_monitoring(self):
        """Démarre la surveillance avec interface interactive"""
        print("🔊 MONITEUR SONORE AVEC VISUALISATION")
        print(f"🎯 Seuil initial: {self.threshold}")
        print("💡 Tapez 'h' pendant la surveillance pour l'aide")
        
        # Initialisation du flux audio
        try:
            stream = self.pyaudio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=44100,
                input=True,
                frames_per_buffer=1024
            )
        except Exception as e:
            print(f"❌ Erreur microphone: {e}")
            return
        
        # Chargement du son d'alerte
        try:
            alert_sound = pygame.mixer.Sound("alert.wav")
            print("✅ Son d'alerte chargé")
        except:
            print("❌ Fichier alert.wav non trouvé")
            alert_sound = None
        
        self.is_running = True
        cooldown = 0
        last_levels = []  # Historique pour moyenne mobile
        
        print("\n🚀 Démarrage de la surveillance...")
        self.show_help()
        
        try:
            while self.is_running:
                # Vérifier les entrées utilisateur
                if self.check_user_input():
                    continue
                
                # Lecture audio
                try:
                    data = stream.read(1024, exception_on_overflow=False)
                    current_level = self.safe_rms(data)
                    
                    # Mise à jour du niveau maximum
                    self.max_level = max(self.max_level, current_level)
                    
                    # Historique pour moyenne mobile
                    last_levels.append(current_level)
                    if len(last_levels) > 10:
                        last_levels.pop(0)
                    avg_level = np.mean(last_levels) if last_levels else current_level
                    
                    # Visualisation
                    bar, current_percent, threshold_percent = self.draw_volume_bar(
                        current_level, self.threshold
                    )
                    
                    # Affichage avec codes couleur (approximatifs)
                    status = "NORMAL"
                    if current_level > self.threshold:
                        status = "DÉTECTION!"
                        color_code = "\033[91m"  # Rouge
                        reset_code = "\033[0m"
                    else:
                        color_code = "\033[92m"  # Vert
                        reset_code = "\033[0m"
                    
                    print(f"\r{color_code}Niveau: {int(current_level):5d} | Seuil: {self.threshold:5d} | {status:10s} [{bar}]{reset_code}", end="")
                    
                    # Détection
                    if current_level > self.threshold and cooldown <= 0:
                        self.detection_count += 1
                        print(f"\n🚨 CRIS DÉTECTÉ! (#{self.detection_count}) - Niveau: {int(current_level)}")
                        
                        if alert_sound:
                            threading.Thread(
                                target=alert_sound.play,
                                daemon=True
                            ).start()
                        
                        cooldown = 3  # 3 secondes de cooldown
                    
                    # Mise à jour cooldown
                    if cooldown > 0:
                        cooldown -= 0.1
                    
                    time.sleep(0.05)
                    
                except IOError:
                    time.sleep(0.1)
                    
        except KeyboardInterrupt:
            print("\n\n🛑 Arrêt demandé...")
        finally:
            stream.stop_stream()
            stream.close()
            self.pyaudio.terminate()
            if pygame.mixer.get_init():
                pygame.mixer.quit()
            print(f"\n📊 Statistiques finales:")
            print(f"   - Détections: {self.detection_count}")
            print(f"   - Niveau maximum: {int(self.max_level)}")
            print(f"   - Seuil final: {self.threshold}")
            print("✅ Fermeture terminée")
    
    def check_user_input(self):
        """Vérifie les entrées utilisateur non-bloquantes"""
        try:
            import msvcrt  # Windows
            if msvcrt.kbhit():
                key = msvcrt.getch().decode('utf-8').lower()
                return self.handle_user_input(key)
        except:
            try:
                import sys
                import select
                # Unix/Linux/Mac
                if select.select([sys.stdin], [], [], 0)[0]:
                    key = sys.stdin.readline().strip().lower()
                    return self.handle_user_input(key)
            except:
                pass
        return False
    
    def handle_user_input(self, key):
        """Gère les entrées utilisateur"""
        if key == 's':
            print(f"\n\n📊 STATISTIQUES:")
            print(f"   - Détections: {self.detection_count}")
            print(f"   - Niveau max historique: {int(self.max_level)}")
            print(f"   - Seuil actuel: {self.threshold}")
            print(f"   - Niveau max possible: 32768")
            input("   Appuyez sur Entrée pour continuer...")
            return True
        elif key == 't':
            try:
                print("\n")
                new_threshold = int(input("   Nouveau seuil: "))
                if 100 <= new_threshold <= 32768:
                    self.threshold = new_threshold
                    print(f"   ✅ Seuil changé à: {self.threshold}")
                else:
                    print("   ❌ Seuil doit être entre 100 et 32768")
                input("   Appuyez sur Entrée pour continuer...")
            except ValueError:
                print("   ❌ Valeur invalide")
            return True
        elif key == 'h':
            self.show_help()
            input("   Appuyez sur Entrée pour continuer...")
            return True
        elif key == 'q':
            self.is_running = False
            return True
        return False

def main():
    """Fonction principale"""
    print("="*60)
    print("        DÉTECTEUR DE CRIS AVEC VISUALISATION")
    print("="*60)
    
    monitor = SoundMonitorWithVisualization()
    monitor.start_interactive_monitoring()

if __name__ == "__main__":
    main()