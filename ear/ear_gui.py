import tkinter as tk
import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import queue
from datetime import datetime
import os
import random

class VoiceAssistantGUI:
    def __init__(self, voice_recognizer):
        self.recognizer = voice_recognizer
        self.root = tk.Tk()
        self.root.title("Assistant Vocal - EAR 🔊")
        self.root.geometry("800x600")
        
        # Configuration de la file d'attente pour la communication thread-safe
        self.message_queue = queue.Queue()
        
        # Variables pour les statistiques
        self.command_count = 0
        self.success_count = 0
        self.start_time = datetime.now()
        
        # Style moderne
        self.setup_styles()
        
        # Création de l'interface
        self.create_widgets()
        
        # Connecter les callbacks
        self.connect_callbacks()
        
        # Démarrer la vérification des messages
        self.check_queue()
        
        # Mettre à jour les statistiques périodiquement
        self.update_stats()
           
        # Démarrer la vérification des messages
        self.check_queue()
        
        # Mettre à jour les statistiques périodiquement
        self.update_stats()
        
        # Démarrer l'écoute automatiquement (après un court délai)
        self.root.after(1000, self.start_listening)  # <-- ADD THIS LINE
        
    def setup_styles(self):
        """Configure les styles pour une apparence moderne"""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Couleurs
        self.bg_color = "#2b2b2b"
        self.fg_color = "#ffffff"
        self.accent_color = "#4a9eff"
        self.success_color = "#4CAF50"
        self.error_color = "#f44336"
        self.warning_color = "#ff9800"
        
        # Configuration de la fenêtre principale
        self.root.configure(bg=self.bg_color)
        
    def create_widgets(self):
        """Crée tous les widgets de l'interface"""
        
        # ===== EN-TÊTE =====
        header_frame = tk.Frame(self.root, bg=self.bg_color)
        header_frame.pack(fill="x", padx=20, pady=(20, 10))
        
        # Logo/Titre
        title_label = tk.Label(
            header_frame,
            text="👂 EAR - Enhanced Audio Recognition",
            font=("Segoe UI", 24, "bold"),
            fg=self.accent_color,
            bg=self.bg_color
        )
        title_label.pack(side="left")
        
        # Indicateur d'état
        self.status_var = tk.StringVar(value="🔴 stopped")
        self.status_label = tk.Label(
            header_frame,
            textvariable=self.status_var,
            font=("Segoe UI", 12),
            fg=self.fg_color,
            bg=self.bg_color
        )
        self.status_label.pack(side="right")
        
        # ===== SECTION PRINCIPALE =====
        main_frame = tk.Frame(self.root, bg=self.bg_color)
        main_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        # Panneau gauche - Contrôles
        left_panel = tk.Frame(main_frame, bg=self.bg_color)
        left_panel.pack(side="left", fill="y", padx=(0, 10))
        
        # Panneau droit - Logs
        right_panel = tk.Frame(main_frame, bg=self.bg_color)
        right_panel.pack(side="right", fill="both", expand=True)
        
        # ===== CONTRÔLES (Gauche) =====
        
        # Bouton principal d'écoute
        self.listen_btn = ttk.Button(
            left_panel,
            text="▶ Start listening",
            command=self.toggle_listening,
            width=20
        )
        self.listen_btn.pack(pady=(0, 10))
        
        # Bouton de calibration
        ttk.Button(
            left_panel,
            text="audio calibration",
            command=self.calibrate_mic,
            width=20
        ).pack(pady=5)
        
        # Bouton test audio
        ttk.Button(
            left_panel,
            text="sound test",
            command=self.test_audio,
            width=20
        ).pack(pady=5)
        
        # Séparateur
        ttk.Separator(left_panel, orient="horizontal").pack(fill="x", pady=20)
        
        # Niveau audio visuel
        audio_frame = tk.Frame(left_panel, bg=self.bg_color)
        audio_frame.pack()
        
        tk.Label(
            audio_frame,
            text="Niveau audio:",
            font=("Segoe UI", 10),
            fg=self.fg_color,
            bg=self.bg_color
        ).pack(anchor="w")
        
        self.audio_level = ttk.Progressbar(
            audio_frame,
            length=200,
            mode='determinate'
        )
        self.audio_level.pack(pady=(5, 0))
        
        # Indicateur d'activité vocale (VU meter)
        self.vu_meter = tk.Canvas(
            left_panel,
            width=200,
            height=30,
            bg="#1a1a1a",
            highlightthickness=0
        )
        self.vu_meter.pack(pady=20)
        self.vu_bar = self.vu_meter.create_rectangle(
            0, 0, 0, 30,
            fill=self.accent_color,
            outline=""
        )
        
        # Indicateur d'activité (LED)
        self.activity_led = tk.Label(
            left_panel,
            text="●",
            font=("Arial", 24),
            fg="red",
            bg=self.bg_color
        )
        self.activity_led.pack(pady=10)
        
        # ===== LOGS ET COMMANDES (Droite) =====
        
        # Affichage des commandes reconnues
        log_frame = tk.LabelFrame(
            right_panel,
            text="📝 Events log",
            font=("Segoe UI", 11, "bold"),
            fg=self.fg_color,
            bg=self.bg_color,
            relief="flat"
        )
        log_frame.pack(fill="both", expand=True)
        
        # Zone de texte avec défilement
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=15,
            font=("Consolas", 10),
            bg="#1a1a1a",
            fg=self.fg_color,
            insertbackground=self.fg_color,
            wrap="word"
        )
        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Dernière commande reconnue
        last_cmd_frame = tk.Frame(right_panel, bg=self.bg_color)
        last_cmd_frame.pack(fill="x", pady=(10, 0))
        
        tk.Label(
            last_cmd_frame,
            text="Dernière commande:",
            font=("Segoe UI", 10),
            fg=self.fg_color,
            bg=self.bg_color
        ).pack(side="left")
        
        self.last_command_var = tk.StringVar(value="Aucune")
        self.last_command_label = tk.Label(
            last_cmd_frame,
            textvariable=self.last_command_var,
            font=("Segoe UI", 10, "bold"),
            fg=self.accent_color,
            bg=self.bg_color
        )
        self.last_command_label.pack(side="left", padx=(10, 0))
        
        # ===== STATISTIQUES =====
        stats_frame = tk.Frame(self.root, bg=self.bg_color)
        stats_frame.pack(fill="x", padx=20, pady=(10, 20))
        
        # Commandes aujourd'hui
        self.commands_today_var = tk.StringVar(value="0")
        self.create_stat_widget(
            stats_frame, "Commandes", 
            self.commands_today_var, "📊"
        )
        
        # Taux de réussite
        self.success_rate_var = tk.StringVar(value="100%")
        self.create_stat_widget(
            stats_frame, "Succès", 
            self.success_rate_var, "✅"
        )
        
        # Temps d'activité
        self.uptime_var = tk.StringVar(value="00:00:00")
        self.create_stat_widget(
            stats_frame, "Activité", 
            self.uptime_var, "🕒"
        )
        
        # Dernière activité
        self.last_activity_var = tk.StringVar(value="--:--:--")
        self.create_stat_widget(
            stats_frame, "Dernière", 
            self.last_activity_var, "⏱️"
        )
        
    def create_stat_widget(self, parent, label, variable, icon):
        """Crée un widget de statistique"""
        frame = tk.Frame(parent, bg=self.bg_color)
        frame.pack(side="left", expand=True, padx=5)
        
        # Icône
        icon_label = tk.Label(
            frame,
            text=icon,
            font=("Segoe UI", 14),
            fg=self.fg_color,
            bg=self.bg_color
        )
        icon_label.pack()
        
        # Label descriptif
        tk.Label(
            frame,
            text=label,
            font=("Segoe UI", 9),
            fg="#aaaaaa",
            bg=self.bg_color
        ).pack()
        
        # Valeur
        value_label = tk.Label(
            frame,
            textvariable=variable,
            font=("Segoe UI", 16, "bold"),
            fg=self.accent_color,
            bg=self.bg_color
        )
        value_label.pack()
    
    def connect_callbacks(self):
        """Connecte les callbacks entre l'interface et le reconnaisseur"""
        self.recognizer.on_command_detected = self.on_command_detected
        self.recognizer.on_audio_playing = self.on_audio_playing
        self.recognizer.on_error = self.on_error
        self.recognizer.on_listening_start = self.on_listening_start
        self.recognizer.on_listening_stop = self.on_listening_stop
        
    def toggle_listening(self):
        """Activate/Désactivate listening"""
        if not self.recognizer.is_listening:
            self.start_listening()
        else:
            self.stop_listening()
    
    def start_listening(self):
        """Démarre l'écoute"""
        self.recognizer.is_listening = True
        self.status_var.set("🟢 listening...")
        self.listen_btn.configure(text="⏸ stop listening")
        self.log_message("Système", "Listening activated")
        
        # Démarrer le thread d'écoute
        self.listen_thread = threading.Thread(
            target=self.recognizer.ecouter_et_repondre,
            daemon=True
        )
        self.listen_thread.start()
    
    def stop_listening(self):
        """Stop listening"""
        self.recognizer.is_listening = False
        self.status_var.set("🔴 stopped")
        self.listen_btn.configure(text="▶ start listening")
        self.log_message("Système", "Listening desactivated")
    
    def calibrate_mic(self):
        """Calibre le microphone"""
        self.log_message("Système", "audio calibration ...")
        threading.Thread(
            target=self.recognizer.calibrer_micro,
            daemon=True
        ).start()
    
    def test_audio(self):
        """Teste le système audio"""
        import pygame
        pygame.mixer.init()
        try:
            # Jouer un son de test si disponible
            test_sound = "sounds/lovecraft.mp3"
            if os.path.exists(test_sound):
                self.log_message("Test", "Lecture du son de test...")
                pygame.mixer.music.load(test_sound)
                pygame.mixer.music.play()
            else:
                self.log_message("Test", "Fichier de test non trouvé", is_error=True)
        except Exception as e:
            self.log_message("Erreur", f"Test audio échoué: {str(e)}", is_error=True)
    
    def on_command_detected(self, command_text, audio_file=None, action_info=None):
        """Callback quand une commande est détectée"""
        self.command_count += 1
        self.success_count += 1
        
        # Mettre à jour l'interface via la queue
        self.message_queue.put((
            "command",
            command_text,
            audio_file,
            action_info
        ))
    
    def on_audio_playing(self, audio_file):
        """Callback quand un audio est joué"""
        self.message_queue.put(("audio_play", audio_file))
    
    def on_error(self, error_message):
        """Callback en cas d'erreur"""
        self.message_queue.put(("error", error_message))
    
    def on_listening_start(self):
        """Callback when listening starts"""
        self.message_queue.put(("listening_start", None))
    
    def on_listening_stop(self):
        """Callback when listening stops"""
        self.message_queue.put(("listening_stop", None))
    
    def log_message(self, source, message, is_error=False):
        """Ajoute un message au journal"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {source}: {message}"
        
        # Ajouter au widget de texte
        self.log_text.insert(tk.END, formatted_message + "\n")
        self.log_text.see(tk.END)  # Défile vers le bas
        
        # Appliquer la couleur selon le type de message
        if is_error:
            self.log_text.tag_add("error", "end-2c", "end-1c")
        elif source == "Commande":
            self.log_text.tag_add("command", "end-2c", "end-1c")
        elif source == "Système":
            self.log_text.tag_add("system", "end-2c", "end-1c")
        
        # Mettre à jour la dernière activité
        self.last_activity_var.set(timestamp)
    
    def update_audio_level(self):
        """Met à jour la barre de niveau audio (simulation)"""
        if self.recognizer.is_listening:
            # Simuler des variations de niveau audio
            level = random.uniform(0.1, 0.8)
            self.audio_level['value'] = min(level * 100, 100)
            
            # Mettre à jour le VU meter
            bar_width = min(int(level * 200), 200)
            self.vu_meter.coords(self.vu_bar, 0, 0, bar_width, 30)
            
            # Changer la couleur selon le niveau
            if level > 0.7:
                self.vu_meter.itemconfig(self.vu_bar, fill=self.error_color)
                self.activity_led.config(fg=self.error_color)
            elif level > 0.4:
                self.vu_meter.itemconfig(self.vu_bar, fill=self.success_color)
                self.activity_led.config(fg=self.success_color)
            else:
                self.vu_meter.itemconfig(self.vu_bar, fill=self.accent_color)
                self.activity_led.config(fg=self.accent_color)
        else:
            self.audio_level['value'] = 0
            self.vu_meter.coords(self.vu_bar, 0, 0, 0, 30)
            self.activity_led.config(fg="gray")
        
        # Planifier la prochaine mise à jour
        self.root.after(200, self.update_audio_level)
    
    def update_stats(self):
        """Met à jour les statistiques périodiquement"""
        # Mettre à jour le temps d'activité
        uptime = datetime.now() - self.start_time
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.uptime_var.set(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        
        # Mettre à jour le compteur de commandes
        self.commands_today_var.set(str(self.command_count))
        
        # Mettre à jour le taux de réussite
        if self.command_count > 0:
            success_rate = (self.success_count / self.command_count) * 100
            self.success_rate_var.set(f"{success_rate:.1f}%")
            # Changer la couleur selon le taux
            if success_rate > 90:
                self.success_rate_var.set(f"✓ {success_rate:.1f}%")
            elif success_rate > 70:
                self.success_rate_var.set(f"⚠ {success_rate:.1f}%")
            else:
                self.success_rate_var.set(f"✗ {success_rate:.1f}%")
        
        # Planifier la prochaine mise à jour
        self.root.after(1000, self.update_stats)
    
    def check_queue(self):
        """Vérifie les messages dans la queue (appelé périodiquement)"""
        try:
            while True:
                msg_type, *data = self.message_queue.get_nowait()
                
                if msg_type == "command":
                    command_text, audio_file, action_info = data
                    self.last_command_var.set(f'"{command_text}"')
                    
                    # Afficher le message approprié
                    if action_info:
                        action_type = action_info.get('type', 'action')
                        if action_type == 'fichier':
                            self.log_message("Commande", f"Ouverture fichier: {command_text}")
                        else:
                            self.log_message("Commande", f"Lancement application: {command_text}")
                    elif audio_file:
                        self.log_message("Commande", f"Audio: {command_text}")
                    else:
                        self.log_message("Commande", f"{command_text}")
                
                elif msg_type == "audio_play":
                    audio_file = data[0]
                    filename = os.path.basename(audio_file)
                    self.log_message("Audio", f"Lecture: {filename}")
                
                elif msg_type == "error":
                    error_msg = data[0]
                    self.log_message("Erreur", error_msg, is_error=True)
                
                elif msg_type == "listening_start":
                    self.status_var.set("🟢 Listening...")
                    self.activity_led.config(fg=self.success_color)
                
                elif msg_type == "listening_stop":
                    self.status_var.set("🔴 Stopped")
                    self.activity_led.config(fg="gray")
                
                self.message_queue.task_done()
                
        except queue.Empty:
            pass
        
        # Planifier la prochaine vérification
        self.root.after(100, self.check_queue)
    
    def run(self):
        """Lance l'interface graphique"""
        # Configurer les tags de couleur pour le log
        self.log_text.tag_config("error", foreground=self.error_color)
        self.log_text.tag_config("command", foreground=self.success_color)
        self.log_text.tag_config("system", foreground=self.accent_color)
        
        # Démarrer les mises à jour périodiques
        self.update_audio_level()
        
        # Configurer la fermeture propre
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Centrer la fenêtre
        self.root.eval('tk::PlaceWindow . center')
        
        # Démarrer la boucle principale
        self.root.mainloop()
    
    def on_closing(self):
        """Gère la fermeture de la fenêtre"""
        # Arrêter l'écoute si active
        if self.recognizer.is_listening:
            self.stop_listening()
            # Attendre un peu pour l'arrêt propre
            self.root.after(500, self.root.destroy)
        else:
            self.root.destroy()


if __name__ == "__main__":
    # Importer la classe AudioCommandRecognizer depuis ear.py
    try:
        # Assurez-vous que ear.py est dans le même dossier
        import os
        script_dir = os.path.dirname(os.path.abspath(__file__))
        os.chdir(script_dir)
        
        from ear import AudioCommandRecognizer
        
        print("=== Lancement de l'interface graphique EAR ===")
        print("Initialisation...")
        
        # Démarrer l'application
        app = AudioCommandRecognizer()
        
        # Démarrer l'interface graphique
        gui = VoiceAssistantGUI(app)
        gui.run()
        
    except ImportError as e:
        print(f"Erreur d'importation: {e}")
        print("Assurez-vous que ear.py est dans le même dossier.")
        input("Appuyez sur Entrée pour quitter...")
    except Exception as e:
        print(f"Erreur lors du lancement: {e}")
        import traceback
        traceback.print_exc()
        input("Appuyez sur Entrée pour quitter...")