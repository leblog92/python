"""
EAR — Enhanced Audio Recognition
Core engine: speech recognition + command dispatch.

New in this version
───────────────────
• All tunable parameters read from config.ini
• System actions loaded from actions.ini
• Vosk offline backend (set backend=vosk in config.ini)
• measure_threshold() to find the right energy_threshold for your room
• Log-rotation cap read from config.ini (log_max_lines)
"""

import configparser
import os
import platform
import subprocess
import threading
import time
import logging
from pathlib import Path

import pygame

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("EAR")


# ──────────────────────────────────────────────
# File paths
# ──────────────────────────────────────────────
CONFIG_FILE   = "config.ini"
KEYWORDS_FILE = "keywords.txt"
ACTIONS_FILE  = "actions.ini"
SOUNDS_DIR    = "sounds"

_DEFAULTS = {
    "recognition": {
        "backend":           "google",
        "language":          "fr-FR",
        "vosk_model_path":   "models/vosk-model-small-fr-0.22",
        "pause_threshold":   "0.5",
        "phrase_time_limit": "3",
        "listen_timeout":    "0.5",
    },
    "audio": {
        "energy_threshold": "300",
        "dynamic_energy":   "false",
    },
    "commands": {
        "cooldown_sec":  "2.0",
        "log_max_lines": "500",
    },
    "network": {
        "max_retry":       "5",
        "retry_delay_sec": "3",
    },
}


# ──────────────────────────────────────────────
# Config loader
# ──────────────────────────────────────────────
def load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    for section, values in _DEFAULTS.items():
        cfg[section] = values
    if os.path.exists(CONFIG_FILE):
        cfg.read(CONFIG_FILE, encoding="utf-8")
        logger.info(f"Config loaded from {CONFIG_FILE}")
    else:
        logger.warning(f"{CONFIG_FILE} not found — using built-in defaults")
    return cfg


# ──────────────────────────────────────────────
# Keywords loader
# ──────────────────────────────────────────────
def load_keywords(filepath: str = KEYWORDS_FILE) -> dict:
    """
    Load audio commands from keywords.txt.
    Format:  trigger phrase = sounds/file.mp3
    Sorted by key length descending (longest match wins).
    """
    commands: dict[str, str] = {}
    if not os.path.exists(filepath):
        logger.warning(f"Keywords file not found: {filepath}")
        return commands

    with open(filepath, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                logger.warning(f"keywords.txt line {lineno} skipped (no '='): {raw.rstrip()}")
                continue
            key, _, val = line.partition("=")
            key, val = key.strip().lower(), val.strip()
            if key and val:
                commands[key] = val

    sorted_cmds = dict(sorted(commands.items(), key=lambda x: len(x[0]), reverse=True))
    logger.info(f"{len(sorted_cmds)} audio commands loaded from {filepath}")
    return sorted_cmds


# ──────────────────────────────────────────────
# Actions loader
# ──────────────────────────────────────────────
def load_actions(filepath: str = ACTIONS_FILE) -> dict:
    """
    Load system actions from actions.ini.
    Each [section] is a trigger phrase.
    Sorted by key length descending.
    """
    actions: dict[str, dict] = {}
    if not os.path.exists(filepath):
        logger.warning(f"Actions file not found: {filepath} — system actions disabled")
        return actions

    cfg = configparser.ConfigParser()
    cfg.read(filepath, encoding="utf-8")

    for trigger in cfg.sections():
        section = cfg[trigger]
        kind = section.get("type", "").strip().lower()
        key  = trigger.strip().lower()

        if kind == "file":
            path = section.get("path", "").strip()
            if path:
                actions[key] = {"type": "file", "path": path, "action": "open_file"}
            else:
                logger.warning(f"actions.ini [{trigger}]: missing 'path'")
        elif kind == "app":
            actions[key] = {
                "type": "app",
                "action": "launch_app",
                "command": {
                    "windows": section.get("windows", "").strip(),
                    "linux":   section.get("linux",   "").strip(),
                    "darwin":  section.get("darwin",  "").strip(),
                },
            }
        else:
            logger.warning(f"actions.ini [{trigger}]: unknown type '{kind}'")

    sorted_actions = dict(sorted(actions.items(), key=lambda x: len(x[0]), reverse=True))
    logger.info(f"{len(sorted_actions)} system actions loaded from {filepath}")
    return sorted_actions


# ──────────────────────────────────────────────
# Vosk backend
# ──────────────────────────────────────────────
class VoskBackend:
    """Offline speech recognition via Vosk."""

    def __init__(self, model_path: str):
        try:
            from vosk import Model, KaldiRecognizer
            import sounddevice as sd
            import json
            self._json   = json
            self._sd     = sd
            self._KaldiR = KaldiRecognizer
            if not os.path.exists(model_path):
                raise FileNotFoundError(
                    f"Vosk model not found at '{model_path}'.\n"
                    "Download from https://alphacephei.com/vosk/models\n"
                    "and extract to that path."
                )
            self._model = Model(model_path)
            logger.info(f"Vosk model loaded: {model_path}")
        except ImportError:
            raise ImportError(
                "Vosk backend requires 'vosk' and 'sounddevice'.\n"
                "Run: pip install vosk sounddevice"
            )

    def listen_once(self, phrase_limit: float) -> str | None:
        samplerate = 16000
        rec = self._KaldiR(self._model, samplerate)
        max_blocks = int(phrase_limit * samplerate / 512)

        with self._sd.InputStream(samplerate=samplerate, channels=1,
                                   dtype="int16", blocksize=512) as stream:
            for _ in range(max_blocks):
                data, _ = stream.read(512)
                if rec.AcceptWaveform(data.tobytes()):
                    result = self._json.loads(rec.Result())
                    text = result.get("text", "").strip()
                    if text:
                        return text

        return self._json.loads(rec.FinalResult()).get("text", "").strip() or None


# ──────────────────────────────────────────────
# Main recognizer
# ──────────────────────────────────────────────
class AudioCommandRecognizer:

    def __init__(self):
        self.cfg = load_config()
        self._apply_config()

        pygame.mixer.init()

        self.commands       = load_keywords()
        self.system_actions = load_actions()
        self._last_triggered: dict[str, float] = {}

        Path(SOUNDS_DIR).mkdir(exist_ok=True)
        self.is_listening  = False
        self._listen_thread: threading.Thread | None = None

        # GUI callbacks
        self.on_command_detected = None
        self.on_audio_playing    = None
        self.on_error            = None
        self.on_listening_start  = None
        self.on_listening_stop   = None
        self.on_word_heard       = None

    def _apply_config(self):
        rec = self.cfg["recognition"]
        aud = self.cfg["audio"]
        cmd = self.cfg["commands"]
        net = self.cfg["network"]

        self.backend       = rec.get("backend", "google").lower()
        self.language      = rec.get("language", "fr-FR")
        self.pause_thresh  = float(rec.get("pause_threshold",   "0.5"))
        self.phrase_limit  = float(rec.get("phrase_time_limit", "3"))
        self.listen_timeout= float(rec.get("listen_timeout",    "0.5"))
        self.energy_thresh = int(aud.get("energy_threshold", "300"))
        self.dynamic_energy= aud.get("dynamic_energy", "false").lower() == "true"
        self.cooldown_sec  = float(cmd.get("cooldown_sec",  "2.0"))
        self.log_max_lines = int(cmd.get("log_max_lines", "500"))
        self.max_retry     = int(net.get("max_retry",       "5"))
        self.retry_delay   = int(net.get("retry_delay_sec", "3"))

        if self.backend == "vosk":
            model_path  = rec.get("vosk_model_path", "models/vosk-model-small-fr-0.22")
            self._vosk  = VoskBackend(model_path)
            self._sr    = None
            self._rec   = None
            self._mic   = None
        else:
            import speech_recognition as sr
            self._sr  = sr
            self._rec = sr.Recognizer()
            self._mic = sr.Microphone()
            self._rec.energy_threshold         = self.energy_thresh
            self._rec.dynamic_energy_threshold = self.dynamic_energy
            self._rec.pause_threshold          = self.pause_thresh
            self._vosk = None

    # ── Reload helpers ────────────────────────
    def reload_keywords(self):
        self.commands = load_keywords()
        self._notify_word(f"keywords.txt reloaded — {len(self.commands)} commands")

    def reload_actions(self):
        self.system_actions = load_actions()
        self._notify_word(f"actions.ini reloaded — {len(self.system_actions)} actions")

    def reload_config(self):
        self.cfg = load_config()
        self._apply_config()
        self._notify_word("config.ini reloaded.")

    # ── Notifications ─────────────────────────
    def _notify_word(self, msg: str):
        if self.on_word_heard:
            self.on_word_heard(msg)

    def _notify_error(self, msg: str):
        logger.error(msg)
        if self.on_error:
            self.on_error(msg)

    def _stop_and_wait(self):
        """Signal the listen loop to stop and block until the thread exits."""
        self.is_listening = False
        if self._listen_thread and self._listen_thread.is_alive():
            self._listen_thread.join(timeout=3)

    def _start_thread(self):
        """Spawn a new listen thread and store the reference."""
        self.is_listening    = True
        self._listen_thread  = threading.Thread(
            target=self.ecouter_et_repondre,
            daemon=True,
            name="EAR-listen",
        )
        self._listen_thread.start()

    # ── Cooldown ──────────────────────────────
    def _on_cooldown(self, trigger: str) -> bool:
        return (time.time() - self._last_triggered.get(trigger, 0)) < self.cooldown_sec

    def _mark(self, trigger: str):
        self._last_triggered[trigger] = time.time()

    # ── Calibration ───────────────────────────
    def calibrer_micro(self):
        """Adjust energy_threshold to current ambient noise.
        Stops the listen loop first so the mic is free."""
        if self.backend == "vosk":
            self._notify_word("Calibration not needed for Vosk backend.")
            return

        was_listening = self.is_listening
        self._stop_and_wait()

        try:
            self._notify_word("Calibrating audio… please stay quiet.")
            with self._mic as source:
                self._rec.adjust_for_ambient_noise(source, duration=2)
            self.energy_thresh = int(self._rec.energy_threshold)
            self._notify_word(f"Calibration complete. Threshold: {self.energy_thresh}")
        except Exception as e:
            self._notify_error(f"Calibration error: {e}")
        finally:
            if was_listening:
                self._start_thread()

    def measure_threshold(self) -> int | None:
        """
        Measure ambient noise for 3 s and report the suggested energy_threshold.
        Does not change the current value — copy it to config.ini manually.
        """
        if self.backend == "vosk":
            self._notify_word("Threshold measurement not available for Vosk backend.")
            return None

        was_listening = self.is_listening
        self._stop_and_wait()

        try:
            import speech_recognition as sr
            self._notify_word("Measuring ambient noise… stay quiet for 3 s.")
            r = sr.Recognizer()
            with self._mic as source:
                r.adjust_for_ambient_noise(source, duration=3)
            measured = int(r.energy_threshold)
            self._notify_word(
                f"Measured: {measured}  (current: {self.energy_thresh})  "
                f"— set energy_threshold = {measured} in config.ini to lock this in."
            )
            return measured
        except Exception as e:
            self._notify_error(f"Threshold measurement error: {e}")
            return None
        finally:
            if was_listening:
                self._start_thread()

    # ── Audio ─────────────────────────────────
    def jouer_audio(self, fichier: str):
        try:
            if os.path.exists(fichier):
                if self.on_audio_playing:
                    self.on_audio_playing(fichier)
                self._notify_word(f"Playing: {os.path.basename(fichier)}")
                pygame.mixer.music.load(fichier)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
            else:
                self._notify_error(f"Audio file not found: {fichier}")
        except Exception as e:
            self._notify_error(f"Audio playback error: {e}")

    # ── File / app launchers ──────────────────
    def ouvrir_fichier(self, chemin: str) -> bool:
        try:
            p = chemin if os.path.isabs(chemin) else os.path.abspath(chemin)
            if not os.path.exists(p):
                self._notify_error(f"File not found: {p}")
                return False
            system = platform.system().lower()
            if system == "windows":
                subprocess.Popen(f'start "" "{p}"', shell=True)
            elif system == "darwin":
                subprocess.Popen(["open", p])
            else:
                subprocess.Popen(["xdg-open", p])
            self._notify_word(f"File opened: {os.path.basename(p)}")
            return True
        except Exception as e:
            self._notify_error(f"Error opening file: {e}")
            return False

    def lancer_programme(self, commande: str) -> bool:
        try:
            subprocess.Popen(commande, shell=True)
            self._notify_word(f"App launched: {commande}")
            return True
        except Exception as e:
            self._notify_error(f"Error launching app: {e}")
            return False

    def executer_action_systeme(self, action_info: dict) -> bool:
        if action_info["action"] == "open_file" and action_info["type"] == "file":
            return self.ouvrir_fichier(action_info["path"])
        elif action_info["action"] == "launch_app" and action_info["type"] == "app":
            cmd = action_info["command"].get(platform.system().lower(), "")
            if cmd:
                return self.lancer_programme(cmd)
            self._notify_error(f"No command for platform: {platform.system()}")
        return False

    # ── Text matching ─────────────────────────
    def _match(self, texte: str) -> tuple:
        self._notify_word(f'Detected: "{texte}"')
        for trigger, info in self.system_actions.items():
            if trigger in texte:
                return trigger, None, info
        for trigger, audio in self.commands.items():
            if trigger in texte:
                return trigger, audio, None
        return None, None, None

    # ── Command dispatch ──────────────────────
    def traiter_commande(self, trigger: str, audio_file, action_info):
        if trigger == "stop":
            self.is_listening = False
            return
        if self._on_cooldown(trigger):
            logger.debug(f"Cooldown active: {trigger}")
            return
        self._mark(trigger)
        if action_info:
            if self.on_command_detected:
                self.on_command_detected(trigger, None, action_info)
            success = self.executer_action_systeme(action_info)
            if success and trigger in self.commands:
                self.jouer_audio(self.commands[trigger])
        elif trigger and audio_file:
            if self.on_command_detected:
                self.on_command_detected(trigger, audio_file, None)
            self.jouer_audio(audio_file)

    # ── Listen loop ───────────────────────────
    def ecouter_et_repondre(self):
        if self.on_listening_start:
            self.on_listening_start()
        if self.backend == "vosk":
            self._loop_vosk()
        else:
            self._loop_google()
        if self.on_listening_stop:
            self.on_listening_stop()

    def _loop_google(self):
        net_errors = 0
        with self._mic as source:
            while self.is_listening:
                try:
                    if pygame.mixer.music.get_busy():
                        time.sleep(0.1)
                        continue
                    audio = self._rec.listen(
                        source,
                        timeout=self.listen_timeout,
                        phrase_time_limit=self.phrase_limit,
                    )
                    try:
                        texte = self._rec.recognize_google(audio, language=self.language).lower()
                    except self._sr.UnknownValueError:
                        continue
                    net_errors = 0
                    trigger, audio_file, action_info = self._match(texte)
                    if trigger:
                        self.traiter_commande(trigger, audio_file, action_info)

                except self._sr.WaitTimeoutError:
                    continue
                except self._sr.RequestError:
                    net_errors += 1
                    if net_errors >= self.max_retry:
                        self._notify_error(
                            f"Speech service unavailable after {self.max_retry} attempts. "
                            f"Retrying in {self.retry_delay}s…"
                        )
                        time.sleep(self.retry_delay)
                        net_errors = 0
                    else:
                        time.sleep(1)
                except OSError as e:
                    self._notify_error(f"Microphone error: {e} — reconnecting in {self.retry_delay}s")
                    time.sleep(self.retry_delay)
                    try:
                        import speech_recognition as sr
                        self._mic = sr.Microphone()
                        source = self._mic.__enter__()
                        self._notify_word("Microphone reconnected.")
                    except Exception as re:
                        self._notify_error(f"Microphone reconnection failed: {re}")
                        self.is_listening = False
                except Exception as e:
                    self._notify_error(f"Unexpected error: {e}")
                    time.sleep(0.5)

    def _loop_vosk(self):
        while self.is_listening:
            try:
                if pygame.mixer.music.get_busy():
                    time.sleep(0.1)
                    continue
                texte = self._vosk.listen_once(self.phrase_limit)
                if texte:
                    trigger, audio_file, action_info = self._match(texte)
                    if trigger:
                        self.traiter_commande(trigger, audio_file, action_info)
            except Exception as e:
                self._notify_error(f"Vosk error: {e}")
                time.sleep(0.5)

    def demarrer(self):
        self.calibrer_micro()
        self._start_thread()


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────
def verifier_fichiers_audio():
    Path(SOUNDS_DIR).mkdir(exist_ok=True)
    return True


if __name__ == "__main__":
    try:
        from ear_gui import VoiceAssistantGUI

        if platform.system() == "Windows":
            import ctypes
            ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)

        verifier_fichiers_audio()
        app = AudioCommandRecognizer()
        gui = VoiceAssistantGUI(app)
        gui.run()

    except ImportError as e:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Error", f"Could not launch the graphical interface:\n{e}")