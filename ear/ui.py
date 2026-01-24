import tkinter as tk
from tkinter import ttk, scrolledtext, font
import threading
import queue
from datetime import datetime
import os

class VoiceAssistantGUI:
    def __init__(self, voice_recognizer):
        self.recognizer = voice_recognizer
        self.root = tk.Tk()
        self.root.title("Assistant Vocal - EAR 🔊")
        self.root.geometry("800x600")
        
        # Configuration de la file d'attente pour la communication thread-safe
        self.message_queue = queue.Queue()
        
        # Style moderne
        self.setup_styles()
        
        # Création de l'interface
        self.create_widgets()
        
        # Démarrer la vérification des messages
        self.check_queue()
        
        # Initialiser l'assistant vocal
        self.init_voice_assistant()
    
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
            text="🎤 EAR - Assistant Vocal",
            font=("Segoe UI", 24, "bold"),
            fg=self.accent_color,
            bg=self.bg_color
        )
        title_label.pack(side="left")
        
        # Indicateur d'état
        self.status_var = tk.StringVar(value="🔴 Arrêté")
        status_label = tk.Label(
            header_frame,
            textvariable=self.status_var,
            font=("Segoe UI", 12),
            fg=self.fg_color,
            bg=self.bg_color
        )
        status_label.pack(side="right")
        
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
            text="▶ Démarrer l'écoute",
            command=self.toggle_listening,
            width=20
        )
        self.listen_btn.pack(pady=(0, 10))
        
        # Bouton de calibration
        ttk.Button(
            left_panel,
            text="🎤 Calibrer microphone",
            command=self.calibrate_mic,
            width=20
        ).pack(pady=5)
        
        # Bouton test audio
        ttk.Button(
            left_panel,
            text="🔊 Tester le son",
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
        
        # Indicateur d'activité vocale
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
        
        # ===== LOGS ET COMMANDES (Droite) =====
        
        # Affichage des commandes reconnues
        log_frame = tk.LabelFrame(
            right_panel,
            text="📝 Journal d'activité",
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
            stats_frame, "Commandes aujourd'hui", 
            self.commands_today_var, "📊"
        )
        
        # Taux de réussite
        self.success_rate_var = tk.StringVar(value="100%")
        self.create_stat_widget(
            stats_frame, "Taux de réussite", 
            self.success_rate_var, "✅"
        )
        
        # Dernière activité
        self.last_activity_var = tk.StringVar(value="--:--:--")
        self.create_stat_widget(
            stats_frame, "Dernière activité", 
            self.last_activity_var, "🕒"
        )
        
        # Initialiser les compteurs
        self.command_count = 0
        self.success_count = 0
        
    def create_stat_widget(self, parent, label, variable, icon):
        """Crée un widget de statistique"""
        frame = tk.Frame(parent, bg=self.bg_color)
        frame.pack(side="left", expand=True)
        
        tk.Label(
            frame,
            text=icon,
            font=("Segoe UI", 14),
            fg=self.fg_color,
            bg=self.bg_color
        ).pack()
        
        tk.Label(
            frame,
            text=label,
            font=("Segoe UI", 9),
            fg="#aaaaaa",
            bg=self.bg_color
        ).pack()
        
        tk.Label(
            frame,
            textvariable=variable,
            font=("Segoe UI", 16, "bold"),
            fg=self.accent_color,
            bg=self.bg_color
        ).pack()
    
    def init_voice_assistant(self):
        """Initialise l'assistant vocal avec callbacks"""
        # Ajouter des callbacks à votre classe AudioCommandRecognizer existante
        self.recognizer.on_command_detected = self.on_command_detected
        self.recognizer.on_audio_playing = self.on_audio_playing
        self.recognizer.on_error = self.on_error
        self.recognizer.on_listening_start = self.on_listening_start
        self.recognizer.on_listening_stop = self.on_listening_stop
        
    def toggle_listening(self):
        """Active/Désactive l'écoute"""
        if not self.recognizer.is_listening:
            self.start_listening()
        else:
            self.stop_listening()
    
    def start_listening(self):
        """Démarre l'écoute"""
        self.recognizer.is_listening = True
        self.status_var.set("🟢 En écoute...")
        self.listen_btn.configure(text="⏸ Arrêter l'écoute")
        self.log_message("Système", "Écoute activée")
        
        # Démarrer le thread d'écoute
        self.listen_thread = threading.Thread(
            target=self.recognizer.ecouter_et_repondre,
            daemon=True
        )
        self.listen_thread.start()
    
    def stop_listening(self):
        """Arrête l'écoute"""
        self.recognizer.is_listening = False
        self.status_var.set("🔴 Arrêté")
        self.listen_btn.configure(text="▶ Démarrer l'écoute")
        self.log_message("Système", "Écoute désactivée")
    
    def calibrate_mic(self):
        """Calibre le microphone"""
        self.log_message("Système", "Calibration du microphone en cours...")
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
            test_sound = "sounds/coucou.mp3"
            if os.path.exists(test_sound):
                pygame.mixer.music.load(test_sound)
                pygame.mixer.music.play()
                self.log_message("Test", "Son de test joué")
            else:
                self.log_message("Test", "Fichier de test non trouvé")
        except Exception as e:
            self.log_message("Erreur", f"Test audio échoué: {str(e)}")
    
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
        """Callback quand l'écoute commence"""
        self.message_queue.put(("listening_start", None))
    
    def on_listening_stop(self):
        """Callback quand l'écoute s'arrête"""
        self.message_queue.put(("listening_stop", None))
    
    def log_message(self, source, message):
        """Ajoute un message au journal"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {source}: {message}\n"
        
        self.log_text.insert(tk.END, formatted_message)
        self.log_text.see(tk.END)  # Défile vers le bas
        
        # Mettre à jour la dernière activité
        self.last_activity_var.set(timestamp)
        
        # Colorisation selon la source
        if source == "Erreur":
            self.log_text.tag_add("error", "end-2l", "end-1l")
        elif source == "Commande":
            self.log_text.tag_add("command", "end-2l", "end-1l")
    
    def update_audio_level(self, level):
        """Met à jour la barre de niveau audio"""
        self.audio_level['value'] = min(level * 100, 100)
        
        # Mettre à jour le VU meter
        bar_width = min(int(level * 200), 200)
        self.vu_meter.coords(self.vu_bar, 0, 0, bar_width, 30)
        
        # Changer la couleur selon le niveau
        if level > 0.8:
            self.vu_meter.itemconfig(self.vu_bar, fill=self.error_color)
        elif level > 0.5:
            self.vu_meter.itemconfig(self.vu_bar, fill=self.success_color)
        else:
            self.vu_meter.itemconfig(self.vu_bar, fill=self.accent_color)
    
    def check_queue(self):
        """Vérifie les messages dans la queue (appelé périodiquement)"""
        try:
            while True:
                msg_type, *data = self.message_queue.get_nowait()
                
                if msg_type == "command":
                    command_text, audio_file, action_info = data
                    self.last_command_var.set(f'"{command_text}"')
                    self.commands_today_var.set(str(self.command_count))
                    
                    success_rate = (self.success_count / self.command_count * 100) if self.command_count > 0 else 100
                    self.success_rate_var.set(f"{success_rate:.1f}%")
                    
                    self.log_message("Commande", command_text)
                    
                    if action_info:
                        self.log_message("Action", f"Exécution: {action_info.get('type', 'inconnu')}")
                
                elif msg_type == "audio_play":
                    audio_file = data[0]
                    self.log_message("Audio", f"Lecture: {os.path.basename(audio_file)}")
                
                elif msg_type == "error":
                    error_msg = data[0]
                    self.log_message("Erreur", error_msg)
                
                elif msg_type == "listening_start":
                    self.status_var.set("🟢 En écoute...")
                
                elif msg_type == "listening_stop":
                    self.status_var.set("🔴 Arrêté")
                
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
        
        # Simuler une mise à jour périodique du niveau audio
        self.simulate_audio_level()
        
        # Démarrer la boucle principale
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()
    
    def simulate_audio_level(self):
        """Simule les variations de niveau audio (pour la démo)"""
        import random
        if self.recognizer.is_listening:
            level = random.uniform(0.1, 0.9)
            self.update_audio_level(level)
        
        # Planifier la prochaine mise à jour
        self.root.after(200, self.simulate_audio_level)
    
    def on_closing(self):
        """Gère la fermeture de la fenêtre"""
        self.stop_listening()
        self.root.destroy()