import cv2
import flask
import numpy as np
import datetime
import os
from pathlib import Path
import time
import socket
import getpass
from flask import Response, request, jsonify, stream_with_context
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

def _speak_edge(text: str):
    import asyncio, tempfile, edge_tts
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp = f.name
    try:
        async def _gen():
            await edge_tts.Communicate(text, EDGE_TTS_VOICE).save(tmp)
        asyncio.run(_gen())
        with audio_lock:
            pygame.mixer.music.load(tmp)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
    finally:
        Path(tmp).unlink(missing_ok=True)

def speak_text(text: str):
    def _run():
        with tts_lock:
            log.info(f"[TTS/Edge] {text}")
            try:
                _speak_edge(text)
            except Exception as e:
                log.error(f"[TTS/Edge] Erreur : {e}")
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

    # Ouvrir directement l'interface Flask dans le navigateur
    try:
        webbrowser.open(server_url)
        print(f"Navigateur ouvert sur {server_url}")
    except Exception as e:
        print(f"Impossible d'ouvrir le navigateur : {e}")


# ─────────────────────────────────────────────
#  INITIALISATION
# ─────────────────────────────────────────────
camera = RobustCamera()
motion_detected = False
last_frame = None
motion_threshold = 1500
capture_count = 0
MAX_CAPTURES = 100
SAVE_CAPTURES = False   # désactivé par défaut pour réduire l'activité fichier suspecte

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
    global last_frame, motion_detected
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
    global motion_detected
    motion_cooldown = 0
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
                if frame_count % 100 == 0:
                    log.debug(f"[STREAM] ✓ {frame_count} frames envoyées, shape={frame.shape}")
                if frame_count % 2 == 0:
                    motion_detected, frame = detect_motion(frame)
                    if motion_detected and motion_cooldown == 0:
                        if SAVE_CAPTURES:
                            log.info("[STREAM] Mouvement détecté — capture sauvegardée")
                            save_capture(frame)
                        motion_cooldown = 30
                if motion_cooldown > 0:
                    motion_cooldown -= 1
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

@app.route('/phrases/<int:pid>', methods=['DELETE'])
def delete_phrase(pid):
    phrases = [p for p in _load_phrases() if p['id'] != pid]
    _save_phrases(phrases)
    return jsonify({"status": "ok", "phrases": phrases})




# ── MP3 : upload ─────────────────────────────
@app.route('/upload_mp3', methods=['POST'])
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
@app.route('/play_mp3', methods=['POST'])
def play_mp3():
    """
    POST JSON : {"filename": "alerte.mp3"}
    Joue le fichier sur la machine caméra.
    """
    data = request.get_json(silent=True) or {}
    filename = data.get('filename', '').strip()
    if not filename:
        return jsonify({"status": "error", "message": "Champ 'filename' manquant"}), 400
    path = os.path.join(MP3_DIR, os.path.basename(filename))
    if not os.path.exists(path):
        return jsonify({"status": "error", "message": f"Fichier introuvable: {filename}"}), 404
    print(f"[AUDIO] ← lecture {filename}")
    play_mp3_file(path)
    return jsonify({"status": "ok", "filename": filename})


# ── MP3 : stop ────────────────────────────────
@app.route('/stop_audio', methods=['POST'])
def stop_audio():
    """Arrête la lecture audio en cours."""
    try:
        pygame.mixer.music.stop()
        print("[AUDIO] Lecture arrêtée")
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500



# ── MP3 : supprimer ──────────────────────────
@app.route('/delete_mp3', methods=['POST'])
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
def route_mic_start():
    ok = mic_start()
    return jsonify({"status": "ok" if ok else "error", "active": mic_active})

@app.route('/mic_stop', methods=['POST'])
def route_mic_stop():
    mic_stop()
    return jsonify({"status": "ok", "active": False})

@app.route('/mic_status')
def route_mic_status():
    return jsonify({"active": mic_active})


# ── Flux audio SSE ────────────────────────────
@app.route('/audio_stream')
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


@app.route('/')
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
h1{{font-size:1.05rem;font-weight:600;letter-spacing:.04em}}
.dot{{width:8px;height:8px;border-radius:50%;background:var(--accent2);
      box-shadow:0 0 6px var(--accent2);animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
.layout{{display:grid;grid-template-columns:1fr 390px;height:calc(100vh - 49px)}}
.video-panel{{background:#000;display:flex;align-items:center;justify-content:center;
              overflow:hidden;position:relative}}
.video-panel img{{width:100%;height:100%;object-fit:contain}}

.ctrl-panel{{background:var(--surface);border-left:1px solid var(--border);
             display:flex;flex-direction:column;overflow:hidden;height:100%}}
.tabs{{display:flex;border-bottom:1px solid var(--border);flex-shrink:0}}
.tab{{flex:1;padding:9px 1px;font-size:.71rem;text-align:center;cursor:pointer;
      color:var(--muted);border-bottom:2px solid transparent;
      transition:color .15s,border-color .15s;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
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
.quick-item{{display:flex;align-items:center;gap:5px}}
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
      <!-- Upload collapsible -->
      <div class="card card-collapsible" id="uploadCard"
           style="border-radius:0;border-left:none;border-right:none;border-top:none;flex-shrink:0;padding-bottom:24px">
        <div class="card-title-row" onclick="collapseCard('uploadCard')">
          <h2 style="margin-bottom:0">&#128194; Ajouter un fichier</h2>
          <button class="collapse-btn" tabindex="-1">&#9656;</button>
        </div>
        <div class="card-body" style="max-height:120px">
          <label class="upload-area" for="mp3Input" id="dropZone">
            Cliquez ou d&eacute;posez MP3 / WAV / OGG
          </label>
          <input type="file" id="mp3Input" accept=".mp3,.wav,.ogg" onchange="uploadMP3(this.files[0])">
        </div>
      </div>
      <!-- Bibliothèque plein panneau avec tags -->
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

    </div>

    <!-- onglet Ecoute -->
    <div class="tab-content" id="pane-listen">
      <div class="card">
        <h2>&Eacute;coute micro en direct</h2>
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
const SERVER = 'http://{ip}:5000';

// Onglets
function switchTab(name) {{
  document.querySelectorAll('.tab').forEach(function(t) {{ t.classList.remove('active'); }});
  document.querySelectorAll('.tab-content').forEach(function(p) {{ p.classList.remove('active'); }});
  document.getElementById('tab-' + name).classList.add('active');
  document.getElementById('pane-' + name).classList.add('active');
  if (name === 'mp3')   loadMP3List();
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

// Phrases rapides
function buildQuickBtns(phrases) {{
  var wrap = document.getElementById('quickBtns');
  wrap.innerHTML = '';
  phrases.forEach(function(p) {{
    var row = document.createElement('div'); row.className = 'quick-item';
    var btn = document.createElement('button'); btn.className = 'quick-btn';
    btn.textContent = p.text; btn.title = p.text;
    btn.onclick = (function(txt) {{ return function() {{
      document.getElementById('ttsText').value = txt; sendTTS();
    }}; }})(p.text);
    var del = document.createElement('button');
    del.className = 'quick-del'; del.title = 'Supprimer'; del.textContent = '\u00d7';
    del.onclick = (function(pid) {{ return function() {{ deletePhrase(pid); }}; }})(p.id);
    row.appendChild(btn); row.appendChild(del); wrap.appendChild(row);
  }});
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

// Init
loadVoices();
loadPhrases();
loadMP3List();
</script>
</body>
</html>'''


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────
if __name__ == '__main__':
    log.info("=== LOGITECH C920 - SURVEILLANCE HD ===")
    log.info(f"Fichier de log : {LOG_FILE}")
    log.info("Démarrage du serveur...")
    log.info("[MICRO] Micro en veille — s'active à la demande via le bouton Écouter")
    save_html_file()
    ip_address = get_local_ip()
    print(f"\n  Interface de contrôle : http://{ip_address}:5000")
    print(f"  Flux vidéo seul       : http://{ip_address}:5000/video_feed")
    print(f"  Dossier captures      : {motion_captures_dir}")
    print(f"  Dossier MP3           : {MP3_DIR}")
    print("\n  Endpoints disponibles :")
    print("    POST /tts           → {{\"text\": \"...\"}}        – Lecture TTS")
    print("    POST /upload_mp3    → form-data 'file'         – Upload audio")
    print("    GET  /list_mp3                                 – Liste des fichiers")
    print("    POST /play_mp3      → {{\"filename\": \"...\"}}     – Jouer un fichier")
    print("    POST /stop_audio                               – Arrêter la lecture")
    print()
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)