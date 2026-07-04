import cv2
import re
import flask
import numpy as np
import datetime
import os
from pathlib import Path
import time
import socket
import getpass
from flask import Response, request, jsonify, stream_with_context, session, redirect, url_for
from functools import wraps
import webbrowser
import threading
import pyttsx3
import pygame
import sounddevice as sd
import queue
import base64
import json
import struct
import logging
import traceback
import sys
import secrets

# ── Variables d'environnement (.env local, jamais committé) ──────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
except ImportError:
    pass  # python-dotenv optionnel — fonctionne sans si variables déjà dans l'env

# ─────────────────────────────────────────────
#  SYSTÈME DE LOGS
#  Écrit dans la console ET dans jvo_debug.log
#  (dans le même dossier que ce script)
# ─────────────────────────────────────────────
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jvo_debug.log")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8", mode="w"),  # écrase à chaque démarrage
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("JVO")
log.info(f"=== Démarrage — logs dans : {LOG_FILE} ===")

# Intercepte toutes les exceptions non catchées
def _handle_uncaught(exc_type, exc_value, exc_tb):
    log.critical("EXCEPTION NON CATCHÉE !", exc_info=(exc_type, exc_value, exc_tb))
sys.excepthook = _handle_uncaught

app = flask.Flask(__name__)
ngrok_public_url = None   # rempli au démarrage si NGROK_TOKEN présent

# Clé de session Flask (générée aléatoirement au démarrage si absente du .env)
app.secret_key = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32)

# Mot de passe de l'interface (lu depuis .env — NE PAS mettre en dur ici)
APP_PASSWORD = os.environ.get('JVO_PASSWORD', '')

def login_required(f):
    """Décorateur : redirige vers /login si non authentifié."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not APP_PASSWORD:
            return f(*args, **kwargs)   # pas de mot de passe défini → accès libre (LAN only)
        if not session.get('authenticated'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def api_auth(f):
    """Décorateur pour les routes API (JSON) : retourne 401 si non authentifié."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not APP_PASSWORD:
            return f(*args, **kwargs)
        if not session.get('authenticated'):
            return jsonify({"status": "error", "message": "Non authentifié"}), 401
        return f(*args, **kwargs)
    return decorated

# ─────────────────────────────────────────────
#  DIFFUSION AUDIO EN TEMPS RÉEL (SSE)
#  Capture le loopback audio (stéréo mix / what-u-hear)
#  et le diffuse aux clients web via Server-Sent Events.
# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
#  DIFFUSION AUDIO EN TEMPS RÉEL (SSE)
#  Capture le micro de la salle (Logitech C270 en priorité,
#  sinon le micro par défaut) et le diffuse aux clients web
#  via Server-Sent Events + Web Audio API.
# ─────────────────────────────────────────────
AUDIO_SAMPLERATE = 44100   # Hz — taux natif de la C920
AUDIO_CHANNELS   = 1       # Mono
AUDIO_CHUNK      = 4096    # ~93 ms par trame à 44100 Hz

audio_clients      = []
audio_clients_lock = threading.Lock()

# ─────────────────────────────────────────────
#  QUALITÉ VIDÉO — modifiable à chaud via /set_quality
# ─────────────────────────────────────────────
QUALITY_PRESETS = {
    "hd":     {"res": (960, 540), "jpeg": 80, "fps_div": 1, "label": "HD  960×540 q80 ~13 Mbit/s"},
    "medium": {"res": (640, 360), "jpeg": 65, "fps_div": 1, "label": "Moyen 640×360 q65 ~4 Mbit/s"},
    "low":    {"res": (480, 270), "jpeg": 50, "fps_div": 2, "label": "Eco  480×270 q50 ~1 Mbit/s"},
}
stream_quality = "medium"   # défaut économique

def _audio_callback(indata, frames, time_info, status):
    """Recoit chaque bloc micro et le pousse vers tous les clients SSE.
    IMPORTANT : pas d'allocation lourde ici - thread temps-reel."""
    if status:
        log.warning(f"[MICRO] sounddevice status : {status}")
    try:
        # Copie rapide du canal mono avant que le buffer ne soit recycle
        mono = indata[:, 0].copy()
        pcm  = (mono * 32767).astype(np.int16).tobytes()
        b64  = base64.b64encode(pcm).decode('ascii')
        payload = f"data: {b64}\n\n"
        with audio_clients_lock:
            dead = []
            for q in audio_clients:
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                audio_clients.remove(q)
    except Exception as e:
        log.warning(f"[MICRO] callback error : {e}")

def _find_mic_device():
    """
    Cherche le meilleur micro disponible dans cet ordre :
      1. Micro de la Logitech C270 (ou toute webcam Logitech)
      2. Tout autre micro USB
      3. Micro par defaut du systeme (None)
    """
    devices = sd.query_devices()
    print("\n[MICRO] Peripheriques d'entree disponibles :")
    for i, d in enumerate(devices):
        if d['max_input_channels'] > 0:
            print(f"  [{i}] {d['name']}  (ch={d['max_input_channels']}, sr={int(d['default_samplerate'])})")

    # Priorité 1 : C920 à 44100 Hz (entrée native)
    for i, d in enumerate(devices):
        name = d['name'].lower()
        if d['max_input_channels'] > 0 and ('logitech' in name or 'c920' in name or 'webcam' in name):
            if int(d['default_samplerate']) == 44100:
                print(f"[MICRO] Logitech C920 trouvee (44100 Hz) : {d['name']} (idx {i})")
                return i

    # Priorité 2 : C920 à n'importe quel taux
    for i, d in enumerate(devices):
        name = d['name'].lower()
        if d['max_input_channels'] > 0 and ('logitech' in name or 'c920' in name or 'webcam' in name):
            print(f"[MICRO] Logitech C920 trouvee : {d['name']} (idx {i})")
            return i

    for i, d in enumerate(devices):
        name = d['name'].lower()
        if d['max_input_channels'] > 0 and 'usb' in name:
            print(f"[MICRO] Micro USB trouve : {d['name']} (idx {i})")
            return i

    print("[MICRO] Aucun micro USB/Logitech trouve, utilisation du micro par defaut.")
    return None

_mic_stream     = None   # instance sd.InputStream active
_mic_stream_lock = threading.Lock()
mic_active      = False  # état courant

def mic_start():
    """Ouvre le micro et démarre la capture. Appelé uniquement à la demande."""
    global _mic_stream, mic_active
    with _mic_stream_lock:
        if mic_active:
            return True  # déjà actif
        try:
            device_idx = _find_mic_device()
            log.info(f"[MICRO] Ouverture micro (idx={device_idx}, {AUDIO_SAMPLERATE} Hz)…")
            _mic_stream = sd.InputStream(
                device=device_idx,
                samplerate=AUDIO_SAMPLERATE,
                channels=AUDIO_CHANNELS,
                dtype='float32',
                blocksize=AUDIO_CHUNK,
                callback=_audio_callback,
            )
            _mic_stream.start()
            mic_active = True
            log.info("[MICRO] ✓ Micro ouvert")
            return True
        except Exception as e:
            log.error(f"[MICRO] Impossible d'ouvrir : {e}")
            _mic_stream = None
            mic_active  = False
            return False

def mic_stop():
    """Ferme le micro et libère la ressource."""
    global _mic_stream, mic_active
    with _mic_stream_lock:
        if not mic_active or _mic_stream is None:
            return
        try:
            _mic_stream.stop()
            _mic_stream.close()
            log.info("[MICRO] Micro fermé")
        except Exception as e:
            log.warning(f"[MICRO] Erreur fermeture : {e}")
        finally:
            _mic_stream = None
            mic_active  = False

# ─────────────────────────────────────────────
#  TTS ENGINE
#  Priorité 1 : edge-tts  (voix neuronale Microsoft Edge)
#               pip install edge-tts  — Python 3.13 OK, aucun droit admin
#  Priorité 2 : pyttsx3   (SAPI5 Windows, fallback hors-ligne)
# ─────────────────────────────────────────────
tts_lock       = threading.Lock()
EDGE_TTS_VOICE = "fr-FR-DeniseNeural"

def _speak_edge(text: str, retries: int = 2):
    import asyncio, tempfile, edge_tts
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp = f.name
    try:
        last_err = None
        for attempt in range(1, retries + 2):  # ex: retries=2 → 3 tentatives
            try:
                async def _gen():
                    await edge_tts.Communicate(text, EDGE_TTS_VOICE).save(tmp)
                asyncio.run(_gen())
                last_err = None
                break
            except Exception as e:
                last_err = e
                log.warning(f"[TTS/Edge] Tentative {attempt} échouée : {e}")
                if attempt <= retries:
                    time.sleep(0.6)
        if last_err:
            raise last_err
        with audio_lock:
            pygame.mixer.music.load(tmp)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
    finally:
        Path(tmp).unlink(missing_ok=True)

def _speak_pyttsx3(text: str):
    # Fallback hors-ligne via SAPI5 Windows — aucune dépendance réseau.
    engine = pyttsx3.init()
    try:
        # Tenter de sélectionner une voix française si disponible
        for voice in engine.getProperty('voices'):
            if 'fr' in (voice.languages[0].decode('utf-8', 'ignore')
                        if voice.languages else voice.id).lower() or 'french' in voice.name.lower():
                engine.setProperty('voice', voice.id)
                break
        engine.say(text)
        engine.runAndWait()
    finally:
        engine.stop()

def speak_text(text: str):
    def _run():
        with tts_lock:
            log.info(f"[TTS/Edge] {text}")
            try:
                _speak_edge(text)
            except Exception as e:
                log.error(f"[TTS/Edge] Échec après retries : {e} — bascule sur pyttsx3 (hors-ligne)")
                try:
                    _speak_pyttsx3(text)
                    log.info("[TTS/pyttsx3] Lecture réussie (fallback)")
                except Exception as e2:
                    log.error(f"[TTS/pyttsx3] Échec également : {e2}")
    threading.Thread(target=_run, daemon=True).start()
# ─────────────────────────────────────────────
#  AUDIO / MP3 (pygame mixer)
# ─────────────────────────────────────────────
pygame.mixer.init()
MP3_DIR   = os.path.join(os.environ.get('USERPROFILE', os.path.expanduser('~')), 'Music', 'jvo_sounds')
os.makedirs(MP3_DIR, exist_ok=True)

TIMER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mp3_timer')
os.makedirs(TIMER_DIR, exist_ok=True)

audio_lock = threading.Lock()

def play_mp3_file(path: str):
    """Joue un fichier MP3/WAV dans un thread dédié."""
    def _run():
        with audio_lock:
            try:
                pygame.mixer.music.load(path)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
            except Exception as e:
                print(f"Erreur lecture audio: {e}")
    threading.Thread(target=_run, daemon=True).start()

# ─────────────────────────────────────────────
#  CAMÉRA
# ─────────────────────────────────────────────
class RobustCamera:
    def __init__(self):
        self.cap = None
        self.backend = cv2.CAP_DSHOW
        self._lock = threading.Lock()  # FIX: empêche les race conditions multi-threads
        self.init_camera()

    def init_camera(self):
        log.info("[CAM] init_camera() appelé")
        if self.cap is not None:
            log.debug("[CAM] Libération du cap existant")
            self.cap.release()
            time.sleep(1)
        try:
            log.debug("[CAM] Tentative VideoCapture(0, CAP_DSHOW)")
            self.cap = cv2.VideoCapture(0, self.backend)
            if not self.cap.isOpened():
                log.warning("[CAM] CAP_DSHOW échoué, tentative backend par défaut...")
                self.cap = cv2.VideoCapture(0)
            if not self.cap.isOpened():
                log.error("[CAM] ERREUR: Impossible d'ouvrir la caméra (index 0)")
                return False
            log.debug("[CAM] Caméra ouverte, configuration en cours...")
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.cap.set(cv2.CAP_PROP_FPS, 25)
            try:
                self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            except:
                pass
            self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
            for attempt in range(5):
                success, frame = self.cap.read()
                if success and frame is not None:
                    log.info(f"[CAM] ✓ Caméra initialisée avec succès (tentative {attempt+1}), shape={frame.shape}")
                    return True
                log.debug(f"[CAM] Tentative {attempt+1}/5 de lecture échouée")
                time.sleep(0.1)
            log.error("[CAM] ✗ Caméra ouverte mais ne renvoie pas d'image après 5 tentatives")
            return False
        except Exception as e:
            log.error(f"[CAM] ERREUR initialisation caméra: {e}")
            log.debug(traceback.format_exc())
            return False

    def read(self):
        with self._lock:  # FIX: verrou pour éviter les accès concurrents
            if self.cap is None:
                log.warning("[CAM] cap=None, réinitialisation...")
                if not self.init_camera():
                    log.error("[CAM] Réinitialisation échouée dans read()")
                    return False, None
            try:
                success, frame = self.cap.read()
                if not success or frame is None:
                    log.warning("[CAM] cap.read() a retourné échec, tentative de récupération...")
                    self.init_camera()
                    success, frame = self.cap.read() if self.cap else (False, None)
                    if not success:
                        log.error("[CAM] Récupération échouée, retourne frame vide")
                return success, frame
            except Exception as e:
                log.error(f"[CAM] Exception dans read(): {type(e).__name__}: {e}")
                log.debug(traceback.format_exc())
                return False, None


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"



def save_html_file():
    """
    Génère un fichier cam.html qui redirige simplement vers http://IP:5000.
    Ainsi, depuis n'importe quel poste du LAN, ouvrir cam.html ouvre
    l'interface complète servie par Flask — sans problème de sécurité file://.
    """
    ip_address = get_local_ip()
    print(f"Adresse IP détectée: {ip_address}")
    server_url = f"http://{ip_address}:5000"

    # Fichier de redirection simple — pas de ressources locales
    html_content = f'''<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="0; url={server_url}">
  <title>Redirection Salle JVO…</title>
</head>
<body>
  <p>Redirection vers <a href="{server_url}">{server_url}</a>…</p>
  <script>window.location.replace("{server_url}");</script>
</body>
</html>'''

    # Essayer d'écrire sur le lecteur réseau, sinon en local
    destination_path = r"L:\Groups\mediatheque\06- SECTEUR INFORMATIQUE\7- SALLE JVO"
    if not os.path.exists(destination_path):
        print(f"Chemin réseau inaccessible, sauvegarde locale.")
        destination_path = "."

    html_file_path = os.path.join(destination_path, "cam.html")
    try:
        with open(html_file_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"Fichier cam.html généré : {html_file_path}")
    except Exception as e:
        print(f"Impossible d'écrire cam.html : {e}")




# ─────────────────────────────────────────────
#  INITIALISATION
# ─────────────────────────────────────────────
camera = RobustCamera()
motion_detected = False
last_frame = None
_latest_frame = None   # dernière frame brute pour snapshot à la demande
motion_threshold = 1500
capture_count = 0
MAX_CAPTURES = 100
SAVE_CAPTURES = False   # désactivé par défaut pour réduire l'activité fichier suspecte
ABSENT_MODE   = False   # mode absent : message audio + capture sur mouvement

user_profile = os.environ.get('USERPROFILE', os.path.expanduser('~'))
motion_captures_dir = os.path.join(user_profile, 'Pictures', 'motion_captures')
os.makedirs(motion_captures_dir, exist_ok=True)


_capture_queue = queue.Queue(maxsize=10)

def _capture_writer():
    """Thread dedié ecriture captures disque - n'a jamais bloqué le stream."""
    global capture_count
    while True:
        try:
            frame, timestamp = _capture_queue.get()
            if capture_count >= MAX_CAPTURES:
                try:
                    files = sorted(os.listdir(motion_captures_dir))
                    for old_file in files[:max(0, len(files) - MAX_CAPTURES + 1)]:
                        Path(os.path.join(motion_captures_dir, old_file)).unlink(missing_ok=True)
                    capture_count = max(0, capture_count - 1)
                except Exception as e:
                    log.warning(f"[CAPTURE] Nettoyage : {e}")
            filename  = f"motion_{timestamp}.jpg"
            file_path = os.path.join(motion_captures_dir, filename)
            small = cv2.resize(frame, (640, 360))
            cv2.imwrite(file_path, small, [cv2.IMWRITE_JPEG_QUALITY, 80])
            capture_count += 1
            log.debug(f"[CAPTURE] Sauvegarde : {filename}")
        except Exception as e:
            log.error(f"[CAPTURE] Erreur ecriture : {e}")

threading.Thread(target=_capture_writer, daemon=True).start()


def save_capture(frame):
    """Enfile la capture pour ecriture asynchrone - ne bloque jamais le stream."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    try:
        _capture_queue.put_nowait((frame.copy(), timestamp))
    except queue.Full:
        log.warning("[CAPTURE] File pleine, capture ignoree")
    return None


def detect_motion(current_frame):
    global last_frame, motion_detected, ABSENT_MODE
    if current_frame is None:
        return False, None
    resized_frame = cv2.resize(current_frame, (640, 360))
    gray = cv2.cvtColor(resized_frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (21, 21), 0)
    if last_frame is None:
        last_frame = gray
        return False, current_frame
    frame_diff = cv2.absdiff(last_frame, gray)
    thresh = cv2.threshold(frame_diff, 25, 255, cv2.THRESH_BINARY)[1]
    thresh = cv2.dilate(thresh, None, iterations=2)
    contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    motion_detected = False
    output_frame = current_frame.copy()
    for contour in contours:
        if cv2.contourArea(contour) > motion_threshold:
            motion_detected = True
            (x, y, w, h) = cv2.boundingRect(contour)
            x, y, w, h = x*2, y*2, w*2, h*2
            cv2.rectangle(output_frame, (x, y), (x + w, y + h), (0, 255, 0), 3)
            cv2.putText(output_frame, "MOTION DETECTED", (10, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3)
    last_frame = gray
    return motion_detected, output_frame


def generate_frames():
    global motion_detected, _latest_frame
    motion_cooldown = 0
    face_frame_skip = 0   # reconnaissance faciale : 1 frame analysée sur 6 (coût LBPH)
    frame_count = 0
    log.info("[STREAM] generate_frames() démarré")
    while True:
        try:
            success, frame = camera.read()
            if not success or frame is None:
                log.warning(f"[STREAM] frame #{frame_count} — caméra indisponible, frame noire envoyée")
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(frame, "CAMERA ERROR - RECONNECTION...", (50, 240),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            else:
                frame_count += 1
                _latest_frame = frame   # snapshot à la demande (global)
                if frame_count % 100 == 0:
                    log.debug(f"[STREAM] ✓ {frame_count} frames envoyées, shape={frame.shape}")
                if frame_count % 2 == 0:
                    motion_detected, frame = detect_motion(frame)
                    if motion_detected and motion_cooldown == 0:
                        if SAVE_CAPTURES:
                            log.info("[STREAM] Mouvement détecté — capture sauvegardée")
                            save_capture(frame)
                        if ABSENT_MODE:
                            log.info("[ABSENT] Mouvement détecté — snapshot + audio")
                            save_capture(frame)
                            _trigger_absent_alert()
                        motion_cooldown = 30
                if motion_cooldown > 0:
                    motion_cooldown -= 1
                # Reconnaissance faciale (coûteuse — 1 frame sur 6)
                if FACE_RECOGNITION_ENABLED:
                    face_frame_skip += 1
                    if face_frame_skip >= 6:
                        face_frame_skip = 0
                        frame, recognized = recognize_faces(frame)
                        if recognized:
                            log.info(f"[FACE] Reconnu(e) : {', '.join(recognized)}")
                            save_capture(frame)
                            _trigger_face_alert(recognized)
            q      = QUALITY_PRESETS[stream_quality]
            # Limite fps selon le preset (fps_div=2 → on saute 1 frame sur 2)
            if frame_count % q["fps_div"] != 0:
                continue
            stream_frame = cv2.resize(frame, q["res"])
            ret, buffer = cv2.imencode('.jpg', stream_frame, [cv2.IMWRITE_JPEG_QUALITY, q["jpeg"]])
            if ret:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            else:
                log.error(f"[STREAM] cv2.imencode() a échoué à la frame #{frame_count}")
                error_frame = np.zeros((540, 960, 3), dtype=np.uint8)
                cv2.putText(error_frame, "ENCODING ERROR", (300, 270),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                _, buffer = cv2.imencode('.jpg', error_frame)
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        except GeneratorExit:
            log.info(f"[STREAM] Client déconnecté après {frame_count} frames (GeneratorExit normal)")
            break
        except Exception as e:
            log.error(f"[STREAM] Exception à la frame #{frame_count}: {type(e).__name__}: {e}")
            log.debug(traceback.format_exc())
            time.sleep(0.5)
            try:
                error_frame = np.zeros((540, 960, 3), dtype=np.uint8)
                cv2.putText(error_frame, "STREAM ERROR - RECOVERING...", (200, 270),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
                _, buffer = cv2.imencode('.jpg', error_frame)
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            except GeneratorExit:
                log.info("[STREAM] GeneratorExit pendant récupération, arrêt propre")
                break
            except Exception as e2:
                log.error(f"[STREAM] Erreur lors de l'envoi de la frame d'erreur: {e2}")


# ─────────────────────────────────────────────
#  ROUTES FLASK
# ─────────────────────────────────────────────

@app.route('/video_feed')
@api_auth
def video_feed():
    client_ip = request.remote_addr
    log.info(f"[HTTP] GET /video_feed — client={client_ip}")
    try:
        resp = Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')
        log.info(f"[HTTP] Response objet créé pour {client_ip}, démarrage du stream")
        return resp
    except Exception as e:
        log.error(f"[HTTP] Erreur création Response /video_feed: {e}")
        log.debug(traceback.format_exc())
        return Response("Erreur serveur", status=500)


# ── TTS ──────────────────────────────────────
# Fichier JSON des phrases pre-enregistrees
PHRASES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'phrases.json')

EDGE_VOICES = [
    {"id": "fr-FR-DeniseNeural",   "label": "FR Denise (femme)"},
    {"id": "fr-FR-HenriNeural",    "label": "FR Henri (homme)"},
    {"id": "fr-FR-EloiseNeural",   "label": "FR Eloise (fille)"},
    {"id": "fr-BE-CharlineNeural", "label": "BE Charline"},
    {"id": "fr-CH-ArianeNeural",   "label": "CH Ariane"},
    {"id": "fr-CA-SylvieNeural",   "label": "CA Sylvie"},
]

def _load_phrases():
    defaults = [
        {"id": 1, "text": "Bonjour, bienvenue dans la salle jeux video."},
        {"id": 2, "text": "Un membre du personnel va arriver dans quelques instants."},
        {"id": 3, "text": "Vous pouvez vous installer dans la salle du fond."},
        {"id": 4, "text": "Attention, la salle fermera dans quelques minutes !"},
        {"id": 5, "text": "Vous pouvez consulter les jeux disponibles sur le panneau."},
    ]
    try:
        if os.path.exists(PHRASES_FILE):
            with open(PHRASES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        log.warning(f"[PHRASES] Lecture echouee : {e}")
    return defaults

def _save_phrases(phrases):
    try:
        with open(PHRASES_FILE, 'w', encoding='utf-8') as f:
            json.dump(phrases, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"[PHRASES] Sauvegarde echouee : {e}")

@app.route('/tts', methods=['POST'])
@api_auth
def tts():
    data = request.get_json(silent=True) or {}
    text = data.get('text', '').strip()
    if not text:
        return jsonify({"status": "error", "message": "Champ text manquant ou vide"}), 400
    log.info(f"[TTS] {text}")
    speak_text(text)
    return jsonify({"status": "ok", "text": text})

@app.route('/voices')
def voices():
    return jsonify({"voices": EDGE_VOICES, "current": EDGE_TTS_VOICE})

@app.route('/set_voice', methods=['POST'])
@api_auth
def set_voice():
    global EDGE_TTS_VOICE
    data = request.get_json(silent=True) or {}
    v = data.get('voice', '').strip()
    if not any(x['id'] == v for x in EDGE_VOICES):
        return jsonify({"status": "error", "message": "Voix inconnue"}), 400
    EDGE_TTS_VOICE = v
    log.info(f"[TTS] Voix changee : {v}")
    return jsonify({"status": "ok", "voice": v})

@app.route('/phrases')
def get_phrases():
    return jsonify({"phrases": _load_phrases()})

@app.route('/phrases', methods=['POST'])
def add_phrase():
    data = request.get_json(silent=True) or {}
    text = data.get('text', '').strip()
    if not text:
        return jsonify({"status": "error", "message": "Texte vide"}), 400
    phrases = _load_phrases()
    new_id  = max((p['id'] for p in phrases), default=0) + 1
    phrases.append({"id": new_id, "text": text})
    _save_phrases(phrases)
    return jsonify({"status": "ok", "phrases": phrases})

@app.route('/phrases/reorder', methods=['POST'])
@api_auth
def reorder_phrases():
    data    = request.get_json(force=True)
    new_order = data.get('order', [])   # liste d'ids dans le nouvel ordre
    phrases   = _load_phrases()
    id_map    = {p['id']: p for p in phrases}
    reordered = [id_map[i] for i in new_order if i in id_map]
    # Ajouter les phrases non listées à la fin (sécurité)
    listed_ids = set(new_order)
    reordered += [p for p in phrases if p['id'] not in listed_ids]
    _save_phrases(reordered)
    return jsonify({"status": "ok", "phrases": reordered})


@app.route('/phrases/<int:pid>', methods=['DELETE'])
def delete_phrase(pid):
    phrases = [p for p in _load_phrases() if p['id'] != pid]
    _save_phrases(phrases)
    return jsonify({"status": "ok", "phrases": phrases})




# ── MP3 : upload ─────────────────────────────
@app.route('/upload_mp3', methods=['POST'])
@api_auth
def upload_mp3():
    """
    Reçoit un fichier audio (MP3/WAV) et le sauvegarde dans MP3_DIR.
    Form-data : champ 'file'
    """
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "Aucun fichier envoyé"}), 400
    f = request.files['file']
    if f.filename == '':
        return jsonify({"status": "error", "message": "Nom de fichier vide"}), 400
    # Sécuriser le nom de fichier
    safe_name = os.path.basename(f.filename).replace(' ', '_')
    dest = os.path.join(MP3_DIR, safe_name)
    f.save(dest)
    print(f"[AUDIO] Fichier uploadé: {dest}")
    return jsonify({"status": "ok", "filename": safe_name})


# ── MP3 : liste ──────────────────────────────
@app.route('/list_mp3')
def list_mp3():
    """Retourne la liste des fichiers audio dans l'ordre sauvegarde."""
    try:
        all_files = [f for f in os.listdir(MP3_DIR)
                     if f.lower().endswith(('.mp3', '.wav', '.ogg'))]
        saved  = _load_mp3_order()
        ordered = [f for f in saved if f in all_files]
        rest    = sorted([f for f in all_files if f not in ordered])
        files   = ordered + rest
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "ok", "files": files})


# ── MP3 : lecture ─────────────────────────────
@app.route('/set_volume', methods=['POST'])
@api_auth
def set_volume():
    """POST JSON : {"volume": 0.8}  — 0.0 à 1.0"""
    data = request.get_json(silent=True) or {}
    vol  = float(data.get('volume', 1.0))
    vol  = max(0.0, min(1.0, vol))
    try:
        pygame.mixer.music.set_volume(vol)
        return jsonify({"status": "ok", "volume": vol})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/play_mp3', methods=['POST'])
@api_auth
def play_mp3():
    """POST JSON : {"filename": "alerte.mp3"}"""
    data     = request.get_json(silent=True) or {}
    filename = data.get('filename', '').strip()
    if not filename:
        return jsonify({"status": "error", "message": "Champ 'filename' manquant"}), 400
    path = os.path.join(MP3_DIR, os.path.basename(filename))
    if not os.path.exists(path):
        return jsonify({"status": "error", "message": f"Fichier introuvable: {filename}"}), 404
    print(f"[AUDIO] ← lecture {filename}")
    play_mp3_file(path)
    return jsonify({"status": "ok", "filename": filename})


# ── Mode absent ───────────────────────────────
_absent_alert_cooldown = 0
_absent_alert_lock = threading.Lock()

def _trigger_absent_alert():
    """Joue le fichier absent.mp3 (si présent) + capture. Cooldown 60 s."""
    global _absent_alert_cooldown
    with _absent_alert_lock:
        if _absent_alert_cooldown > 0:
            return
        _absent_alert_cooldown = 60
    # Son absent.mp3 dans TIMER_DIR ou MP3_DIR
    for d in (TIMER_DIR, MP3_DIR):
        p = os.path.join(d, 'absent.mp3')
        if os.path.exists(p):
            play_mp3_file(p)
            break
    # Décrémenter le cooldown en arrière-plan
    def _dec():
        import time as _t
        for _ in range(60):
            _t.sleep(1)
            global _absent_alert_cooldown
            _absent_alert_cooldown = max(0, _absent_alert_cooldown - 1)
    threading.Thread(target=_dec, daemon=True).start()

@app.route('/absent_mode', methods=['POST'])
@api_auth
def toggle_absent_mode():
    global ABSENT_MODE, SAVE_CAPTURES
    data = request.get_json(silent=True) or {}
    ABSENT_MODE = bool(data.get('active', not ABSENT_MODE))
    if ABSENT_MODE:
        SAVE_CAPTURES = True   # activer aussi les captures mouvement
    log.info(f"[ABSENT] Mode {'activé' if ABSENT_MODE else 'désactivé'}")
    return jsonify({"status": "ok", "absent": ABSENT_MODE})

@app.route('/absent_mode')
@api_auth
def get_absent_mode():
    return jsonify({"absent": ABSENT_MODE})


# ── Reconnaissance faciale ────────────────────
# Détection : Haar Cascade (livré avec OpenCV, aucun téléchargement)
# Reconnaissance : LBPH (cv2.face, déjà dans opencv-contrib-python)
FACES_DIR     = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'faces')
FACES_RAW_DIR = os.path.join(FACES_DIR, 'photos')      # photos brutes par personne
FACES_MODEL   = os.path.join(FACES_DIR, 'model.yml')   # modèle LBPH entraîné
FACES_LABELS  = os.path.join(FACES_DIR, 'labels.json') # id numérique → nom
os.makedirs(FACES_RAW_DIR, exist_ok=True)
os.makedirs(os.path.join(FACES_DIR, 'sounds'), exist_ok=True)

_face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
_face_recognizer = None     # créé/chargé à la demande
_face_labels      = {}      # {id: "Nom"}
_face_lock        = threading.Lock()
FACE_RECOGNITION_ENABLED = False    # toggle global activable depuis l'UI
FACE_CONFIDENCE_THRESHOLD = 70      # LBPH : plus bas = plus strict (0=identique)

_last_recognitions = []     # historique court {name, ts} pour l'UI
MAX_RECOGNITIONS_LOG = 20
_face_alert_cooldowns = {}  # {name: timestamp dernière alerte}
FACE_ALERT_COOLDOWN_S = 60

def _trigger_face_alert(names):
    """Joue un son par personne reconnue (si <nom>.mp3 existe), avec cooldown 60s/personne."""
    now = time.time()
    for name in names:
        last = _face_alert_cooldowns.get(name, 0)
        if now - last < FACE_ALERT_COOLDOWN_S:
            continue
        _face_alert_cooldowns[name] = now
        # Cherche un son nominatif optionnel : faces/sounds/<nom>.mp3
        sound_path = os.path.join(FACES_DIR, 'sounds', f"{name}.mp3")
        if os.path.exists(sound_path):
            play_mp3_file(sound_path)

def _load_face_labels():
    global _face_labels
    if os.path.exists(FACES_LABELS):
        try:
            with open(FACES_LABELS, 'r', encoding='utf-8') as f:
                _face_labels = {int(k): v for k, v in json.load(f).items()}
        except Exception as e:
            log.error(f"[FACE] Erreur lecture labels: {e}")
            _face_labels = {}
    else:
        _face_labels = {}

def _save_face_labels():
    with open(FACES_LABELS, 'w', encoding='utf-8') as f:
        json.dump({str(k): v for k, v in _face_labels.items()}, f, ensure_ascii=False, indent=2)

def _load_face_model():
    """Charge le modèle LBPH s'il existe."""
    global _face_recognizer
    if not os.path.exists(FACES_MODEL):
        _face_recognizer = None
        return False
    try:
        rec = cv2.face.LBPHFaceRecognizer_create()
        rec.read(FACES_MODEL)
        _face_recognizer = rec
        log.info("[FACE] Modèle chargé")
        return True
    except Exception as e:
        log.error(f"[FACE] Erreur chargement modèle: {e}")
        _face_recognizer = None
        return False

def train_face_model():
    """
    Reconstruit le modèle LBPH à partir de toutes les photos dans FACES_RAW_DIR/<nom>/*.jpg
    Appelé après ajout/suppression de personnes.
    """
    global _face_recognizer, _face_labels
    with _face_lock:
        people = sorted([d for d in os.listdir(FACES_RAW_DIR)
                         if os.path.isdir(os.path.join(FACES_RAW_DIR, d))])
        if not people:
            _face_recognizer = None
            _face_labels = {}
            for f in (FACES_MODEL, FACES_LABELS):
                Path(f).unlink(missing_ok=True)
            log.info("[FACE] Aucune personne enregistrée — modèle réinitialisé")
            return True

        faces_data, ids, labels = [], [], {}
        for idx, person in enumerate(people):
            labels[idx] = person
            person_dir = os.path.join(FACES_RAW_DIR, person)
            for fname in os.listdir(person_dir):
                if not fname.lower().endswith(('.jpg', '.jpeg', '.png')):
                    continue
                img_path = os.path.join(person_dir, fname)
                img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
                if img is None:
                    continue
                detected = _face_cascade.detectMultiScale(img, 1.1, 5, minSize=(60, 60))
                if len(detected) == 0:
                    # Pas de visage détecté — utiliser l'image entière en dernier recours
                    face_roi = cv2.resize(img, (200, 200))
                else:
                    (x, y, w, h) = max(detected, key=lambda r: r[2] * r[3])
                    face_roi = cv2.resize(img[y:y+h, x:x+w], (200, 200))
                faces_data.append(face_roi)
                ids.append(idx)

        if not faces_data:
            log.warning("[FACE] Aucun visage exploitable dans les photos fournies")
            return False

        rec = cv2.face.LBPHFaceRecognizer_create()
        rec.train(faces_data, np.array(ids))
        rec.write(FACES_MODEL)
        _face_recognizer = rec
        _face_labels = labels
        _save_face_labels()
        log.info(f"[FACE] Modèle entraîné : {len(people)} personne(s), {len(faces_data)} photo(s)")
        return True

def recognize_faces(frame):
    """
    Détecte et identifie les visages dans une frame BGR.
    Retourne (frame_annotée, liste de noms reconnus dans cette frame).
    """
    global _last_recognitions
    if frame is None or not FACE_RECOGNITION_ENABLED:
        return frame, []
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    detected = _face_cascade.detectMultiScale(gray, 1.1, 5, minSize=(80, 80))
    recognized_names = []
    output = frame.copy()
    for (x, y, w, h) in detected:
        name = "Inconnu"
        color = (0, 165, 255)  # orange = non identifié
        if _face_recognizer is not None and _face_labels:
            try:
                face_roi = cv2.resize(gray[y:y+h, x:x+w], (200, 200))
                label_id, confidence = _face_recognizer.predict(face_roi)
                if confidence < FACE_CONFIDENCE_THRESHOLD and label_id in _face_labels:
                    name = _face_labels[label_id]
                    color = (0, 220, 0)  # vert = identifié
                    recognized_names.append(name)
            except Exception as e:
                log.debug(f"[FACE] Erreur prediction: {e}")
        cv2.rectangle(output, (x, y), (x + w, y + h), color, 2)
        cv2.putText(output, name, (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    if recognized_names:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        for name in recognized_names:
            _last_recognitions.insert(0, {"name": name, "time": ts})
        _last_recognitions = _last_recognitions[:MAX_RECOGNITIONS_LOG]
    return output, recognized_names

_load_face_labels()
_load_face_model()


# ── Snapshot à la demande ────────────────────
SNAPSHOTS_DIR = os.path.join(user_profile, 'Pictures', 'jvo_snapshots')
os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
MAX_SNAPSHOTS = 50

@app.route('/snapshot', methods=['POST'])
@api_auth
def take_snapshot():
    """Capture la frame courante et la sauvegarde."""
    global _latest_frame
    frame = _latest_frame
    if frame is None:
        return jsonify({"status": "error", "message": "Aucune frame disponible"}), 503
    ts       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"snap_{ts}.jpg"
    path     = os.path.join(SNAPSHOTS_DIR, filename)
    try:
        cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        # Nettoyer si > MAX_SNAPSHOTS
        files = sorted(Path(SNAPSHOTS_DIR).glob('snap_*.jpg'))
        for old in files[:-MAX_SNAPSHOTS]:
            old.unlink(missing_ok=True)
        log.info(f"[SNAPSHOT] Sauvegardé : {filename}")
        return jsonify({"status": "ok", "filename": filename})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/snapshots')
@api_auth
def list_snapshots():
    """Retourne la liste des snapshots (10 plus récents)."""
    files = sorted(Path(SNAPSHOTS_DIR).glob('snap_*.jpg'), reverse=True)
    names = [f.name for f in files[:10]]
    return jsonify({"snapshots": names})

@app.route('/snapshots/<filename>')
@api_auth
def get_snapshot(filename):
    """Sert un fichier snapshot."""
    safe = os.path.basename(filename)
    path = os.path.join(SNAPSHOTS_DIR, safe)
    if not os.path.exists(path):
        return ('', 404)
    from flask import send_file
    return send_file(path, mimetype='image/jpeg')

@app.route('/snapshots/<filename>', methods=['DELETE'])
@api_auth
def delete_snapshot(filename):
    safe = os.path.basename(filename)
    path = Path(SNAPSHOTS_DIR) / safe
    try:
        path.unlink(missing_ok=True)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Reconnaissance faciale : API ──────────────
@app.route('/faces/toggle', methods=['POST'])
@api_auth
def toggle_face_recognition():
    global FACE_RECOGNITION_ENABLED
    data = request.get_json(silent=True) or {}
    FACE_RECOGNITION_ENABLED = bool(data.get('active', not FACE_RECOGNITION_ENABLED))
    log.info(f"[FACE] Reconnaissance {'activée' if FACE_RECOGNITION_ENABLED else 'désactivée'}")
    return jsonify({"status": "ok", "active": FACE_RECOGNITION_ENABLED})

@app.route('/faces/status')
@api_auth
def face_status():
    return jsonify({
        "active": FACE_RECOGNITION_ENABLED,
        "model_ready": _face_recognizer is not None,
        "people": sorted(_face_labels.values()) if _face_labels else []
    })

@app.route('/faces/people')
@api_auth
def list_face_people():
    """Liste les personnes enregistrées avec leur nombre de photos."""
    result = []
    if os.path.isdir(FACES_RAW_DIR):
        for person in sorted(os.listdir(FACES_RAW_DIR)):
            person_dir = os.path.join(FACES_RAW_DIR, person)
            if os.path.isdir(person_dir):
                n = len([f for f in os.listdir(person_dir)
                         if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
                result.append({"name": person, "photos": n})
    return jsonify({"people": result})

@app.route('/faces/add', methods=['POST'])
@api_auth
def add_face_photo():
    """
    POST multipart/form-data : name=<nom>, file=<image>
    Ajoute une photo à la collection d'une personne (créée si besoin).
    """
    name = request.form.get('name', '').strip()
    if not name or not re.match(r'^[\w\-éèêàâîïôûç ]{1,40}$', name, re.IGNORECASE):
        return jsonify({"status": "error", "message": "Nom invalide (lettres, chiffres, espaces, tirets)"}), 400
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "Fichier manquant"}), 400
    file = request.files['file']
    safe_name = name.strip()
    person_dir = os.path.join(FACES_RAW_DIR, safe_name)
    os.makedirs(person_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    ext = os.path.splitext(file.filename)[1].lower() or '.jpg'
    if ext not in ('.jpg', '.jpeg', '.png'):
        ext = '.jpg'
    dest = os.path.join(person_dir, f"{ts}{ext}")
    file.save(dest)
    log.info(f"[FACE] Photo ajoutée pour '{safe_name}'")
    return jsonify({"status": "ok", "name": safe_name})

@app.route('/faces/train', methods=['POST'])
@api_auth
def retrain_faces():
    """Relance l'entraînement du modèle à partir des photos actuelles."""
    ok = train_face_model()
    if ok:
        return jsonify({"status": "ok", "people": list(_face_labels.values())})
    return jsonify({"status": "error", "message": "Échec entraînement (vérifier les photos)"}), 500

@app.route('/faces/person/<name>', methods=['DELETE'])
@api_auth
def delete_face_person(name):
    """Supprime une personne (toutes ses photos) puis ré-entraîne."""
    safe = os.path.basename(name)
    person_dir = os.path.join(FACES_RAW_DIR, safe)
    if not os.path.isdir(person_dir):
        return jsonify({"status": "error", "message": "Personne introuvable"}), 404
    import shutil
    shutil.rmtree(person_dir, ignore_errors=True)
    train_face_model()
    log.info(f"[FACE] Personne '{safe}' supprimée")
    return jsonify({"status": "ok"})

@app.route('/faces/recent')
@api_auth
def recent_recognitions():
    return jsonify({"recognitions": _last_recognitions})


# ── Interphone : client → haut-parleurs serveur ──────────
import io as _io

_interphone_active  = False   # toggle global
_interphone_volume  = 0.8     # 0.0 – 1.0
_interphone_lock    = threading.Lock()
_interphone_channel = None    # pygame.mixer.Channel dédié

def _get_interphone_channel():
    """Canal pygame réservé à l'interphone (index 1)."""
    global _interphone_channel
    if _interphone_channel is None:
        pygame.mixer.set_num_channels(max(8, pygame.mixer.get_num_channels()))
        _interphone_channel = pygame.mixer.Channel(1)
    return _interphone_channel

@app.route('/interphone/toggle', methods=['POST'])
@api_auth
def interphone_toggle():
    global _interphone_active
    data = request.get_json(silent=True) or {}
    _interphone_active = bool(data.get('active', not _interphone_active))
    if not _interphone_active:
        try: _get_interphone_channel().stop()
        except Exception: pass
    log.info(f"[INTERPHONE] {'Activé' if _interphone_active else 'Désactivé'}")
    return jsonify({"status": "ok", "active": _interphone_active})

@app.route('/interphone/status')
@api_auth
def interphone_status():
    return jsonify({"active": _interphone_active, "volume": _interphone_volume})

@app.route('/interphone/volume', methods=['POST'])
@api_auth
def interphone_set_volume():
    global _interphone_volume
    data = request.get_json(silent=True) or {}
    vol  = max(0.0, min(1.0, float(data.get('volume', _interphone_volume))))
    _interphone_volume = vol
    try: _get_interphone_channel().set_volume(vol)
    except Exception: pass
    return jsonify({"status": "ok", "volume": vol})

@app.route('/interphone/stream', methods=['POST'])
@api_auth
def interphone_stream():
    """
    Reçoit un chunk audio brut (PCM16 mono, 16000 Hz) depuis le navigateur client
    et le joue immédiatement sur les haut-parleurs du serveur.
    """
    if not _interphone_active:
        return jsonify({"status": "off"}), 200
    data = request.data
    if not data:
        return ('', 204)
    try:
        with _interphone_lock:
            # pygame.mixer attend du PCM signé 16-bit
            # On crée un Sound depuis les bytes bruts
            sound = pygame.sndarray.make_sound(
                np.frombuffer(data, dtype=np.int16).reshape(-1, 1)
                if pygame.mixer.get_init()[2] == 1
                else np.column_stack([
                    np.frombuffer(data, dtype=np.int16),
                    np.frombuffer(data, dtype=np.int16)
                ])
            )
            ch = _get_interphone_channel()
            ch.set_volume(_interphone_volume)
            ch.queue(sound)
    except Exception as e:
        log.debug(f"[INTERPHONE] Erreur lecture chunk: {e}")
    return ('', 204)


# ── MP3 : stop ────────────────────────────────
@app.route('/stop_audio', methods=['POST'])
@api_auth
def stop_audio():
    """Arrête la lecture audio en cours (y compris boucles repeat)."""
    try:
        pygame.mixer.music.stop()
        print("[AUDIO] Lecture arrêtée")
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500



# ── MP3 : supprimer ──────────────────────────
@app.route('/delete_mp3', methods=['POST'])
@api_auth
def delete_mp3():
    data = request.get_json(silent=True) or {}
    filename = data.get('filename', '').strip()
    if not filename:
        return jsonify({"status": "error", "message": "Nom manquant"}), 400
    path = os.path.join(MP3_DIR, os.path.basename(filename))
    if not os.path.exists(path):
        return jsonify({"status": "error", "message": "Fichier introuvable"}), 404
    try:
        # Arrêter la lecture avant de supprimer (libère le verrou sur le fichier)
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
            time.sleep(0.1)
        except Exception:
            pass
        os.remove(path)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── MP3 : renommer ────────────────────────────
@app.route('/rename_mp3', methods=['POST'])
@api_auth
def rename_mp3():
    data = request.get_json(silent=True) or {}
    old_name = data.get('old_name', '').strip()
    new_name = data.get('new_name', '').strip()
    if not old_name or not new_name:
        return jsonify({"status": "error", "message": "Noms manquants"}), 400
    old_path = os.path.join(MP3_DIR, os.path.basename(old_name))
    new_path = os.path.join(MP3_DIR, os.path.basename(new_name))
    if not os.path.exists(old_path):
        return jsonify({"status": "error", "message": "Fichier introuvable"}), 404
    if os.path.exists(new_path) and old_name != new_name:
        return jsonify({"status": "error", "message": "Ce nom existe deja"}), 409
    try:
        os.rename(old_path, new_path)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── MP3 : libellés ────────────────────────────
_MP3_LABELS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mp3_labels.json')

def _load_mp3_labels():
    try:
        if os.path.exists(_MP3_LABELS_FILE):
            with open(_MP3_LABELS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_mp3_labels(d):
    try:
        with open(_MP3_LABELS_FILE, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"[AUDIO] Sauvegarde libelles : {e}")

@app.route('/mp3_labels', methods=['GET'])
def get_mp3_labels():
    return jsonify({"labels": _load_mp3_labels()})

@app.route('/mp3_labels', methods=['POST'])
def set_mp3_label():
    data = request.get_json(silent=True) or {}
    fname = data.get('filename', '').strip()
    label = data.get('label', '').strip()
    if not fname:
        return jsonify({"status": "error", "message": "Nom manquant"}), 400
    labels = _load_mp3_labels()
    if label:
        labels[fname] = label
    else:
        labels.pop(fname, None)
    _save_mp3_labels(labels)
    return jsonify({"status": "ok", "labels": labels})


# ── MP3 : ordre ───────────────────────────────
_MP3_ORDER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mp3_order.json')

def _load_mp3_order():
    try:
        if os.path.exists(_MP3_ORDER_FILE):
            with open(_MP3_ORDER_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return []

def _save_mp3_order(order):
    try:
        with open(_MP3_ORDER_FILE, 'w', encoding='utf-8') as f:
            json.dump(order, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"[AUDIO] Sauvegarde ordre : {e}")

@app.route('/mp3_order', methods=['POST'])
def set_mp3_order():
    data = request.get_json(silent=True) or {}
    _save_mp3_order(data.get('order', []))
    return jsonify({"status": "ok"})


# ── Timer VGT ─────────────────────────────────
import pytz as _pytz

_TIMER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'timer_schedule.json')
_TIMER_DEFAULT = [
    {"time": "14:00", "file": "start.mp3"},
    {"time": "14:45", "file": "45.mp3"},
    {"time": "14:50", "file": "50.mp3"},
    {"time": "14:55", "file": "55.mp3"},
    {"time": "14:58", "file": "58.mp3"},
    {"time": "15:45", "file": "45.mp3"},
    {"time": "15:50", "file": "50.mp3"},
    {"time": "15:55", "file": "55.mp3"},
    {"time": "15:58", "file": "58.mp3"},
    {"time": "16:45", "file": "45.mp3"},
    {"time": "16:50", "file": "50.mp3"},
    {"time": "16:55", "file": "55.mp3"},
    {"time": "16:58", "file": "58.mp3"},
    {"time": "17:45", "file": "45.mp3"},
    {"time": "17:50", "file": "50.mp3"},
    {"time": "17:55", "file": "55.mp3"},
    {"time": "17:58", "file": "end.mp3"},
]
_timer_enabled  = False
_timer_fired    = set()
_timer_lock     = threading.Lock()
_timer_log      = []

def _load_timer_schedule():
    try:
        if os.path.exists(_TIMER_FILE):
            with open(_TIMER_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return list(_TIMER_DEFAULT)

def _save_timer_schedule(s):
    try:
        with open(_TIMER_FILE, 'w', encoding='utf-8') as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"[TIMER] {e}")

def _timer_loop():
    global _timer_fired
    paris = _pytz.timezone('Europe/Paris')
    last_day = None
    while True:
        try:
            now   = datetime.datetime.now(paris)
            today = now.strftime("%Y-%m-%d")
            hm    = now.strftime("%H:%M")
            if last_day != today:
                _timer_fired = set()
                last_day = today
            with _timer_lock:
                enabled = _timer_enabled
            if enabled:
                for entry in _load_timer_schedule():
                    t = entry.get('time', '')
                    f = entry.get('file', '')
                    if t == hm and t not in _timer_fired:
                        path = os.path.join(TIMER_DIR, os.path.basename(f))
                        if os.path.exists(path):
                            log.info(f"[TIMER] {t} -> {f}")
                            play_mp3_file(path)
                        else:
                            log.warning(f"[TIMER] Fichier introuvable : {f}")
                        _timer_fired.add(t)
                        _timer_log.append({"time": t, "file": f, "ts": now.strftime("%H:%M:%S")})
                        if len(_timer_log) > 100:
                            _timer_log.pop(0)
        except Exception as e:
            log.error(f"[TIMER] Boucle : {e}")
        time.sleep(15)

threading.Thread(target=_timer_loop, daemon=True).start()

@app.route('/timer/status')
def timer_status():
    return jsonify({
        "enabled": _timer_enabled,
        "schedule": _load_timer_schedule(),
        "log": _timer_log[-20:],
        "fired": list(_timer_fired),
    })

@app.route('/timer/toggle', methods=['POST'])
def timer_toggle():
    global _timer_enabled
    with _timer_lock:
        _timer_enabled = not _timer_enabled
    log.info(f"[TIMER] {'Active' if _timer_enabled else 'Desactive'}")
    return jsonify({"status": "ok", "enabled": _timer_enabled})

@app.route('/timer/schedule', methods=['POST'])
def timer_set_schedule():
    data = request.get_json(silent=True) or {}
    _save_timer_schedule(data.get('schedule', []))
    return jsonify({"status": "ok"})

@app.route('/timer/reset', methods=['POST'])
def timer_reset_route():
    _save_timer_schedule(list(_TIMER_DEFAULT))
    return jsonify({"status": "ok", "schedule": _TIMER_DEFAULT})

@app.route('/timer/fired_reset', methods=['POST'])
def timer_fired_reset():
    global _timer_fired
    _timer_fired = set()
    return jsonify({"status": "ok"})


# ── Captures mouvement ───────────────────────
@app.route('/set_captures', methods=['POST'])
def set_captures():
    global SAVE_CAPTURES
    data = request.get_json(silent=True) or {}
    SAVE_CAPTURES = bool(data.get('enabled', False))
    log.info(f"[CAPTURE] Sauvegarde {'activée' if SAVE_CAPTURES else 'désactivée'}")
    return jsonify({"status": "ok", "enabled": SAVE_CAPTURES})

@app.route('/get_captures')
def get_captures():
    return jsonify({"enabled": SAVE_CAPTURES})


# ── Qualité vidéo ────────────────────────────
@app.route('/set_quality', methods=['POST'])
@api_auth
def set_quality():
    global stream_quality
    data = request.get_json(silent=True) or {}
    q = data.get('quality', '').strip()
    if q not in QUALITY_PRESETS:
        return jsonify({"status": "error", "message": f"Valeur inconnue : {q}"}), 400
    stream_quality = q
    log.info(f"[STREAM] Qualité changée → {QUALITY_PRESETS[q]['label']}")
    return jsonify({"status": "ok", "quality": q, "label": QUALITY_PRESETS[q]["label"]})

@app.route('/get_quality')
def get_quality():
    return jsonify({"quality": stream_quality, "label": QUALITY_PRESETS[stream_quality]["label"]})


# ── Contrôle micro (start/stop à la demande) ─
@app.route('/mic_start', methods=['POST'])
@api_auth
def route_mic_start():
    ok = mic_start()
    return jsonify({"status": "ok" if ok else "error", "active": mic_active})

@app.route('/mic_stop', methods=['POST'])
@api_auth
def route_mic_stop():
    mic_stop()
    return jsonify({"status": "ok", "active": False})

@app.route('/ngrok_url')
def get_ngrok_url():
    # Route publique — l'URL ngrok n'est pas un secret
    return jsonify({"url": ngrok_public_url})


@app.route('/mic_status')
def route_mic_status():
    return jsonify({"active": mic_active})


# ── Flux audio SSE ────────────────────────────
@app.route('/audio_stream')
@api_auth
def audio_stream():
    """
    Server-Sent Events : envoie les trames PCM base64 aux clients web.
    Le navigateur décode et joue via Web Audio API.
    """
    q = queue.Queue(maxsize=60)
    with audio_clients_lock:
        audio_clients.append(q)

    @stream_with_context
    def generate():
        cfg = json.dumps({"sampleRate": AUDIO_SAMPLERATE, "channels": AUDIO_CHANNELS})
        yield f"event: config\ndata: {cfg}\n\n"
        try:
            while True:
                try:
                    chunk = q.get(timeout=5)
                    yield chunk
                except queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            with audio_clients_lock:
                if q in audio_clients:
                    audio_clients.remove(q)

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache, no-store',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
            'Access-Control-Allow-Origin': '*',
        }
    )


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = ''
    if request.method == 'POST':
        pwd = request.form.get('password', '')
        if pwd == APP_PASSWORD:
            session['authenticated'] = True
            session.permanent = False
            return redirect(url_for('index'))
        error = 'Mot de passe incorrect'
    # Page de login minimaliste, thème sombre cohérent
    return f'''<!DOCTYPE html><html lang="fr"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JVO — Connexion</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0f0f17;display:flex;align-items:center;justify-content:center;
       min-height:100vh;font-family:system-ui,sans-serif}}
  .box{{background:#1a1a2e;border:1px solid #2a2a3e;border-radius:14px;
        padding:40px 36px;width:320px;display:flex;flex-direction:column;gap:16px}}
  h1{{color:#e0e0f0;font-size:1.1rem;text-align:center;letter-spacing:.05em}}
  .dot{{width:10px;height:10px;border-radius:50%;background:#e35b5b;
        box-shadow:0 0 8px #e35b5b;margin:0 auto 4px}}
  input[type=password]{{background:#111;border:1px solid #2a2a3e;border-radius:8px;
    color:#e0e0f0;padding:11px 13px;font-size:.95rem;width:100%;outline:none;
    transition:border .2s}}
  input[type=password]:focus{{border-color:#4f8ef7}}
  button{{background:#4f8ef7;border:none;border-radius:8px;color:#fff;
          padding:11px;font-size:.95rem;cursor:pointer;transition:background .2s}}
  button:hover{{background:#3a7ae0}}
  .err{{color:#e35b5b;font-size:.82rem;text-align:center}}
</style></head><body>
<form class="box" method="POST">
  <div class="dot"></div>
  <h1>SALLE JVO</h1>
  <input type="password" name="password" placeholder="Mot de passe" autofocus>
  {"<div class='err'>" + error + "</div>" if error else ""}
  <button type="submit">Connexion</button>
</form></body></html>'''

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    ip = get_local_ip()
    return f'''<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Salle JVO \u2013 Contr\u00f4le</title>
<style>
:root {{
  --bg:#0d0d0d; --surface:#1a1a1a; --border:#2e2e2e;
  --accent:#4f8ef7; --accent2:#3ecf8e; --red:#e35b5b;
  --text:#e8e8e8; --muted:#888;
}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:var(--bg);color:var(--text);font-family:'Segoe UI',Arial,sans-serif;min-height:100vh}}
header{{background:var(--surface);border-bottom:1px solid var(--border);
        padding:12px 24px;display:flex;align-items:center;gap:10px}}
@media (max-width: 960px) {{
  header{{padding:8px 14px}}
  h1{{font-size:.92rem}}
}}
h1{{font-size:1.05rem;font-weight:600;letter-spacing:.04em}}
.dot{{width:8px;height:8px;border-radius:50%;background:var(--accent2);
      box-shadow:0 0 6px var(--accent2);animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
.layout{{display:grid;grid-template-columns:1fr 390px;height:calc(100vh - 49px)}}
@media (orientation: portrait), (max-width: 960px) {{
  .layout{{grid-template-columns:1fr;grid-template-rows:40vh 1fr;height:calc(100vh - 49px)}}
  .video-panel{{min-height:0}}
  .ctrl-panel{{border-left:none;border-top:1px solid var(--border)}}
}}
.video-panel{{background:#000;display:flex;align-items:center;justify-content:center;
              overflow:hidden;position:relative;min-height:0}}
.video-panel img{{width:100%;height:100%;object-fit:contain}}

.ctrl-panel{{background:var(--surface);border-left:1px solid var(--border);
             display:flex;flex-direction:column;overflow:hidden;height:100%}}
.tabs{{display:flex;border-bottom:1px solid var(--border);flex-shrink:0}}
.tab{{flex:1;padding:9px 1px;font-size:.71rem;text-align:center;cursor:pointer;
      color:var(--muted);border-bottom:2px solid transparent;
      transition:color .15s,border-color .15s;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
@media (max-width: 480px) {{
  .tab{{font-size:.65rem;padding:8px 1px}}
}}
.tab.active{{color:var(--accent);border-bottom-color:var(--accent)}}
.tab-content{{display:none;flex-direction:column;gap:13px;overflow-y:auto;padding:13px;flex:1;
              scrollbar-width:thin;scrollbar-color:var(--border) transparent}}
.tab-content.active{{display:flex}}
.card{{background:var(--bg);border:1px solid var(--border);border-radius:9px;padding:12px}}
.card h2{{font-size:.73rem;text-transform:uppercase;letter-spacing:.1em;
          color:var(--muted);margin-bottom:9px;display:flex;align-items:center;gap:5px}}
textarea,input[type=text]{{width:100%;background:#111;border:1px solid var(--border);
  border-radius:6px;color:var(--text);padding:8px;font-size:.86rem;resize:vertical;
  outline:none;transition:border .2s}}
textarea:focus,input[type=text]:focus{{border-color:var(--accent)}}
.btn{{display:inline-flex;align-items:center;justify-content:center;gap:4px;
      padding:6px 12px;border:none;border-radius:6px;font-size:.82rem;
      cursor:pointer;font-weight:600;transition:opacity .15s,transform .1s;white-space:nowrap}}
.btn:active{{transform:scale(.97)}}
.btn:disabled{{opacity:.4;cursor:not-allowed}}
.btn-primary{{background:var(--accent);color:#fff}}
.btn-success{{background:var(--accent2);color:#000}}
.btn-danger{{background:var(--red);color:#fff}}
.btn-ghost{{background:var(--border);color:var(--text)}}
.btn-row{{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}}
select{{width:100%;background:#111;border:1px solid var(--border);border-radius:6px;
        color:var(--text);padding:7px 8px;font-size:.82rem;outline:none;
        cursor:pointer;transition:border .2s;margin-bottom:7px}}
select:focus{{border-color:var(--accent)}}
.quick-btns{{display:flex;flex-direction:column;gap:4px}}
.quick-item{{display:flex;align-items:center;gap:5px;
  border-radius:6px;transition:background .15s;user-select:none;cursor:grab}}
.quick-item:active{{cursor:grabbing}}
.quick-item.dragging{{opacity:.35}}
.quick-item.drag-over-phrase{{outline:2px dashed var(--accent2);outline-offset:1px;border-radius:6px}}
.quick-btn{{flex:1;background:#111;border:1px solid var(--border);border-radius:6px;
            color:var(--text);padding:6px 8px;font-size:.79rem;cursor:pointer;
            text-align:left;transition:border .2s,background .2s;
            white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.quick-btn:hover{{border-color:var(--accent);background:#1a1a2e}}
.quick-del{{background:none;border:none;color:var(--muted);cursor:pointer;font-size:.87rem;padding:2px 4px}}
.quick-del:hover{{color:var(--red)}}
#mp3List{{list-style:none;display:flex;flex-direction:column;gap:4px}}
.mp3-item{{background:#111;border:1px solid var(--border);border-radius:7px;padding:7px 8px}}
.mp3-item.drag-over{{border-color:var(--accent2);background:#0d1f0d}}
.mp3-row1{{display:flex;align-items:center;gap:6px}}
.mp3-handle{{color:var(--muted);font-size:.95rem;cursor:grab;user-select:none;flex-shrink:0}}
.mp3-label{{flex:1;font-size:.79rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.mp3-alias{{font-size:.71rem;color:var(--muted);margin-top:1px}}
.mp3-actions{{display:flex;gap:4px;margin-top:6px}}
.mp3-actions button{{font-size:.71rem;padding:3px 7px}}
.snap-gallery{{display:grid;grid-template-columns:repeat(auto-fill,minmax(72px,1fr));
              gap:6px;width:100%}}
.snap-thumb{{position:relative;aspect-ratio:4/3;border-radius:6px;overflow:hidden;
             cursor:pointer;border:1px solid var(--border);background:#000}}
.snap-thumb img{{width:100%;height:100%;object-fit:cover;display:block}}
.snap-del{{position:absolute;top:2px;right:2px;background:rgba(0,0,0,.65);
           border:none;color:#fff;border-radius:4px;font-size:.65rem;
           padding:1px 5px;cursor:pointer;line-height:1.5;opacity:0;
           transition:opacity .15s}}
.snap-thumb:hover .snap-del{{opacity:1}}
.snap-thumb:hover img{{opacity:.8}}

.upload-area{{border:2px dashed var(--border);border-radius:8px;padding:10px;
              text-align:center;cursor:pointer;font-size:.79rem;
              color:var(--muted);transition:border .2s}}
.upload-area:hover{{border-color:var(--accent);color:var(--text)}}
input[type=file]{{display:none}}
.timer-header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:9px}}
.timer-clock{{font-size:1.4rem;font-weight:700;font-family:monospace;color:var(--accent2)}}
.toggle-pill{{width:40px;height:22px;border-radius:11px;background:#333;
              position:relative;cursor:pointer;transition:background .2s;flex-shrink:0}}
.toggle-pill.on{{background:var(--accent2)}}
.toggle-pill::after{{content:'';width:16px;height:16px;border-radius:50%;background:#fff;
  position:absolute;top:3px;left:3px;transition:left .2s}}
.toggle-pill.on::after{{left:21px}}
.timer-tbl{{width:100%;border-collapse:collapse;font-size:.77rem}}
.timer-tbl th{{color:var(--muted);text-align:left;padding:3px 4px;
               border-bottom:1px solid var(--border);font-weight:500}}
.timer-tbl td{{padding:4px 4px;border-bottom:1px solid #1a1a1a}}
.timer-tbl tr:last-child td{{border-bottom:none}}
.timer-tbl input{{background:#111;border:1px solid var(--border);border-radius:4px;
                  color:var(--text);padding:2px 5px;font-size:.74rem;width:100%;outline:none}}
.timer-tbl input:focus{{border-color:var(--accent)}}
.tdel{{background:none;border:none;color:var(--muted);cursor:pointer;font-size:.8rem;padding:0 3px}}
.tdel:hover{{color:var(--red)}}
.timer-badge{{display:inline-block;padding:1px 7px;border-radius:9px;font-size:.69rem;font-weight:700;margin-left:5px}}
.timer-badge.on{{background:#1a2e1a;color:var(--accent2);border:1px solid var(--accent2)}}
.timer-badge.off{{background:#2e1a1a;color:var(--red);border:1px solid var(--red)}}
.timer-log{{max-height:85px;overflow-y:auto;font-size:.71rem;color:var(--muted);
            font-family:monospace;margin-top:4px;
            scrollbar-width:thin;scrollbar-color:var(--border) transparent}}
/* ── Tags MP3 ── */
.tag-group{{border:1px solid var(--border);border-radius:8px;overflow:hidden;margin-bottom:4px}}
.tag-header{{display:flex;align-items:center;justify-content:space-between;
             padding:7px 10px;cursor:pointer;background:#111;
             transition:background .15s;user-select:none}}
.tag-header:hover{{background:#181828}}
.tag-name{{font-size:.8rem;font-weight:600;color:var(--accent);display:flex;align-items:center;gap:6px}}
.tag-count{{font-size:.7rem;color:var(--muted);font-weight:400}}
.tag-chevron{{font-size:.65rem;color:var(--muted);transition:transform .2s}}
.tag-chevron.open{{transform:rotate(90deg)}}
.tag-body{{display:none;flex-direction:column;gap:3px;padding:6px 8px;background:#0d0d0d}}
.tag-body.open{{display:flex}}
.mp3-row{{display:flex;align-items:center;gap:5px;padding:4px 6px;
          border-radius:6px;transition:background .15s}}
.mp3-row:hover{{background:#1a1a1a}}
.mp3-name-lbl{{flex:1;font-size:.79rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.mp3-alias-lbl{{font-size:.69rem;color:var(--muted)}}
/* ── Collapse ── */
.card-collapsible .card-body{{overflow:hidden;transition:max-height .25s ease}}
.card-collapsible.collapsed .card-body{{max-height:0!important}}
.card-title-row{{display:flex;align-items:center;justify-content:space-between;cursor:pointer;margin-bottom:0}}
.card-title-row h2{{margin-bottom:0;cursor:pointer}}
.collapse-btn{{background:none;border:none;color:var(--muted);font-size:.9rem;cursor:pointer;
               padding:0 2px;line-height:1;transition:transform .2s;flex-shrink:0}}
.card-collapsible:not(.collapsed) .collapse-btn{{transform:rotate(0deg)}}
.card-collapsible.collapsed .collapse-btn{{transform:rotate(-90deg)}}
.card-collapsible:not(.collapsed) .card-body{{margin-top:9px}}
/* ── Bibliothèque audio plein panneau ── */
#audioLibFull{{display:flex;flex-direction:column;height:100%;overflow:hidden}}
#audioLibFull .lib-top{{flex-shrink:0;padding:10px 13px 6px;border-bottom:1px solid var(--border);
                        display:flex;gap:6px;align-items:center}}
#audioLibFull .lib-search{{flex:1;background:#111;border:1px solid var(--border);border-radius:6px;
                           color:var(--text);padding:6px 9px;font-size:.82rem;outline:none}}
#audioLibFull .lib-search:focus{{border-color:var(--accent)}}
#audioLibFull .lib-scroll{{flex:1;overflow-y:auto;padding:8px 13px;
                           scrollbar-width:thin;scrollbar-color:var(--border) transparent}}
#stopBar{{flex-shrink:0;padding:8px 13px;border-top:1px solid var(--border);
          display:flex;gap:6px;align-items:center;background:var(--surface)}}
#nowPlaying{{flex:1;font-size:.75rem;color:var(--muted);overflow:hidden;
             text-overflow:ellipsis;white-space:nowrap}}
.modal-bg{{display:none;position:fixed;inset:0;z-index:500;background:rgba(0,0,0,.75);
           align-items:center;justify-content:center}}
.modal-bg.open{{display:flex}}
.modal-box{{background:var(--surface);border:1px solid var(--border);border-radius:10px;
            padding:20px;width:320px;max-width:92vw}}
.modal-box h3{{font-size:.86rem;margin-bottom:12px}}
.modal-box input{{margin-bottom:9px}}
.modal-btns{{display:flex;gap:7px;justify-content:flex-end}}
#toast{{position:fixed;bottom:16px;right:16px;z-index:999;background:#222;
        border:1px solid var(--border);border-radius:8px;padding:8px 15px;
        font-size:.82rem;opacity:0;pointer-events:none;transition:opacity .3s;max-width:270px}}
#toast.show{{opacity:1}}
#toast.ok{{border-color:var(--accent2);color:var(--accent2)}}
#toast.err{{border-color:var(--red);color:var(--red)}}
</style>
</head>
<body>
<header>
  <div class="dot"></div>
  <h1>SALLE JVO &ndash; Surveillance &amp; Diffusion</h1>
</header>

<div class="layout">
  <div class="video-panel">
    <img id="videoFeed" src="/video_feed" alt="Flux vid&eacute;o">
  </div>
  <div class="ctrl-panel">
    <div class="tabs">
      <div class="tab active" id="tab-tts"    onclick="switchTab('tts')">&#128266; TTS</div>
      <div class="tab"        id="tab-mp3"    onclick="switchTab('mp3')">&#127925; MP3</div>
      <div class="tab"        id="tab-timer"  onclick="switchTab('timer')">&#9201; Timer</div>
      <div class="tab"        id="tab-cam"    onclick="switchTab('cam')">&#128247; Cam</div>
      <div class="tab"        id="tab-faces"  onclick="switchTab('faces')">&#128100; Visages</div>
      <div class="tab"        id="tab-listen" onclick="switchTab('listen')">&#127911; &Eacute;coute</div>
    </div>

    <!-- onglet TTS -->
    <div class="tab-content active" id="pane-tts">
      <div class="card">
        <h2>Voix</h2>
        <select id="voiceSelect" onchange="setVoice(this.value)"><option>Chargement&hellip;</option></select>
      </div>
      <div class="card">
        <h2>Message libre</h2>
        <textarea id="ttsText" rows="3" placeholder="Tapez votre message&hellip;"></textarea>
        <div class="btn-row">
          <button class="btn btn-primary" onclick="sendTTS()">&#9654; Lire</button>
          <button class="btn btn-ghost" onclick="document.getElementById('ttsText').value=''">Effacer</button>
        </div>
      </div>
      <div class="card">
        <h2>Phrases rapides</h2>
        <div class="quick-btns" id="quickBtns"></div>
        <div style="display:flex;gap:5px;margin-top:8px">
          <input type="text" id="newPhrase" placeholder="Nouvelle phrase&hellip;"
                 style="flex:1;padding:5px 8px;font-size:.79rem"
                 onkeydown="if(event.key==='Enter')addPhrase()">
          <button class="btn btn-success" onclick="addPhrase()" style="padding:5px 10px">+</button>
        </div>
      </div>
    </div>

    <!-- onglet MP3 -->
    <div class="tab-content" id="pane-mp3" style="padding:0;gap:0;overflow:hidden;height:100%">
      <!-- Upload -->
      <div class="card" id="uploadCard"
           style="border-radius:0;border-left:none;border-right:none;border-top:none;flex-shrink:0">
        <h2 style="margin-bottom:8px">&#128194; Ajouter un fichier</h2>
        <label class="upload-area" for="mp3Input" id="dropZone">
          Cliquez ou d&eacute;posez MP3 / WAV / OGG
        </label>
        <input type="file" id="mp3Input" accept=".mp3,.wav,.ogg" onchange="uploadMP3(this.files[0])">
      </div>
      <!-- Bibliothèque plein panneau avec tags -->
      <!-- Volume -->
      <div style="display:flex;align-items:center;gap:8px;padding:8px 12px;
                  background:var(--surface);border-bottom:1px solid var(--border);flex-shrink:0">
        <span style="font-size:.72rem;color:var(--muted);white-space:nowrap">&#128266;</span>
        <input type="range" id="volumeSlider" min="0" max="100" value="80" step="1"
               style="flex:1;accent-color:var(--accent)" oninput="onVolumeChange(this.value)">
        <span id="volumeLabel" style="font-size:.72rem;color:var(--muted);width:30px;text-align:right">80%</span>
      </div>
      <div id="audioLibFull">
        <div class="lib-top">
          <span style="font-size:.73rem;color:var(--muted);white-space:nowrap">&#127925; Biblioth&egrave;que</span>
          <input type="text" class="lib-search" id="mp3Search" placeholder="Rechercher&hellip;" oninput="filterTags()">
          <button class="btn btn-ghost" style="font-size:.7rem;padding:4px 7px" onclick="loadMP3List()" title="Actualiser">&#8635;</button>
          <button class="btn btn-ghost" style="font-size:.7rem;padding:4px 7px" onclick="toggleAllTags()" title="Tout ouvrir/fermer">&#9723;</button>
        </div>
        <div class="lib-scroll" id="tagContainer">
          <div style="color:var(--muted);font-size:.79rem;padding:12px 0">Chargement&hellip;</div>
        </div>
        <div id="stopBar">
          <span id="nowPlaying">Aucune lecture</span>
          <button class="btn btn-danger" style="font-size:.75rem;padding:5px 11px" onclick="stopAudio()">&#9632; Stop</button>
        </div>
      </div>
    </div>

    <!-- onglet Timer -->
    <div class="tab-content" id="pane-timer">
      <div class="card">
        <div class="timer-header">
          <div>
            <div class="timer-clock" id="timerClock">--:--:--</div>
            <div style="font-size:.71rem;color:var(--muted);margin-top:2px">
              Timer auto
              <span class="timer-badge off" id="timerBadge">OFF</span>
            </div>
          </div>
          <div class="toggle-pill" id="timerPill" onclick="timerToggle()"></div>
        </div>
        <div class="btn-row">
          <button class="btn btn-ghost" style="font-size:.71rem" onclick="timerFiredReset()">&#8635; R&eacute;armer</button>
          <button class="btn btn-ghost" style="font-size:.71rem" onclick="timerReset()">D&eacute;faut</button>
          <button class="btn btn-success" style="font-size:.71rem" onclick="timerAddRow()">+ Entr&eacute;e</button>
        </div>
      </div>
      <div class="card">
        <h2>Planning</h2>
        <table class="timer-tbl">
          <thead><tr><th>Heure</th><th>Fichier MP3</th><th></th></tr></thead>
          <tbody id="timerBody"></tbody>
        </table>
        <div class="btn-row" style="margin-top:8px">
          <button class="btn btn-primary" onclick="timerSave()">&#128190; Sauvegarder</button>
        </div>
      </div>
      <div class="card">
        <h2>Historique</h2>
        <div class="timer-log" id="timerLog"><span style="color:var(--muted)">Aucun rappel.</span></div>
      </div>
    </div>

    <!-- onglet Cam -->
    <div class="tab-content" id="pane-cam">
      <div class="card" id="ngrokCard" style="display:none">
        <div style="display:flex;align-items:center;gap:8px">
          <div style="width:8px;height:8px;border-radius:50%;background:#3ecf8e;
                      box-shadow:0 0 6px #3ecf8e;flex-shrink:0"></div>
          <span style="font-size:.73rem;color:var(--muted)">Accès externe :</span>
          <a id="ngrokLink" href="#" target="_blank"
             style="font-size:.75rem;color:#3ecf8e;word-break:break-all;text-decoration:none;font-weight:600"></a>
        </div>
      </div>
      <div class="card">
        <h2>Qualit&eacute; vid&eacute;o</h2>
        <div class="btn-row" id="qualityBtns">
          <button class="btn btn-ghost" id="q-hd" onclick="setQuality('hd')">HD</button>
          <button class="btn btn-success" id="q-medium" onclick="setQuality('medium')">Moyen</button>
          <button class="btn btn-ghost" id="q-low" onclick="setQuality('low')">&Eacute;co</button>
        </div>
        <div style="margin-top:6px;font-size:.73rem;color:var(--muted)" id="qualityLabel">640&times;360 &middot; ~4 Mbit/s</div>
      </div>
      <div class="card">
        <h2>Captures mouvement</h2>
        <div style="display:flex;align-items:center;justify-content:space-between">
          <span style="font-size:.79rem;color:var(--muted)" id="captureStatus">D&eacute;sactiv&eacute;es</span>
          <div class="toggle-pill" id="captureToggle" onclick="toggleCaptures()"></div>
        </div>
      </div>
      <!-- Snapshot -->
      <div class="card">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
          <h2 style="margin:0">&#128247; Snapshot</h2>
          <button class="btn btn-primary" style="padding:4px 10px;font-size:.78rem"
                  onclick="takeSnapshot()">Capturer</button>
        </div>
        <div id="snapshotGallery" class="snap-gallery"></div>
      </div>
      <!-- Mode absent -->
      <div class="card">
        <div style="display:flex;align-items:center;justify-content:space-between">
          <div>
            <h2 style="margin:0">&#128682; Mode absent</h2>
            <div style="font-size:.72rem;color:var(--muted);margin-top:2px">
              Snapshot + son sur mouvement d&eacute;tect&eacute;
            </div>
          </div>
          <div class="toggle-pill" id="absentToggle" onclick="toggleAbsent()"></div>
        </div>
        <div id="absentStatus" style="font-size:.73rem;color:var(--muted);margin-top:6px">D&eacute;sactiv&eacute;</div>
        <div style="font-size:.71rem;color:var(--muted);margin-top:4px">
          Son : <code>mp3_timer/absent.mp3</code> (facultatif)
        </div>
      </div>

    </div>

    <!-- onglet Visages -->
    <div class="tab-content" id="pane-faces">
      <div class="card">
        <div style="display:flex;align-items:center;justify-content:space-between">
          <div>
            <h2 style="margin:0">&#128100; Reconnaissance faciale</h2>
            <div style="font-size:.72rem;color:var(--muted);margin-top:2px" id="faceModelStatus">
              Mod&egrave;le non entra&icirc;n&eacute;
            </div>
          </div>
          <div class="toggle-pill" id="faceToggle" onclick="toggleFaceRecognition()"></div>
        </div>
        <div id="faceActiveStatus" style="font-size:.73rem;color:var(--muted);margin-top:6px">D&eacute;sactiv&eacute;e</div>
      </div>

      <div class="card">
        <h2>Ajouter une personne</h2>
        <input type="text" id="facePersonName" placeholder="Nom de la personne"
               style="margin-bottom:8px">
        <label class="upload-area" for="faceFileInput" id="faceDropZone">
          Cliquez ou d&eacute;posez 3-5 photos du visage
        </label>
        <input type="file" id="faceFileInput" accept=".jpg,.jpeg,.png" multiple
               onchange="uploadFacePhotos(this.files)">
        <div style="font-size:.71rem;color:var(--muted);margin-top:6px">
          Photos nettes, visage de face, bon &eacute;clairage recommand&eacute;es.
        </div>
      </div>

      <div class="card">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
          <h2 style="margin:0">Personnes enregistr&eacute;es</h2>
          <button class="btn btn-success" style="padding:4px 10px;font-size:.78rem"
                  onclick="retrainFaceModel()">&#128260; Entra&icirc;ner</button>
        </div>
        <div id="facePeopleList" style="display:flex;flex-direction:column;gap:6px"></div>
      </div>

      <div class="card">
        <h2>Derni&egrave;res identifications</h2>
        <div id="faceRecentList" style="font-size:.78rem;color:var(--muted)">Aucune</div>
      </div>
    </div>

    <!-- onglet Ecoute -->
    <div class="tab-content" id="pane-listen">
      <!-- Écoute micro salle (serveur → client) -->
      <div class="card">
        <h2>&#127911; &Eacute;coute micro en direct</h2>
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
          <div id="audioIndicator" style="width:8px;height:8px;border-radius:50%;background:#444;flex-shrink:0"></div>
          <span id="audioStatus" style="font-size:.79rem;color:var(--muted)">Non connect&eacute;</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:7px">
          <label style="font-size:.79rem;color:var(--muted);white-space:nowrap">Volume</label>
          <input type="range" id="listenVolume" min="0" max="2" step="0.05" value="1"
                 style="flex:1;accent-color:var(--accent)">
          <span id="volLabel" style="font-size:.73rem;color:var(--muted);width:34px;text-align:right">100%</span>
        </div>
        <div class="btn-row">
          <button class="btn btn-primary" id="btnListen" onclick="toggleListen()">&#127911; &Eacute;couter</button>
        </div>
      </div>

      <!-- Interphone : parler vers la salle (client → serveur) -->
      <div class="card">
        <h2>&#128226; Interphone</h2>
        <div style="font-size:.73rem;color:var(--muted);margin-bottom:10px">
          Votre micro &rarr; haut-parleurs de la salle
        </div>
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
          <div id="interphoneIndicator" style="width:8px;height:8px;border-radius:50%;background:#444;flex-shrink:0"></div>
          <span id="interphoneStatus" style="font-size:.79rem;color:var(--muted)">Inactif</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
          <label style="font-size:.79rem;color:var(--muted);white-space:nowrap">Volume salle</label>
          <input type="range" id="interphoneVolume" min="0" max="1" step="0.05" value="0.8"
                 style="flex:1;accent-color:var(--accent2)"
                 oninput="onInterphoneVolume(this.value)">
          <span id="interphoneVolLabel" style="font-size:.73rem;color:var(--muted);width:34px;text-align:right">80%</span>
        </div>
        <div class="btn-row">
          <button class="btn btn-success" id="btnInterphone" onclick="toggleInterphone()">
            &#127908; Parler
          </button>
        </div>
        <div style="font-size:.7rem;color:var(--muted);margin-top:8px">
          N&eacute;cessite l&rsquo;autorisation micro du navigateur.
        </div>
      </div>
    </div>

  </div>
</div>

<!-- Modal renommer -->
<div class="modal-bg" id="renameModal">
  <div class="modal-box">
    <h3>&#9998; Renommer / Lib&eacute;ll&eacute;</h3>
    <input type="text" id="renameOld" readonly style="color:var(--muted)">
    <input type="text" id="renameNew" placeholder="Nouveau nom de fichier&hellip;">
    <input type="text" id="renameAlias" placeholder="Lib&eacute;ll&eacute; affich&eacute; (optionnel)&hellip;">
    <div class="modal-btns">
      <button class="btn btn-ghost" onclick="renameClose()">Annuler</button>
      <button class="btn btn-primary" onclick="renameConfirm()">Valider</button>
    </div>
  </div>
</div>

<div id="toast"></div>
<script>
const SERVER = window.location.origin;  // s'adapte automatiquement : LAN ou URL ngrok
  const NGROK_URL = {__import__('json').dumps(ngrok_public_url)};

// Onglets
function switchTab(name) {{
  document.querySelectorAll('.tab').forEach(function(t) {{ t.classList.remove('active'); }});
  document.querySelectorAll('.tab-content').forEach(function(p) {{ p.classList.remove('active'); }});
  document.getElementById('tab-' + name).classList.add('active');
  document.getElementById('pane-' + name).classList.add('active');
  if (name === 'mp3')   loadMP3List();
loadSnapshots();
fetch(SERVER + '/absent_mode', {{credentials:'same-origin'}})
  .then(function(r) {{ return r.json(); }})
  .then(function(d) {{ _absentActive = d.absent || false; updateAbsentUI(); }})
  .catch(function() {{}});

// ── ngrok URL ─────────────────────────────────
// Afficher URL ngrok (injectée au chargement ou récupérée via fetch)
function showNgrokBar(url) {{
  if (!url) return;
  var card = document.getElementById('ngrokCard');
  var link = document.getElementById('ngrokLink');
  if (card) card.style.display = '';
  if (link) {{ link.href = url; link.textContent = url; }}
}}

if (NGROK_URL) {{
  showNgrokBar(NGROK_URL);
}} else {{
  // Fallback : poll toutes les 3s si ngrok n'était pas encore prêt au chargement
  (function pollNgrok(tries) {{
    fetch(SERVER + '/ngrok_url', {{credentials: 'same-origin'}})
      .then(function(r) {{ return r.json(); }})
      .then(function(d) {{
        if (d.url) {{ showNgrokBar(d.url); }}
        else if (tries < 10) {{ setTimeout(function() {{ pollNgrok(tries+1); }}, 3000); }}
      }}).catch(function() {{
        if (tries < 10) {{ setTimeout(function() {{ pollNgrok(tries+1); }}, 3000); }}
      }});
  }})(0);
}}


  if (name === 'timer') {{ startTimerClock(); loadTimerStatus(); }}
}}

// Toast
function toast(msg, type) {{
  var t = document.getElementById('toast');
  t.textContent = msg; t.className = 'show ' + (type || 'ok');
  clearTimeout(t._t); t._t = setTimeout(function() {{ t.className = ''; }}, 3000);
}}

// Flux video
var feed = document.getElementById('videoFeed');
feed.onerror = function() {{ feed.src = SERVER + '/video_feed?t=' + Date.now(); }};
setInterval(function() {{ feed.src = SERVER + '/video_feed?t=' + Date.now(); }}, 30000);

// PiP supprimé


// TTS
async function sendTTS() {{
  var text = document.getElementById('ttsText').value.trim();
  if (!text) {{ toast('Aucun texte saisi', 'err'); return; }}
  try {{
    var r = await fetch(SERVER + '/tts', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{text: text}})
    }});
    var d = await r.json();
    if (d.status === 'ok') toast('Message envoye');
    else toast('Erreur: ' + d.message, 'err');
  }} catch(e) {{ toast('Connexion impossible', 'err'); }}
}}
document.getElementById('ttsText').addEventListener('keydown', function(e) {{
  if (e.ctrlKey && e.key === 'Enter') sendTTS();
}});

async function loadVoices() {{
  try {{
    var r = await fetch(SERVER + '/voices');
    var d = await r.json();
    var sel = document.getElementById('voiceSelect');
    sel.innerHTML = '';
    d.voices.forEach(function(v) {{
      var o = document.createElement('option');
      o.value = v.id; o.textContent = v.label;
      if (v.id === d.current) o.selected = true;
      sel.appendChild(o);
    }});
  }} catch(e) {{ console.error('loadVoices', e); }}
}}
async function setVoice(id) {{
  if (!id) return;
  try {{
    var r = await fetch(SERVER + '/set_voice', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{voice: id}})
    }});
    var d = await r.json();
    if (d.status === 'ok') toast('Voix : ' + id.split('-').slice(2).join(' '));
    else toast('Erreur voix', 'err');
  }} catch(e) {{ toast('Connexion impossible', 'err'); }}
}}

// Phrases rapides avec drag & drop pour réordonner
var _dragSrcPhrase = null;

function buildQuickBtns(phrases) {{
  var wrap = document.getElementById('quickBtns');
  wrap.innerHTML = '';
  phrases.forEach(function(p) {{
    var row = document.createElement('div');
    row.className = 'quick-item';
    row.draggable = true;
    row.dataset.pid = p.id;

    // Poignée drag
    var handle = document.createElement('span');
    handle.textContent = '\u2630';
    handle.title = 'Glisser pour réordonner';
    handle.style.cssText = 'color:var(--muted);font-size:.75rem;cursor:grab;padding:0 2px;flex-shrink:0';

    var btn = document.createElement('button'); btn.className = 'quick-btn';
    btn.textContent = p.text; btn.title = p.text;
    btn.onclick = (function(txt) {{ return function() {{
      document.getElementById('ttsText').value = txt; sendTTS();
    }}; }})(p.text);

    var del = document.createElement('button');
    del.className = 'quick-del'; del.title = 'Supprimer'; del.textContent = '\u00d7';
    del.onclick = (function(pid) {{ return function() {{ deletePhrase(pid); }}; }})(p.id);

    // Drag events
    row.addEventListener('dragstart', function(e) {{
      _dragSrcPhrase = row;
      row.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
    }});
    row.addEventListener('dragend', function() {{
      row.classList.remove('dragging');
      wrap.querySelectorAll('.drag-over-phrase').forEach(function(el) {{
        el.classList.remove('drag-over-phrase');
      }});
    }});
    row.addEventListener('dragover', function(e) {{
      e.preventDefault(); e.dataTransfer.dropEffect = 'move';
      if (row !== _dragSrcPhrase) row.classList.add('drag-over-phrase');
    }});
    row.addEventListener('dragleave', function() {{
      row.classList.remove('drag-over-phrase');
    }});
    row.addEventListener('drop', function(e) {{
      e.preventDefault();
      row.classList.remove('drag-over-phrase');
      if (!_dragSrcPhrase || _dragSrcPhrase === row) return;
      // Réinsérer dans le DOM
      var items = Array.from(wrap.children);
      var srcIdx = items.indexOf(_dragSrcPhrase);
      var dstIdx = items.indexOf(row);
      if (srcIdx < dstIdx) {{ wrap.insertBefore(_dragSrcPhrase, row.nextSibling); }}
      else                  {{ wrap.insertBefore(_dragSrcPhrase, row); }}
      // Sauvegarder le nouvel ordre
      var newOrder = Array.from(wrap.children).map(function(el) {{
        return parseInt(el.dataset.pid, 10);
      }});
      savePhrasesOrder(newOrder);
    }});

    row.appendChild(handle); row.appendChild(btn); row.appendChild(del);
    wrap.appendChild(row);
  }});
}}

async function savePhrasesOrder(order) {{
  try {{
    var r = await fetch(SERVER + '/phrases/reorder', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{order: order}})
    }});
    var d = await r.json();
    if (d.status !== 'ok') toast('Erreur sauvegarde ordre', 'err');
  }} catch(e) {{ toast('Connexion impossible', 'err'); }}
}}
async function loadPhrases() {{
  try {{
    var r = await fetch(SERVER + '/phrases');
    var d = await r.json();
    buildQuickBtns(d.phrases);
  }} catch(e) {{ console.error('loadPhrases', e); }}
}}
async function addPhrase() {{
  var inp = document.getElementById('newPhrase');
  var text = inp.value.trim();
  if (!text) {{ toast('Phrase vide', 'err'); return; }}
  try {{
    var r = await fetch(SERVER + '/phrases', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{text: text}})
    }});
    var d = await r.json();
    if (d.status === 'ok') {{ inp.value = ''; buildQuickBtns(d.phrases); toast('Phrase ajoutee'); }}
    else toast('Erreur', 'err');
  }} catch(e) {{ toast('Connexion impossible', 'err'); }}
}}
async function deletePhrase(id) {{
  try {{
    var r = await fetch(SERVER + '/phrases/' + id, {{method: 'DELETE'}});
    var d = await r.json();
    if (d.status === 'ok') {{ buildQuickBtns(d.phrases); toast('Phrase supprimee'); }}
  }} catch(e) {{ toast('Connexion impossible', 'err'); }}
}}

// ── Volume ────────────────────────────────────
function onVolumeChange(val) {{
  document.getElementById('volumeLabel').textContent = val + '%';
  fetch(SERVER + '/set_volume', {{
    method: 'POST', credentials: 'same-origin',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{volume: val / 100}})
  }});
}}
// Appliquer volume au lancement
fetch(SERVER + '/set_volume', {{
  method: 'POST', credentials: 'same-origin',
  headers: {{'Content-Type': 'application/json'}},
  body: JSON.stringify({{volume: 0.8}})
}});



// ── Snapshots ──────────────────────────────────
async function takeSnapshot() {{
  try {{
    var r = await fetch(SERVER + '/snapshot', {{method:'POST',credentials:'same-origin'}});
    var d = await r.json();
    if (d.status === 'ok') {{ toast('📷 Snapshot sauvegardé'); loadSnapshots(); }}
    else toast('Erreur snapshot', 'err');
  }} catch(e) {{ toast('Connexion impossible', 'err'); }}
}}

async function loadSnapshots() {{
  try {{
    var r = await fetch(SERVER + '/snapshots', {{credentials:'same-origin'}});
    var d = await r.json();
    renderSnapshots(d.snapshots || []);
  }} catch(e) {{}}
}}

function renderSnapshots(names) {{
  var g = document.getElementById('snapshotGallery');
  if (!g) return;
  g.innerHTML = '';
  if (!names.length) {{
    g.innerHTML = '<span style="font-size:.72rem;color:var(--muted)">Aucun snapshot</span>';
    return;
  }}
  names.forEach(function(name) {{
    var wrap = document.createElement('div'); wrap.className = 'snap-thumb';
    var img  = document.createElement('img');
    img.src  = SERVER + '/snapshots/' + encodeURIComponent(name);
    img.alt  = name;
    img.onclick = function() {{ window.open(img.src, '_blank'); }};
    var del  = document.createElement('button'); del.className = 'snap-del';
    del.textContent = '✕'; del.title = 'Supprimer';
    del.onclick = function(e) {{
      e.stopPropagation();
      fetch(SERVER + '/snapshots/' + encodeURIComponent(name),
            {{method:'DELETE',credentials:'same-origin'}})
        .then(function() {{ loadSnapshots(); }});
    }};
    wrap.appendChild(img); wrap.appendChild(del); g.appendChild(wrap);
  }});
}}

// ── Mode absent ────────────────────────────────
var _absentActive = false;

async function toggleAbsent() {{
  _absentActive = !_absentActive;
  try {{
    var r = await fetch(SERVER + '/absent_mode', {{
      method: 'POST', credentials: 'same-origin',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{active: _absentActive}})
    }});
    var d = await r.json();
    _absentActive = d.absent;
    updateAbsentUI();
    toast(_absentActive ? '🔴 Mode absent activé' : '⚫ Mode absent désactivé');
  }} catch(e) {{ toast('Connexion impossible', 'err'); _absentActive = !_absentActive; }}
}}

function updateAbsentUI() {{
  var tog = document.getElementById('absentToggle');
  var lbl = document.getElementById('absentStatus');
  if (!tog) return;
  if (_absentActive) {{
    tog.classList.add('on');
    lbl.textContent = '🔴 Actif — snapshot + son à chaque mouvement (cooldown 60 s)';
    lbl.style.color = 'var(--red)';
  }} else {{
    tog.classList.remove('on');
    lbl.textContent = 'Désactivé';
    lbl.style.color = 'var(--muted)';
  }}
}}

// ── Reconnaissance faciale ──────────────────────
var _faceActive = false;

async function toggleFaceRecognition() {{
  _faceActive = !_faceActive;
  try {{
    var r = await fetch(SERVER + '/faces/toggle', {{
      method: 'POST', credentials: 'same-origin',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{active: _faceActive}})
    }});
    var d = await r.json();
    _faceActive = d.active;
    updateFaceUI();
    toast(_faceActive ? '👤 Reconnaissance activée' : '👤 Reconnaissance désactivée');
  }} catch(e) {{ toast('Connexion impossible', 'err'); _faceActive = !_faceActive; }}
}}

function updateFaceUI() {{
  var tog = document.getElementById('faceToggle');
  var lbl = document.getElementById('faceActiveStatus');
  if (!tog) return;
  if (_faceActive) {{
    tog.classList.add('on');
    lbl.textContent = '🔴 Active — identification en continu (charge CPU modérée)';
    lbl.style.color = 'var(--red)';
  }} else {{
    tog.classList.remove('on');
    lbl.textContent = 'Désactivée';
    lbl.style.color = 'var(--muted)';
  }}
}}

async function loadFaceStatus() {{
  try {{
    var r = await fetch(SERVER + '/faces/status', {{credentials:'same-origin'}});
    var d = await r.json();
    _faceActive = d.active;
    updateFaceUI();
    var ms = document.getElementById('faceModelStatus');
    if (ms) {{
      ms.textContent = d.model_ready
        ? '✓ Modèle prêt — ' + d.people.length + ' personne(s)'
        : 'Modèle non entraîné';
    }}
  }} catch(e) {{}}
}}

async function uploadFacePhotos(files) {{
  var name = document.getElementById('facePersonName').value.trim();
  if (!name) {{ toast('Indiquez un nom', 'err'); return; }}
  if (!files || !files.length) return;
  var ok = 0;
  for (var i = 0; i < files.length; i++) {{
    var fd = new FormData();
    fd.append('name', name);
    fd.append('file', files[i]);
    try {{
      var r = await fetch(SERVER + '/faces/add', {{
        method: 'POST', credentials: 'same-origin', body: fd
      }});
      var d = await r.json();
      if (d.status === 'ok') ok++;
    }} catch(e) {{}}
  }}
  toast(ok + ' photo(s) ajoutée(s) pour ' + name);
  document.getElementById('faceFileInput').value = '';
  loadFacePeople();
}}

async function retrainFaceModel() {{
  toast('Entraînement en cours…');
  try {{
    var r = await fetch(SERVER + '/faces/train', {{method:'POST', credentials:'same-origin'}});
    var d = await r.json();
    if (d.status === 'ok') {{
      toast('✓ Modèle entraîné (' + d.people.length + ' personne(s))');
      loadFaceStatus();
    }} else {{
      toast('Erreur : ' + d.message, 'err');
    }}
  }} catch(e) {{ toast('Connexion impossible', 'err'); }}
}}

async function loadFacePeople() {{
  try {{
    var r = await fetch(SERVER + '/faces/people', {{credentials:'same-origin'}});
    var d = await r.json();
    var wrap = document.getElementById('facePeopleList');
    if (!wrap) return;
    wrap.innerHTML = '';
    if (!d.people.length) {{
      wrap.innerHTML = '<span style="font-size:.78rem;color:var(--muted)">Aucune personne enregistrée</span>';
      return;
    }}
    d.people.forEach(function(p) {{
      var row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;'
        + 'background:#111;border:1px solid var(--border);border-radius:7px;padding:7px 10px';
      var info = document.createElement('span');
      info.style.fontSize = '.82rem';
      info.textContent = p.name + ' (' + p.photos + ' photo' + (p.photos > 1 ? 's' : '') + ')';
      var del = document.createElement('button');
      del.className = 'quick-del'; del.title = 'Supprimer'; del.textContent = '\\u00d7';
      del.onclick = (function(name) {{ return function() {{ deleteFacePerson(name); }}; }})(p.name);
      row.appendChild(info); row.appendChild(del);
      wrap.appendChild(row);
    }});
  }} catch(e) {{}}
}}

async function deleteFacePerson(name) {{
  if (!confirm('Supprimer ' + name + ' et toutes ses photos ?')) return;
  try {{
    var r = await fetch(SERVER + '/faces/person/' + encodeURIComponent(name),
                         {{method:'DELETE', credentials:'same-origin'}});
    var d = await r.json();
    if (d.status === 'ok') {{ toast('Personne supprimée'); loadFacePeople(); loadFaceStatus(); }}
    else toast('Erreur suppression', 'err');
  }} catch(e) {{ toast('Connexion impossible', 'err'); }}
}}

async function loadFaceRecent() {{
  try {{
    var r = await fetch(SERVER + '/faces/recent', {{credentials:'same-origin'}});
    var d = await r.json();
    var wrap = document.getElementById('faceRecentList');
    if (!wrap) return;
    if (!d.recognitions.length) {{
      wrap.textContent = 'Aucune identification récente';
      return;
    }}
    wrap.innerHTML = d.recognitions.map(function(r) {{
      return '<div style="padding:3px 0">' + r.time + ' — <strong style="color:var(--accent2)">'
        + r.name + '</strong></div>';
    }}).join('');
  }} catch(e) {{}}
}}

// ── Collapse cards ───────────────────────────
function collapseCard(id) {{
  var card = document.getElementById(id);
  card.classList.toggle('collapsed');
}}

// ── MP3 avec tags ─────────────────────────────
var mp3Labels   = {{}};
var _allFiles   = [];
var _openTags   = {{}};  // tag → true/false
var _allTagsOpen = true;

async function loadMP3List() {{
  try {{
    var rf = await fetch(SERVER + '/list_mp3');
    var rl = await fetch(SERVER + '/mp3_labels');
    var df = await rf.json();
    var dl = await rl.json();
    mp3Labels = dl.labels || {{}};
    _allFiles = df.files || [];
    buildTagView(_allFiles);
  }} catch(e) {{ console.error('loadMP3List', e); }}
}}

// Extrait le tag d'un nom de fichier : "tag_nomfichier.mp3" → "tag"
// Si pas de underscore → tag = "_sans tag_"
function getTag(fname) {{
  // Priorité : libellé stocké dans mp3Labels
  if (mp3Labels[fname]) return mp3Labels[fname];
  // Fallback : préfixe avant le premier '_' dans le nom de fichier
  var base = fname.replace(/[.][^.]+$/, '');
  var idx  = base.indexOf('_');
  return idx > 0 ? base.substring(0, idx) : '— sans tag —';
}}

function buildTagView(files) {{
  var q   = (document.getElementById('mp3Search') || {{}}).value || '';
  var low = q.toLowerCase();
  // Filtrer sur nom de fichier OU tag
  var filtered = low ? files.filter(function(f) {{
    return f.toLowerCase().includes(low) || getTag(f).toLowerCase().includes(low);
  }}) : files;

  // Grouper par tag
  var groups = {{}};
  filtered.forEach(function(f) {{
    var tag = getTag(f);
    if (!groups[tag]) groups[tag] = [];
    groups[tag].push(f);
  }});
  var tags = Object.keys(groups).sort(function(a,b) {{ return a.localeCompare(b,'fr'); }});

  var container = document.getElementById('tagContainer');
  container.innerHTML = '';

  if (!tags.length) {{
    container.innerHTML = '<div style="color:var(--muted);font-size:.79rem;padding:12px 0">Aucun fichier</div>';
    return;
  }}

  tags.forEach(function(tag) {{
    var isOpen = (_openTags[tag] !== undefined) ? _openTags[tag] : false;
    var grp = document.createElement('div'); grp.className = 'tag-group';

    var hdr = document.createElement('div'); hdr.className = 'tag-header';
    hdr.innerHTML =
      '<div class="tag-name">' +
        '<span class="tag-chevron' + (isOpen ? ' open' : '') + '">&#9656;</span>' +
        tag +
        '<span class="tag-count">' + groups[tag].length + '</span>' +
      '</div>';
    hdr.onclick = (function(t, g) {{ return function() {{
      var body = g.querySelector('.tag-body');
      var chev = g.querySelector('.tag-chevron');
      var open = body.classList.toggle('open');
      chev.classList.toggle('open', open);
      _openTags[t] = open;
    }}; }})(tag, grp);

    var body = document.createElement('div');
    body.className = 'tag-body' + (isOpen ? ' open' : '');

    groups[tag].forEach(function(fname) {{
      var row = document.createElement('div'); row.className = 'mp3-row';

      var info = document.createElement('div'); info.style.cssText = 'flex:1;overflow:hidden';
      // Nom de fichier sans extension — seul affiché (le tag est déjà dans l'en-tête)
      var lbl  = document.createElement('div'); lbl.className = 'mp3-name-lbl';
      lbl.textContent = fname.replace(/[.][^.]+$/, ''); lbl.title = fname;
      info.appendChild(lbl);

      var bPlay = document.createElement('button');
      bPlay.className = 'btn btn-success'; bPlay.style.cssText = 'font-size:.72rem;padding:3px 8px';
      bPlay.textContent = '\u25b6';
      bPlay.onclick = (function(fn) {{ return function() {{ playMP3(fn); }}; }})(fname);

      var bRen = document.createElement('button');
      bRen.className = 'btn btn-ghost'; bRen.style.cssText = 'font-size:.72rem;padding:3px 7px';
      bRen.textContent = '\u270e'; bRen.title = 'Renommer';
      bRen.onclick = (function(fn) {{ return function() {{ renameOpen(fn); }}; }})(fname);

      var bDel = document.createElement('button');
      bDel.className = 'btn btn-danger'; bDel.style.cssText = 'font-size:.72rem;padding:3px 7px';
      bDel.textContent = '\u00d7'; bDel.title = 'Supprimer';
      bDel.onclick = (function(fn) {{ return function() {{ deleteMP3(fn); }}; }})(fname);

      row.appendChild(info); row.appendChild(bPlay); row.appendChild(bRen); row.appendChild(bDel);
      body.appendChild(row);
    }});

    grp.appendChild(hdr); grp.appendChild(body);
    container.appendChild(grp);
  }});
}}

function filterTags() {{ buildTagView(_allFiles); }}

function toggleAllTags() {{
  _allTagsOpen = !_allTagsOpen;
  document.querySelectorAll('.tag-body').forEach(function(b) {{
    b.classList.toggle('open', _allTagsOpen);
  }});
  document.querySelectorAll('.tag-chevron').forEach(function(ch) {{
    ch.classList.toggle('open', _allTagsOpen);
  }});
  Object.keys(_openTags).forEach(function(k) {{ _openTags[k] = _allTagsOpen; }});
}}

async function playMP3(fname) {{
  try {{
    var r = await fetch(SERVER + '/play_mp3', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{filename: fname}})
    }});
    var d = await r.json();
    if (d.status === 'ok') {{
      var label = mp3Labels[fname] || fname.replace(/[.][^.]+$/, '');
      document.getElementById('nowPlaying').textContent = '\u25b6 ' + label;
      toast('\u25b6 ' + label);
    }} else toast('Erreur: ' + d.message, 'err');
  }} catch(e) {{ toast('Connexion impossible', 'err'); }}
}}

async function stopAudio() {{
  try {{
    await fetch(SERVER + '/stop_audio', {{method: 'POST'}});
    document.getElementById('nowPlaying').textContent = 'Aucune lecture';
    toast('Audio arrete');
  }} catch(e) {{ toast('Connexion impossible', 'err'); }}
}}

async function deleteMP3(fname) {{
  if (!confirm('Supprimer ' + (mp3Labels[fname] || fname) + ' ?')) return;
  try {{
    var r = await fetch(SERVER + '/delete_mp3', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{filename: fname}})
    }});
    var d = await r.json();
    if (d.status === 'ok') {{ toast('Supprime'); loadMP3List(); }}
    else toast('Erreur : ' + d.message, 'err');
  }} catch(e) {{ toast('Connexion impossible', 'err'); }}
}}

// saveMP3Order conservé pour compatibilité (drag-and-drop supprimé mais route toujours là)
async function saveMP3Order() {{}}

// Modal renommer
var _renTarget = '';
function renameOpen(fname) {{
  _renTarget = fname;
  document.getElementById('renameOld').value   = fname;
  document.getElementById('renameNew').value   = fname;
  document.getElementById('renameAlias').value = mp3Labels[fname] || '';
  document.getElementById('renameModal').classList.add('open');
  setTimeout(function() {{ document.getElementById('renameAlias').focus(); }}, 40);
}}
function renameClose() {{ document.getElementById('renameModal').classList.remove('open'); }}
async function renameConfirm() {{
  var oldN  = _renTarget;
  var newN  = document.getElementById('renameNew').value.trim();
  var alias = document.getElementById('renameAlias').value.trim();
  var target = oldN;
  if (newN && newN !== oldN) {{
    try {{
      var r = await fetch(SERVER + '/rename_mp3', {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{old_name: oldN, new_name: newN}})
      }});
      var d = await r.json();
      if (d.status !== 'ok') {{ toast('Erreur renommage: ' + d.message, 'err'); return; }}
      target = newN;
    }} catch(e) {{ toast('Connexion impossible', 'err'); return; }}
  }}
  try {{
    await fetch(SERVER + '/mp3_labels', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{filename: target, label: alias}})
    }});
  }} catch(e) {{}}
  renameClose(); toast('Modifie'); loadMP3List();
}}

// Upload
async function uploadMP3(file) {{
  if (!file) return;
  var fd = new FormData(); fd.append('file', file);
  toast('Envoi de ' + file.name + '...');
  try {{
    var r = await fetch(SERVER + '/upload_mp3', {{method: 'POST', body: fd}});
    var d = await r.json();
    if (d.status === 'ok') {{ toast(d.filename + ' uploade'); loadMP3List(); }}
    else toast('Erreur upload: ' + d.message, 'err');
  }} catch(e) {{ toast('Connexion impossible', 'err'); }}
}}
var dz = document.getElementById('dropZone');
dz.addEventListener('dragover',  function(e) {{ e.preventDefault(); dz.style.borderColor = 'var(--accent)'; }});
dz.addEventListener('dragleave', function() {{ dz.style.borderColor = ''; }});
dz.addEventListener('drop', function(e) {{
  e.preventDefault(); dz.style.borderColor = '';
  var f = e.dataTransfer.files[0]; if (f) uploadMP3(f);
}});

// Timer VGT
var _timerInterval = null;
function startTimerClock() {{
  if (_timerInterval) return;
  _timerInterval = setInterval(function() {{
    document.getElementById('timerClock').textContent =
      new Date().toLocaleTimeString('fr-FR', {{hour:'2-digit',minute:'2-digit',second:'2-digit'}});
  }}, 500);
}}
async function loadTimerStatus() {{
  try {{
    var r = await fetch(SERVER + '/timer/status');
    var d = await r.json();
    applyTimerState(d.enabled);
    buildTimerTable(d.schedule || []);
    buildTimerLog(d.log || []);
  }} catch(e) {{ console.error(e); }}
}}
function applyTimerState(on) {{
  document.getElementById('timerPill').classList.toggle('on', on);
  var b = document.getElementById('timerBadge');
  b.textContent = on ? 'ON' : 'OFF';
  b.className = 'timer-badge ' + (on ? 'on' : 'off');
}}
async function timerToggle() {{
  try {{
    var r = await fetch(SERVER + '/timer/toggle', {{method: 'POST'}});
    var d = await r.json();
    applyTimerState(d.enabled);
    toast('Timer ' + (d.enabled ? 'active' : 'desactive'));
  }} catch(e) {{ toast('Erreur', 'err'); }}
}}
function buildTimerTable(schedule) {{
  var tbody = document.getElementById('timerBody');
  tbody.innerHTML = '';
  schedule.forEach(function(row, i) {{
    var tr = document.createElement('tr');
    var tdT = document.createElement('td');
    var inT = document.createElement('input');
    inT.type = 'text'; inT.value = row.time || ''; inT.placeholder = 'HH:MM';
    inT.style.width = '60px';
    tdT.appendChild(inT);
    var tdF = document.createElement('td');
    var inF = document.createElement('input');
    inF.type = 'text'; inF.value = row.file || ''; inF.placeholder = 'fichier.mp3';
    tdF.appendChild(inF);
    var tdD = document.createElement('td');
    var btn = document.createElement('button'); btn.className = 'tdel'; btn.textContent = '\u00d7';
    btn.onclick = (function(idx) {{ return function() {{ timerDelRow(idx); }}; }})(i);
    tdD.appendChild(btn);
    tr.appendChild(tdT); tr.appendChild(tdF); tr.appendChild(tdD);
    tbody.appendChild(tr);
  }});
}}
function buildTimerLog(logs) {{
  var el = document.getElementById('timerLog');
  if (!logs.length) {{ el.innerHTML = '<span style="color:var(--muted)">Aucun rappel.</span>'; return; }}
  el.innerHTML = logs.slice().reverse().map(function(l) {{
    return '<div><span style="color:var(--accent2)">' + l.ts + '</span> &rarr; ' + l.file + '</div>';
  }}).join('');
}}
function timerGetSchedule() {{
  return Array.from(document.querySelectorAll('#timerBody tr')).map(function(tr) {{
    var ins = tr.querySelectorAll('input');
    return {{time: ins[0].value.trim(), file: ins[1].value.trim()}};
  }}).filter(function(r) {{ return r.time && r.file; }});
}}
async function timerSave() {{
  var schedule = timerGetSchedule();
  try {{
    var r = await fetch(SERVER + '/timer/schedule', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{schedule: schedule}})
    }});
    var d = await r.json();
    if (d.status === 'ok') toast('Planning sauvegarde');
    else toast('Erreur', 'err');
  }} catch(e) {{ toast('Connexion impossible', 'err'); }}
}}
async function timerReset() {{
  if (!confirm('Reinitialiser le planning par defaut ?')) return;
  try {{
    var r = await fetch(SERVER + '/timer/reset', {{method: 'POST'}});
    var d = await r.json();
    buildTimerTable(d.schedule || []);
    toast('Planning reinitialise');
  }} catch(e) {{ toast('Erreur', 'err'); }}
}}
function timerAddRow() {{
  var s = timerGetSchedule();
  s.push({{time: '', file: ''}});
  buildTimerTable(s);
  var ins = document.querySelectorAll('#timerBody tr:last-child input');
  if (ins[0]) ins[0].focus();
}}
function timerDelRow(i) {{
  var s = timerGetSchedule();
  s.splice(i, 1);
  buildTimerTable(s);
}}
async function timerFiredReset() {{
  try {{
    await fetch(SERVER + '/timer/fired_reset', {{method: 'POST'}});
    toast('Sonneries rearmees');
  }} catch(e) {{ toast('Erreur', 'err'); }}
}}
setInterval(function() {{
  if (document.getElementById('pane-timer').classList.contains('active'))
    fetch(SERVER + '/timer/status').then(function(r) {{ return r.json(); }})
      .then(function(d) {{ buildTimerLog(d.log || []); }}).catch(function() {{}});
}}, 30000);

setInterval(function() {{
  var p = document.getElementById('pane-faces');
  if (p && p.classList.contains('active')) loadFaceRecent();
}}, 5000);

// Qualite video
var QL = {{hd:'HD 960x540 ~13 Mbit/s', medium:'Moyen 640x360 ~4 Mbit/s', low:'Eco 480x270 ~1 Mbit/s'}};
async function setQuality(q) {{
  try {{
    var r = await fetch(SERVER + '/set_quality', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{quality: q}})
    }});
    var d = await r.json();
    if (d.status === 'ok') {{
      ['hd','medium','low'].forEach(function(k) {{
        document.getElementById('q-' + k).className = 'btn ' + (k === q ? 'btn-success' : 'btn-ghost');
      }});
      document.getElementById('qualityLabel').textContent = QL[q];
      toast('Qualite : ' + QL[q]);
    }}
  }} catch(e) {{ toast('Erreur qualite', 'err'); }}
}}
(async function() {{
  try {{
    var r = await fetch(SERVER + '/get_quality'); var d = await r.json();
    ['hd','medium','low'].forEach(function(k) {{
      document.getElementById('q-' + k).className = 'btn ' + (k === d.quality ? 'btn-success' : 'btn-ghost');
    }});
    document.getElementById('qualityLabel').textContent = QL[d.quality] || d.label;
  }} catch(e) {{}}
}})();

// Captures
var capturesOn = false;
async function toggleCaptures() {{
  capturesOn = !capturesOn;
  try {{
    await fetch(SERVER + '/set_captures', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{enabled: capturesOn}})
    }});
    document.getElementById('captureToggle').classList.toggle('on', capturesOn);
    document.getElementById('captureStatus').textContent = capturesOn ? 'Activees' : 'Desactivees';
    toast(capturesOn ? 'Captures activees' : 'Captures desactivees');
  }} catch(e) {{ toast('Erreur', 'err'); }}
}}

// Ecoute micro
var audioCtx = null, gainNode = null, audioSSE = null, listening = false;
var sampleRate = 44100, nextTime = 0;
var AHEAD = 0.10;

document.getElementById('listenVolume').addEventListener('input', function() {{
  document.getElementById('volLabel').textContent = Math.round(this.value * 100) + '%';
  if (gainNode) gainNode.gain.value = parseFloat(this.value);
}});
function setAudioStatus(text, color) {{
  document.getElementById('audioStatus').textContent = text;
  document.getElementById('audioIndicator').style.background = color;
}}
function toggleListen() {{ if (listening) stopListen(); else startListen(); }}
function startListen() {{
  if (listening) return;
  listening = true;
  document.getElementById('btnListen').textContent = 'Stop ecoute';
  document.getElementById('btnListen').className = 'btn btn-danger';
  setAudioStatus('Ouverture micro...', '#f0a500');
  fetch(SERVER + '/mic_start', {{method: 'POST'}}).catch(function() {{}});
  audioCtx = new (window.AudioContext || window.webkitAudioContext)({{sampleRate: sampleRate}});
  gainNode = audioCtx.createGain();
  gainNode.gain.value = parseFloat(document.getElementById('listenVolume').value);
  gainNode.connect(audioCtx.destination);
  nextTime = audioCtx.currentTime + AHEAD;
  audioSSE = new EventSource(SERVER + '/audio_stream');
  audioSSE.addEventListener('config', function(e) {{
    var cfg = JSON.parse(e.data); sampleRate = cfg.sampleRate;
    if (audioCtx.sampleRate !== sampleRate) {{
      audioCtx.close();
      audioCtx = new (window.AudioContext || window.webkitAudioContext)({{sampleRate: sampleRate}});
      gainNode = audioCtx.createGain();
      gainNode.gain.value = parseFloat(document.getElementById('listenVolume').value);
      gainNode.connect(audioCtx.destination);
      nextTime = audioCtx.currentTime + AHEAD;
    }}
    setAudioStatus('Micro en direct', '#3ecf8e');
  }});
  audioSSE.onmessage = function(e) {{
    if (!audioCtx || !gainNode) return;
    try {{
      var binStr = atob(e.data);
      var bytes = new Uint8Array(binStr.length);
      for (var i = 0; i < binStr.length; i++) bytes[i] = binStr.charCodeAt(i);
      var pcm16 = new Int16Array(bytes.buffer);
      var f32 = new Float32Array(pcm16.length);
      for (var i = 0; i < pcm16.length; i++) f32[i] = pcm16[i] / 32768.0;
      var buf = audioCtx.createBuffer(1, f32.length, sampleRate);
      buf.copyToChannel(f32, 0);
      var src = audioCtx.createBufferSource();
      src.buffer = buf; src.connect(gainNode);
      var now = audioCtx.currentTime;
      if (nextTime < now + 0.01) nextTime = now + AHEAD;
      src.start(nextTime); nextTime += buf.duration;
    }} catch(err) {{ console.warn('[Audio]', err); }}
  }};
  audioSSE.onerror = function() {{ if (listening) setAudioStatus('Reconnexion...', '#e35b5b'); }};
}}
function stopListen() {{
  listening = false;
  if (audioSSE) {{ audioSSE.close(); audioSSE = null; }}
  if (audioCtx) {{ audioCtx.close(); audioCtx = null; gainNode = null; }}
  nextTime = 0;
  fetch(SERVER + '/mic_stop', {{method: 'POST'}}).catch(function() {{}});
  document.getElementById('btnListen').textContent = 'Ecouter';
  document.getElementById('btnListen').className = 'btn btn-primary';
  setAudioStatus('Micro ferme', '#444');
}}

// ── Interphone (client → serveur) ──────────────
var _interphoneOn    = false;
var _mediaRecorder   = null;
var _interphoneStream = null;

function setInterphoneStatus(text, color) {{
  var ind = document.getElementById('interphoneIndicator');
  var lbl = document.getElementById('interphoneStatus');
  if (ind) ind.style.background = color;
  if (lbl) lbl.textContent = text;
}}

function onInterphoneVolume(val) {{
  document.getElementById('interphoneVolLabel').textContent = Math.round(val * 100) + '%';
  fetch(SERVER + '/interphone/volume', {{
    method: 'POST', credentials: 'same-origin',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{volume: parseFloat(val)}})
  }}).catch(function() {{}});
}}

async function toggleInterphone() {{
  if (_interphoneOn) {{
    stopInterphone();
  }} else {{
    await startInterphone();
  }}
}}

async function startInterphone() {{
  if (_interphoneOn) return;
  try {{
    _interphoneStream = await navigator.mediaDevices.getUserMedia({{
      audio: {{
        channelCount: 1,
        sampleRate: 16000,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
      }},
      video: false
    }});
  }} catch(e) {{
    toast('Micro refusé par le navigateur', 'err');
    setInterphoneStatus('Accès micro refusé', '#e35b5b');
    return;
  }}

  // Activer côté serveur
  var r = await fetch(SERVER + '/interphone/toggle', {{
    method: 'POST', credentials: 'same-origin',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{active: true}})
  }}).catch(function() {{ return null; }});
  if (!r || !r.ok) {{
    toast('Erreur activation interphone', 'err');
    _interphoneStream.getTracks().forEach(function(t) {{ t.stop(); }});
    return;
  }}

  _interphoneOn = true;
  document.getElementById('btnInterphone').textContent = '⏹ Arrêter';
  document.getElementById('btnInterphone').className = 'btn btn-danger';
  setInterphoneStatus('🔴 En cours — vous parlez dans la salle', '#e35b5b');

  // MediaRecorder en timeslice : envoie un chunk toutes les 80 ms
  // On demande PCM via AudioContext + ScriptProcessor pour avoir du raw PCM16
  var ctx = new (window.AudioContext || window.webkitAudioContext)({{sampleRate: 16000}});
  var src = ctx.createMediaStreamSource(_interphoneStream);
  var bufferSize = 2048;
  var proc = ctx.createScriptProcessor(bufferSize, 1, 1);

  proc.onaudioprocess = function(e) {{
    if (!_interphoneOn) return;
    var f32 = e.inputBuffer.getChannelData(0);
    // Convertir Float32 → Int16 PCM
    var pcm16 = new Int16Array(f32.length);
    for (var i = 0; i < f32.length; i++) {{
      var s = Math.max(-1, Math.min(1, f32[i]));
      pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }}
    fetch(SERVER + '/interphone/stream', {{
      method: 'POST', credentials: 'same-origin',
      headers: {{'Content-Type': 'application/octet-stream'}},
      body: pcm16.buffer
    }}).catch(function() {{}});
  }};

  src.connect(proc);
  proc.connect(ctx.destination);
  // Garder une référence pour pouvoir arrêter
  _interphoneOn = {{ctx: ctx, proc: proc, src: src}};
}}

function stopInterphone() {{
  if (!_interphoneOn) return;
  // Déconnecter AudioContext
  if (typeof _interphoneOn === 'object') {{
    try {{ _interphoneOn.proc.disconnect(); }} catch(e) {{}}
    try {{ _interphoneOn.src.disconnect(); }} catch(e) {{}}
    try {{ _interphoneOn.ctx.close(); }} catch(e) {{}}
  }}
  _interphoneOn = false;
  if (_interphoneStream) {{
    _interphoneStream.getTracks().forEach(function(t) {{ t.stop(); }});
    _interphoneStream = null;
  }}
  fetch(SERVER + '/interphone/toggle', {{
    method: 'POST', credentials: 'same-origin',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{active: false}})
  }}).catch(function() {{}});
  document.getElementById('btnInterphone').textContent = '🎙 Parler';
  document.getElementById('btnInterphone').className = 'btn btn-success';
  setInterphoneStatus('Inactif', '#444');
}}

// Init
loadVoices();
loadPhrases();
loadMP3List();
loadFaceStatus();
loadFacePeople();
loadFaceRecent();
fetch(SERVER + '/interphone/status', {{credentials:'same-origin'}})
  .then(function(r) {{ return r.json(); }})
  .then(function(d) {{
    if (d.active) {{
      setInterphoneStatus('Actif (session précédente)', '#f0a500');
      // Réinitialiser côté serveur au cas où
      fetch(SERVER + '/interphone/toggle', {{
        method:'POST', credentials:'same-origin',
        headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify({{active:false}})
      }});
    }}
    var vol = d.volume || 0.8;
    var sl = document.getElementById('interphoneVolume');
    var lb = document.getElementById('interphoneVolLabel');
    if (sl) sl.value = vol;
    if (lb) lb.textContent = Math.round(vol * 100) + '%';
  }}).catch(function() {{}});
</script>
</body>
</html>'''


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
#  NGROK — tunnel public optionnel
# ─────────────────────────────────────────────
def start_ngrok(port: int = 5000):
    """
    Lance ngrok en subprocess et retourne l'URL publique.
    Nécessite ngrok.exe dans le même dossier que ce script
    ET NGROK_TOKEN défini dans .env
    """
    global ngrok_public_url
    token = os.environ.get('NGROK_TOKEN', '').strip()
    if not token:
        log.info("[NGROK] NGROK_TOKEN absent — tunnel désactivé")
        return None

    ngrok_exe = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ngrok.exe')
    if not os.path.isfile(ngrok_exe):
        log.warning(f"[NGROK] ngrok.exe introuvable dans {os.path.dirname(ngrok_exe)}")
        return None

    try:
        # Configurer le token (une seule fois suffit, mais sans nuire si répété)
        import subprocess
        subprocess.run([ngrok_exe, 'config', 'add-authtoken', token],
                       capture_output=True, timeout=10)

        # Lancer le tunnel en arrière-plan
        proc = subprocess.Popen(
            [ngrok_exe, 'http', str(port), '--log', 'stdout', '--log-format', 'json'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )

        # Lire les logs JSON jusqu'à obtenir l'URL publique (timeout 10 s)
        import select
        deadline = time.time() + 10
        url = None
        while time.time() < deadline and url is None:
            try:
                line = proc.stdout.readline()
                if not line:
                    break
                data = json.loads(line.decode('utf-8', errors='ignore'))
                if data.get('msg') == 'started tunnel':
                    url = data.get('url') or data.get('public_url')
            except (json.JSONDecodeError, Exception):
                pass

        if url:
            ngrok_public_url = url
            log.info(f"[NGROK] ✓ Tunnel actif : {url}")
            return url
        else:
            log.warning("[NGROK] Tunnel démarré mais URL non récupérée dans les délais")
            return None
    except Exception as e:
        log.error(f"[NGROK] Erreur démarrage : {e}")
        return None


if __name__ == '__main__':
    log.info("=== LOGITECH C920 - SURVEILLANCE HD ===")
    log.info(f"Fichier de log : {LOG_FILE}")
    log.info("Démarrage du serveur...")
    log.info("[MICRO] Micro en veille — s'active à la demande via le bouton Écouter")
    save_html_file()
    ip_address = get_local_ip()
    # Démarrer ngrok si token présent (avant Flask pour avoir l'URL dès le départ)
    public_url = start_ngrok(port=5000)
    local_url  = f"http://{ip_address}:5000"
    print(f"\n  Interface LAN    : {local_url}")
    if public_url:
        print(f"  Accès externe    : {public_url}")
    print(f"  Flux vidéo       : {local_url}/video_feed")
    print(f"  Dossier captures : {motion_captures_dir}")
    print(f"  Dossier MP3      : {MP3_DIR}")
    print()
    try:
        rep = input("  Ouvrir le navigateur ? [O/n] : ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        rep = 'o'
    if rep in ('', 'o', 'oui', 'y', 'yes'):
        try:
            webbrowser.open(local_url)
            print("  Navigateur ouvert.\n")
        except Exception as e:
            print(f"  Impossible d'ouvrir le navigateur : {e}\n")
    else:
        print("  Navigateur non ouvert.\n")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)