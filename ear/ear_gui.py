import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import queue
from datetime import datetime
import os
import random
import pygame

class VoiceAssistantGUI:
    def __init__(self, voice_recognizer):
        self.recognizer = voice_recognizer
        self.root = tk.Tk()
        self.root.title("EAR - Voice Assistant 🔊")
        self.root.geometry("800x600")
        
        # Configuration of the queue for thread-safe communication
        self.message_queue = queue.Queue()
        
        # Variables for statistics
        self.command_count = 0
        self.success_count = 0
        self.start_time = datetime.now()
        
        # Modern style
        self.setup_styles()
        
        # Create interface
        self.create_widgets()
        
        # Connect callbacks
        self.connect_callbacks()
        
        # Start checking the queue
        self.check_queue()
        
        # Start listening automatically (after a short delay)
        self.root.after(1000, self.start_listening)
        
    def setup_styles(self):
        """Configure styles for a modern appearance"""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Colors
        self.bg_color = "#2b2b2b"
        self.fg_color = "#ffffff"
        self.accent_color = "#4a9eff"
        self.success_color = "#4CAF50"
        self.error_color = "#f44336"
        self.warning_color = "#ff9800"
        self.word_color = "#FFD700"  # Couleur or pour les mots détectés
        
        # Main window configuration
        self.root.configure(bg=self.bg_color)
        
    def create_widgets(self):
        """Creates all interface widgets"""
        
        # ===== HEADER =====
        header_frame = tk.Frame(self.root, bg=self.bg_color)
        header_frame.pack(fill="x", padx=20, pady=(20, 10))
        
        # Logo/Title
        title_label = tk.Label(
            header_frame,
            text="EAR - Enhanced Audio Recognition",
            font=("Segoe UI", 24, "bold"),
            fg=self.accent_color,
            bg=self.bg_color
        )
        title_label.pack(side="left")
        
        # Status indicator
        self.status_var = tk.StringVar(value="🔴 stopped")
        self.status_label = tk.Label(
            header_frame,
            textvariable=self.status_var,
            font=("Segoe UI", 12),
            fg=self.fg_color,
            bg=self.bg_color
        )
        self.status_label.pack(side="right")
        
        # ===== MAIN SECTION =====
        main_frame = tk.Frame(self.root, bg=self.bg_color)
        main_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        # Left panel - Controls
        left_panel = tk.Frame(main_frame, bg=self.bg_color)
        left_panel.pack(side="left", fill="y", padx=(0, 10))
        
        # Right panel - Logs
        right_panel = tk.Frame(main_frame, bg=self.bg_color)
        right_panel.pack(side="right", fill="both", expand=True)
        
        # ===== CONTROLS (Left) =====
        
        # Main listening button
        self.listen_btn = ttk.Button(
            left_panel,
            text="▶ start listening",
            command=self.toggle_listening,
            width=20
        )
        self.listen_btn.pack(pady=(0, 10))
        
        # Calibration button
        ttk.Button(
            left_panel,
            text="audio calibration",
            command=self.calibrate_mic,
            width=20
        ).pack(pady=5)
        
        # Sound test button
        ttk.Button(
            left_panel,
            text="sound test",
            command=self.test_audio,
            width=20
        ).pack(pady=5)
        
        # Clear log button
        ttk.Button(
            left_panel,
            text="clear log",
            command=self.clear_log,
            width=20
        ).pack(pady=5)
        
        # Separator
        ttk.Separator(left_panel, orient="horizontal").pack(fill="x", pady=20)
        
        # Audio level
        audio_frame = tk.Frame(left_panel, bg=self.bg_color)
        audio_frame.pack(fill="x")
        
        tk.Label(
            audio_frame,
            text="audio level:",
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
        
        # Activity indicator (simple colored circle)
        self.activity_led = tk.Label(
            left_panel,
            text="●",
            font=("Arial", 24),
            fg="gray",
            bg=self.bg_color
        )
        self.activity_led.pack(pady=10)
        
        # Word count
        self.word_count_var = tk.StringVar(value="Words detected: 0")
        self.word_count_label = tk.Label(
            left_panel,
            textvariable=self.word_count_var,
            font=("Segoe UI", 10),
            fg=self.fg_color,
            bg=self.bg_color
        )
        self.word_count_label.pack(pady=5)
        
        # ===== LOGS AND COMMANDS (Right) =====
        
        # Events log display
        log_frame = tk.LabelFrame(
            right_panel,
            text="📝 Events log",
            font=("Segoe UI", 11, "bold"),
            fg=self.fg_color,
            bg=self.bg_color,
            relief="flat"
        )
        log_frame.pack(fill="both", expand=True)
        
        # Scrolled text area
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
        
        # Last recognized command
        last_cmd_frame = tk.Frame(right_panel, bg=self.bg_color)
        last_cmd_frame.pack(fill="x", pady=(10, 0))
        
        tk.Label(
            last_cmd_frame,
            text="last command:",
            font=("Segoe UI", 10),
            fg=self.fg_color,
            bg=self.bg_color
        ).pack(side="left")
        
        self.last_command_var = tk.StringVar(value="None")
        self.last_command_label = tk.Label(
            last_cmd_frame,
            textvariable=self.last_command_var,
            font=("Segoe UI", 10, "bold"),
            fg=self.accent_color,
            bg=self.bg_color
        )
        self.last_command_label.pack(side="left", padx=(10, 0))
    
    def connect_callbacks(self):
        """Connects callbacks between interface and recognizer"""
        self.recognizer.on_command_detected = self.on_command_detected
        self.recognizer.on_audio_playing = self.on_audio_playing
        self.recognizer.on_error = self.on_error
        self.recognizer.on_listening_start = self.on_listening_start
        self.recognizer.on_listening_stop = self.on_listening_stop
        self.recognizer.on_word_heard = self.on_word_heard  # Nouveau callback
        
    def clear_log(self):
        """Clear the log text area"""
        self.log_text.delete(1.0, tk.END)
        self.log_message("System", "Log cleared")
        
    def toggle_listening(self):
        """Toggles listening on/off"""
        if not self.recognizer.is_listening:
            self.start_listening()
        else:
            self.stop_listening()
    
    def start_listening(self):
        """Starts listening"""
        self.recognizer.is_listening = True
        self.status_var.set("🟢 listening...")
        self.listen_btn.configure(text="⏸ stop listening")
        self.log_message("System", "Listening activated")
        
        # Start listening thread
        self.listen_thread = threading.Thread(
            target=self.recognizer.ecouter_et_repondre,
            daemon=True
        )
        self.listen_thread.start()
    
    def stop_listening(self):
        """Stops listening"""
        self.recognizer.is_listening = False
        self.status_var.set("🔴 stopped")
        self.listen_btn.configure(text="▶ start listening")
        self.log_message("System", "Listening deactivated")
    
    def calibrate_mic(self):
        """Calibrates the microphone"""
        self.log_message("System", "Calibrating microphone...")
        threading.Thread(
            target=self.recognizer.calibrer_micro,
            daemon=True
        ).start()
    
    def test_audio(self):
        """Tests the audio system"""
        try:
            # Play a test sound if available
            test_sound = "sounds/thx.mp3"
            if os.path.exists(test_sound):
                self.log_message("Test", "Playing test sound...")
                pygame.mixer.music.load(test_sound)
                pygame.mixer.music.play()
            else:
                self.log_message("Test", "Test sound file not found")
        except Exception as e:
            self.log_message("Error", f"Audio test failed: {str(e)}", is_error=True)
    
    def on_word_heard(self, word_text):
        """Callback when a word is heard (not necessarily a command)"""
        self.message_queue.put(("word", word_text))
    
    def on_command_detected(self, command_text, audio_file=None, action_info=None):
        """Callback when a command is detected"""
        self.command_count += 1
        self.success_count += 1
        
        # Update interface via queue
        self.message_queue.put((
            "command",
            command_text,
            audio_file,
            action_info
        ))
    
    def on_audio_playing(self, audio_file):
        """Callback when audio is playing"""
        self.message_queue.put(("audio_play", audio_file))
    
    def on_error(self, error_message):
        """Callback for errors"""
        self.message_queue.put(("error", error_message))
    
    def on_listening_start(self):
        """Callback when listening starts"""
        self.message_queue.put(("listening_start", None))
    
    def on_listening_stop(self):
        """Callback when listening stops"""
        self.message_queue.put(("listening_stop", None))
    
    def log_message(self, source, message, is_error=False):
        """Adds a message to the log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {source}: {message}\n"
        
        self.log_text.insert(tk.END, formatted_message)
        self.log_text.see(tk.END)
        
        # Apply color based on message type
        last_line_start = self.log_text.index(f"end-2c linestart")
        last_line_end = "end-1c"
        
        if is_error:
            self.log_text.tag_add("error", last_line_start, last_line_end)
        elif source == "Command":
            self.log_text.tag_add("command", last_line_start, last_line_end)
        elif source == "System":
            self.log_text.tag_add("system", last_line_start, last_line_end)
        elif source == "Word":
            self.log_text.tag_add("word", last_line_start, last_line_end)
    
    def update_audio_level(self):
        """Updates the audio level bar (simulation)"""
        if self.recognizer.is_listening:
            # Simulate audio level - in reality, you'd get this from the microphone
            level = random.uniform(0.1, 0.8)
            self.audio_level['value'] = min(level * 100, 100)
            
            # Update activity LED color based on level
            if level > 0.7:
                self.activity_led.config(fg=self.error_color)
            elif level > 0.4:
                self.activity_led.config(fg=self.success_color)
            else:
                self.activity_led.config(fg=self.accent_color)
        else:
            self.audio_level['value'] = 0
            self.activity_led.config(fg="gray")
        
        self.root.after(200, self.update_audio_level)
    
    def check_queue(self):
        """Checks messages in the queue (called periodically)"""
        word_count = 0
        
        try:
            while True:
                msg_type, *data = self.message_queue.get_nowait()
                
                if msg_type == "word":
                    word_text = data[0]
                    word_count += 1
                    self.word_count_var.set(f"Words detected: {word_count}")
                    self.log_message("Word", word_text)
                
                elif msg_type == "command":
                    command_text, audio_file, action_info = data
                    self.last_command_var.set(f'"{command_text}"')
                    
                    if action_info:
                        action_type = action_info.get('type', 'action')
                        if action_type == 'fichier':
                            self.log_message("Command", f"📂 Opening file: {command_text}")
                        else:
                            self.log_message("Command", f"🚀 Launching application: {command_text}")
                    elif audio_file:
                        self.log_message("Command", f"🔊 Audio: {command_text}")
                    else:
                        self.log_message("Command", f"💬 {command_text}")
                
                elif msg_type == "audio_play":
                    audio_file = data[0]
                    filename = os.path.basename(audio_file)
                    self.log_message("Audio", f"▶️ Playing: {filename}")
                
                elif msg_type == "error":
                    error_msg = data[0]
                    self.log_message("Error", error_msg, is_error=True)
                
                elif msg_type == "listening_start":
                    self.status_var.set("🟢 listening...")
                    self.activity_led.config(fg=self.success_color)
                    self.log_message("System", "Started listening")
                
                elif msg_type == "listening_stop":
                    self.status_var.set("🔴 stopped")
                    self.activity_led.config(fg="gray")
                    self.log_message("System", "Stopped listening")
                
                self.message_queue.task_done()
                
        except queue.Empty:
            pass
        
        self.root.after(100, self.check_queue)
    
    def run(self):
        """Launches the graphical interface"""
        # Configure color tags for log
        self.log_text.tag_config("error", foreground=self.error_color)
        self.log_text.tag_config("command", foreground=self.success_color)
        self.log_text.tag_config("system", foreground=self.accent_color)
        self.log_text.tag_config("word", foreground=self.word_color)
        
        # Start periodic updates
        self.update_audio_level()
        
        # Configure clean closing
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Center the window
        self.root.eval('tk::PlaceWindow . center')
        
        # Start main loop
        self.root.mainloop()
    
    def on_closing(self):
        """Handles window closing"""
        if self.recognizer.is_listening:
            self.stop_listening()
            self.root.after(500, self.root.destroy)
        else:
            self.root.destroy()