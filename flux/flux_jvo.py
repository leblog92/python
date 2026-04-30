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
MP3_DIR = os.path.join(os.environ.get('USERPROFILE', os.path.expanduser('~')), 'Music', 'jvo_sounds')
os.makedirs(MP3_DIR, exist_ok=True)

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



# ── MP3 : renommer ───────────────────────────
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
    if os.path.exists(new_path):
        return jsonify({"status": "error", "message": "Ce nom existe déjà"}), 409
    try:
        os.rename(old_path, new_path)
        log.info(f"[AUDIO] Renommé : {old_name} → {new_name}")
        return jsonify({"status": "ok", "old_name": old_name, "new_name": new_name})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── MP3 : supprimer ───────────────────────────
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
        os.remove(path)
        log.info(f"[AUDIO] Supprimé : {filename}")
        return jsonify({"status": "ok", "filename": filename})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── MP3 : libellés personnalisés ─────────────
MP3_LABELS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mp3_labels.json')

def _load_mp3_labels():
    try:
        if os.path.exists(MP3_LABELS_FILE):
            with open(MP3_LABELS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_mp3_labels(labels):
    try:
        with open(MP3_LABELS_FILE, 'w', encoding='utf-8') as f:
            json.dump(labels, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"[AUDIO] Sauvegarde libellés échouée : {e}")

@app.route('/mp3_labels', methods=['GET'])
def get_mp3_labels():
    return jsonify({"labels": _load_mp3_labels()})

@app.route('/mp3_labels', methods=['POST'])
def set_mp3_label():
    data = request.get_json(silent=True) or {}
    filename = data.get('filename', '').strip()
    label    = data.get('label', '').strip()
    if not filename:
        return jsonify({"status": "error", "message": "Nom manquant"}), 400
    labels = _load_mp3_labels()
    if label:
        labels[filename] = label
    else:
        labels.pop(filename, None)
    _save_mp3_labels(labels)
    return jsonify({"status": "ok", "labels": labels})


# ── MP3 : ordre personnalisé ──────────────────
MP3_ORDER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mp3_order.json')

def _load_mp3_order():
    try:
        if os.path.exists(MP3_ORDER_FILE):
            with open(MP3_ORDER_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return []

def _save_mp3_order(order):
    try:
        with open(MP3_ORDER_FILE, 'w', encoding='utf-8') as f:
            json.dump(order, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"[AUDIO] Sauvegarde ordre échouée : {e}")

@app.route('/mp3_order', methods=['POST'])
def set_mp3_order():
    data = request.get_json(silent=True) or {}
    order = data.get('order', [])
    _save_mp3_order(order)
    return jsonify({"status": "ok"})

@app.route('/list_mp3')
def list_mp3():
    """Retourne la liste des fichiers audio disponibles, triée selon l'ordre sauvegardé."""
    try:
        files = [f for f in os.listdir(MP3_DIR)
                 if f.lower().endswith(('.mp3', '.wav', '.ogg'))]
        saved_order = _load_mp3_order()
        # Fichiers présents dans l'ordre sauvegardé d'abord, puis les nouveaux alphabétiquement
        ordered = [f for f in saved_order if f in files]
        rest    = sorted([f for f in files if f not in ordered])
        files   = ordered + rest
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "ok", "files": files})


# ── Timer VGT ────────────────────────────────
import pytz

TIMER_SCHEDULE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'timer_schedule.json')

_timer_default_schedule = [
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

timer_enabled    = False
timer_fired_set  = set()   # horaires déjà déclenchés aujourd'hui
timer_lock       = threading.Lock()
timer_log_list   = []      # historique pour l'UI

def _load_timer_schedule():
    try:
        if os.path.exists(TIMER_SCHEDULE_FILE):
            with open(TIMER_SCHEDULE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return list(_timer_default_schedule)

def _save_timer_schedule(schedule):
    try:
        with open(TIMER_SCHEDULE_FILE, 'w', encoding='utf-8') as f:
            json.dump(schedule, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"[TIMER] Sauvegarde planning échouée : {e}")

def _timer_loop():
    global timer_fired_set
    paris = pytz.timezone('Europe/Paris')
    last_day = None
    while True:
        try:
            now      = datetime.datetime.now(paris)
            today    = now.strftime("%Y-%m-%d")
            hm       = now.strftime("%H:%M")
            if last_day != today:
                timer_fired_set = set()
                last_day = today
            with timer_lock:
                enabled = timer_enabled
            if enabled:
                schedule = _load_timer_schedule()
                for entry in schedule:
                    t = entry.get('time', '')
                    f = entry.get('file', '')
                    if t == hm and t not in timer_fired_set:
                        path = os.path.join(MP3_DIR, os.path.basename(f))
                        if os.path.exists(path):
                            log.info(f"[TIMER] {t} → {f}")
                            play_mp3_file(path)
                        else:
                            log.warning(f"[TIMER] Fichier introuvable : {f}")
                        timer_fired_set.add(t)
                        timer_log_list.append({"time": t, "file": f,
                                               "ts": now.strftime("%H:%M:%S")})
                        if len(timer_log_list) > 100:
                            timer_log_list.pop(0)
        except Exception as e:
            log.error(f"[TIMER] Erreur boucle : {e}")
        time.sleep(15)

threading.Thread(target=_timer_loop, daemon=True).start()

@app.route('/timer/status')
def timer_status():
    schedule = _load_timer_schedule()
    return jsonify({
        "enabled": timer_enabled,
        "schedule": schedule,
        "log": timer_log_list[-20:],
        "fired": list(timer_fired_set),
    })

@app.route('/timer/toggle', methods=['POST'])
def timer_toggle():
    global timer_enabled
    with timer_lock:
        timer_enabled = not timer_enabled
    log.info(f"[TIMER] {'Activé' if timer_enabled else 'Désactivé'}")
    return jsonify({"status": "ok", "enabled": timer_enabled})

@app.route('/timer/schedule', methods=['POST'])
def timer_set_schedule():
    data = request.get_json(silent=True) or {}
    schedule = data.get('schedule', [])
    _save_timer_schedule(schedule)
    return jsonify({"status": "ok"})

@app.route('/timer/reset', methods=['POST'])
def timer_reset():
    _save_timer_schedule(list(_timer_default_schedule))
    return jsonify({"status": "ok", "schedule": _timer_default_schedule})

@app.route('/timer/fired_reset', methods=['POST'])
def timer_fired_reset():
    global timer_fired_set
    timer_fired_set = set()
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
<title>Salle JVO – Contrôle</title>
<style>
  :root {{
    --bg: #0d0d0d;
    --surface: #1a1a1a;
    --border: #2e2e2e;
    --accent: #4f8ef7;
    --accent2: #3ecf8e;
    --red: #e35b5b;
    --orange: #f0a500;
    --text: #e8e8e8;
    --muted: #888;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:var(--bg); color:var(--text); font-family:'Segoe UI',Arial,sans-serif; min-height:100vh; }}

  header {{
    background:var(--surface);
    border-bottom:1px solid var(--border);
    padding:14px 28px;
    display:flex; align-items:center; justify-content:space-between;
  }}
  .header-left {{ display:flex; align-items:center; gap:12px; }}
  header h1 {{ font-size:1.1rem; font-weight:600; letter-spacing:.05em; }}
  .dot {{ width:9px; height:9px; border-radius:50%; background:var(--accent2); box-shadow:0 0 6px var(--accent2); animation:pulse 2s infinite; }}
  @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.4}} }}

  .layout {{
    display:grid;
    grid-template-columns: 1fr 420px;
    gap:0;
    height:calc(100vh - 57px);
  }}

  /* ── Vidéo ── */
  .video-panel {{
    background:#000;
    display:flex; align-items:center; justify-content:center;
    overflow:hidden; position:relative;
  }}
  .video-panel img {{ width:100%; height:100%; object-fit:contain; }}
  .pip-btn {{
    position:absolute; bottom:12px; right:12px;
    background:rgba(0,0,0,.55); border:1px solid rgba(255,255,255,.2);
    color:#fff; border-radius:8px; padding:6px 12px; font-size:.78rem;
    cursor:pointer; backdrop-filter:blur(4px); z-index:10;
    transition:background .2s;
  }}
  .pip-btn:hover {{ background:rgba(79,142,247,.6); }}

  /* ── Panneau de contrôle ── */
  .ctrl-panel {{
    background:var(--surface);
    border-left:1px solid var(--border);
    display:flex; flex-direction:column;
    overflow:hidden;
  }}
  /* Onglets */
  .tabs {{
    display:flex; border-bottom:1px solid var(--border); flex-shrink:0;
  }}
  .tab {{
    flex:1; padding:10px 4px; font-size:.75rem; text-align:center;
    cursor:pointer; color:var(--muted); border-bottom:2px solid transparent;
    transition:color .15s, border-color .15s; white-space:nowrap; overflow:hidden;
    text-overflow:ellipsis;
  }}
  .tab.active {{ color:var(--accent); border-bottom-color:var(--accent); }}
  .tab-content {{ display:none; flex-direction:column; gap:16px; overflow-y:auto;
                  padding:16px; flex:1;
                  scrollbar-width:thin; scrollbar-color:var(--border) transparent; }}
  .tab-content.active {{ display:flex; }}

  .card {{
    background:var(--bg);
    border:1px solid var(--border);
    border-radius:10px;
    padding:14px;
  }}
  .card h2 {{
    font-size:.78rem; text-transform:uppercase; letter-spacing:.1em;
    color:var(--muted); margin-bottom:10px; display:flex; align-items:center; gap:6px;
  }}

  textarea, input[type=text] {{
    width:100%; background:#111; border:1px solid var(--border); border-radius:6px;
    color:var(--text); padding:9px; font-size:.88rem; resize:vertical;
    outline:none; transition:border .2s;
  }}
  textarea:focus, input[type=text]:focus {{ border-color:var(--accent); }}

  .btn {{
    display:inline-flex; align-items:center; justify-content:center; gap:5px;
    padding:8px 14px; border:none; border-radius:6px; font-size:.84rem;
    cursor:pointer; font-weight:600; transition:opacity .15s, transform .1s;
    white-space:nowrap;
  }}
  .btn:active {{ transform:scale(.97); }}
  .btn:disabled {{ opacity:.4; cursor:not-allowed; }}
  .btn-primary {{ background:var(--accent); color:#fff; }}
  .btn-success {{ background:var(--accent2); color:#000; }}
  .btn-danger  {{ background:var(--red); color:#fff; }}
  .btn-ghost   {{ background:var(--border); color:var(--text); }}
  .btn-orange  {{ background:var(--orange); color:#000; }}
  .btn-row {{ display:flex; gap:6px; flex-wrap:wrap; margin-top:10px; }}

  select {{
    width:100%; background:#111; border:1px solid var(--border); border-radius:6px;
    color:var(--text); padding:8px 10px; font-size:.84rem; outline:none; cursor:pointer;
    transition:border .2s; margin-bottom:8px;
  }}
  select:focus {{ border-color:var(--accent); }}

  /* ── Phrases rapides ── */
  .quick-btns {{ display:flex; flex-direction:column; gap:5px; }}
  .quick-item {{ display:flex; align-items:center; gap:5px; }}
  .quick-btn {{
    flex:1; background:#111; border:1px solid var(--border); border-radius:6px;
    color:var(--text); padding:7px 10px; font-size:.82rem; cursor:pointer;
    text-align:left; transition:border .2s, background .2s;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  }}
  .quick-btn:hover {{ border-color:var(--accent); background:#1a1a2e; }}
  .quick-del {{ background:none; border:none; color:var(--muted); cursor:pointer;
               font-size:.9rem; padding:2px 5px; flex-shrink:0; }}
  .quick-del:hover {{ color:var(--red); }}

  /* ── Lecteur MP3 amélioré ── */
  #mp3List {{ list-style:none; display:flex; flex-direction:column; gap:5px; }}
  .mp3-item {{
    background:#111; border:1px solid var(--border); border-radius:7px;
    padding:8px 10px; cursor:grab; transition:border .15s, background .15s;
  }}
  .mp3-item:hover {{ border-color:var(--accent); }}
  .mp3-item.dragging {{ opacity:.45; border-color:var(--accent2); cursor:grabbing; }}
  .mp3-item.drag-over {{ border-color:var(--accent2); background:#1a2e1a; }}
  .mp3-row1 {{ display:flex; align-items:center; gap:6px; }}
  .mp3-handle {{ color:var(--muted); font-size:1rem; cursor:grab; user-select:none; flex-shrink:0; }}
  .mp3-label {{ flex:1; font-size:.82rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .mp3-alias {{ font-size:.76rem; color:var(--muted); margin-top:2px; }}
  .mp3-row2 {{ display:flex; gap:5px; margin-top:7px; }}
  .mp3-row2 button {{ font-size:.75rem; padding:4px 9px; }}

  /* ── Upload ── */
  .upload-area {{
    border:2px dashed var(--border); border-radius:8px; padding:12px;
    text-align:center; cursor:pointer; font-size:.82rem; color:var(--muted);
    transition:border .2s;
  }}
  .upload-area:hover {{ border-color:var(--accent); color:var(--text); }}
  input[type=file] {{ display:none; }}

  /* ── Timer VGT ── */
  .timer-header {{ display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; }}
  .timer-clock {{ font-size:1.6rem; font-weight:700; font-family:monospace; color:var(--accent2); }}
  .toggle-pill {{
    width:44px; height:24px; border-radius:12px; background:#333;
    position:relative; cursor:pointer; transition:background .2s; flex-shrink:0;
  }}
  .toggle-pill.on {{ background:var(--accent2); }}
  .toggle-pill::after {{ content:''; width:18px; height:18px; border-radius:50%;
    background:#fff; position:absolute; top:3px; left:3px; transition:left .2s; }}
  .toggle-pill.on::after {{ left:23px; }}
  .timer-table {{ width:100%; border-collapse:collapse; font-size:.8rem; }}
  .timer-table th {{ color:var(--muted); text-align:left; padding:4px 6px;
                     border-bottom:1px solid var(--border); font-weight:500; }}
  .timer-table td {{ padding:5px 6px; border-bottom:1px solid #1e1e1e; }}
  .timer-table tr:last-child td {{ border-bottom:none; }}
  .timer-table input {{ background:#111; border:1px solid var(--border); border-radius:4px;
                        color:var(--text); padding:3px 6px; font-size:.78rem; outline:none; }}
  .timer-table input:focus {{ border-color:var(--accent); }}
  .timer-del {{ background:none; border:none; color:var(--muted); cursor:pointer; font-size:.85rem; }}
  .timer-del:hover {{ color:var(--red); }}
  .timer-log {{ max-height:100px; overflow-y:auto; font-size:.75rem; color:var(--muted);
                font-family:monospace; margin-top:6px;
                scrollbar-width:thin; scrollbar-color:var(--border) transparent; }}
  .timer-log div {{ padding:2px 0; }}
  .timer-badge {{
    display:inline-block; padding:2px 8px; border-radius:10px; font-size:.72rem;
    font-weight:700; margin-left:6px;
  }}
  .timer-badge.on  {{ background:#1a2e1a; color:var(--accent2); border:1px solid var(--accent2); }}
  .timer-badge.off {{ background:#2e1a1a; color:var(--red);     border:1px solid var(--red); }}

  /* ── Rename modal ── */
  .modal-overlay {{
    display:none; position:fixed; inset:0; z-index:500;
    background:rgba(0,0,0,.7); backdrop-filter:blur(3px);
    align-items:center; justify-content:center;
  }}
  .modal-overlay.open {{ display:flex; }}
  .modal-box {{
    background:var(--surface); border:1px solid var(--border); border-radius:12px;
    padding:24px; width:360px; max-width:90vw;
  }}
  .modal-box h3 {{ font-size:.9rem; margin-bottom:14px; color:var(--text); }}
  .modal-box input {{ margin-bottom:12px; }}
  .modal-btns {{ display:flex; gap:8px; justify-content:flex-end; }}

  /* ── Toast ── */
  #toast {{
    position:fixed; bottom:20px; right:20px; z-index:999;
    background:#222; border:1px solid var(--border); border-radius:8px;
    padding:10px 18px; font-size:.84rem; opacity:0; pointer-events:none;
    transition:opacity .3s; max-width:300px;
  }}
  #toast.show {{ opacity:1; }}
  #toast.ok  {{ border-color:var(--accent2); color:var(--accent2); }}
  #toast.err {{ border-color:var(--red);     color:var(--red); }}
</style>
</head>
<body>

<header>
  <div class="header-left">
    <div class="dot"></div>
    <h1>SALLE JVO – Surveillance &amp; Diffusion</h1>
  </div>
</header>

<div class="layout">
  <!-- Flux vidéo -->
  <div class="video-panel">
    <img id="videoFeed" src="/video_feed" alt="Flux vidéo">
    <button class="pip-btn" onclick="togglePiP()" id="pipBtn">⧉ Mode PiP</button>
  </div>

  <!-- Panneau onglets -->
  <div class="ctrl-panel">
    <div class="tabs">
      <div class="tab active" onclick="switchTab('tts')"    id="tab-tts">🔊 TTS</div>
      <div class="tab"        onclick="switchTab('mp3')"    id="tab-mp3">🎵 MP3</div>
      <div class="tab"        onclick="switchTab('timer')"  id="tab-timer">⏱ Timer</div>
      <div class="tab"        onclick="switchTab('cam')"    id="tab-cam">📷 Caméra</div>
      <div class="tab"        onclick="switchTab('listen')" id="tab-listen">🎧 Écoute</div>
    </div>

    <!-- ═══ ONGLET TTS ═══ -->
    <div class="tab-content active" id="pane-tts">
      <div class="card">
        <h2>Voix</h2>
        <select id="voiceSelect" onchange="setVoice(this.value)">
          <option value="">Chargement…</option>
        </select>
      </div>
      <div class="card">
        <h2>Message libre</h2>
        <textarea id="ttsText" rows="3" placeholder="Tapez votre message…"></textarea>
        <div class="btn-row">
          <button class="btn btn-primary" onclick="sendTTS()">▶ Lire</button>
          <button class="btn btn-ghost"   onclick="document.getElementById('ttsText').value=''">Effacer</button>
        </div>
      </div>
      <div class="card">
        <h2>Phrases rapides</h2>
        <div class="quick-btns" id="quickBtns"></div>
        <div style="display:flex;gap:6px;margin-top:10px">
          <input type="text" id="newPhrase" placeholder="Nouvelle phrase…"
                 style="flex:1;padding:7px 9px;font-size:.82rem"
                 onkeydown="if(event.key==='Enter') addPhrase()">
          <button class="btn btn-success" onclick="addPhrase()" style="padding:7px 12px">＋</button>
        </div>
      </div>
    </div>

    <!-- ═══ ONGLET MP3 ═══ -->
    <div class="tab-content" id="pane-mp3">
      <div class="card">
        <h2>Ajouter un fichier audio</h2>
        <label class="upload-area" for="mp3Input" id="dropZone">
          📂 Cliquez ou déposez MP3 / WAV / OGG
        </label>
        <input type="file" id="mp3Input" accept=".mp3,.wav,.ogg" onchange="uploadMP3(this.files[0])">
      </div>
      <div class="card">
        <h2 style="justify-content:space-between">
          <span>Bibliothèque audio</span>
          <div style="display:flex;gap:6px">
            <button class="btn btn-ghost" style="font-size:.72rem;padding:3px 8px" onclick="loadMP3List()">↺</button>
            <button class="btn btn-danger" style="font-size:.72rem;padding:3px 8px" onclick="stopAudio()">■ Stop</button>
          </div>
        </h2>
        <p style="font-size:.75rem;color:var(--muted);margin-bottom:8px">
          Glissez les ☰ pour réordonner · ✎ pour renommer · 🗑 pour supprimer
        </p>
        <ul id="mp3List"><li style="color:var(--muted);font-size:.82rem">Chargement…</li></ul>
      </div>
    </div>

    <!-- ═══ ONGLET TIMER ═══ -->
    <div class="tab-content" id="pane-timer">
      <div class="card">
        <div class="timer-header">
          <div>
            <div class="timer-clock" id="timerClock">--:--:--</div>
            <div style="font-size:.75rem;color:var(--muted);margin-top:2px">
              Timer automatique
              <span class="timer-badge off" id="timerBadge">OFF</span>
            </div>
          </div>
          <div class="toggle-pill" id="timerPill" onclick="timerToggle()"></div>
        </div>
        <div class="btn-row">
          <button class="btn btn-ghost"   style="font-size:.76rem" onclick="timerFiredReset()">↺ Réarmer</button>
          <button class="btn btn-ghost"   style="font-size:.76rem" onclick="timerReset()">Défaut</button>
          <button class="btn btn-success" style="font-size:.76rem" onclick="timerAddRow()">＋ Entrée</button>
        </div>
      </div>
      <div class="card">
        <h2>Planning</h2>
        <table class="timer-table">
          <thead><tr><th>Heure</th><th>Fichier MP3</th><th></th></tr></thead>
          <tbody id="timerBody"></tbody>
        </table>
        <div class="btn-row" style="margin-top:10px">
          <button class="btn btn-primary" onclick="timerSave()">💾 Sauvegarder</button>
        </div>
      </div>
      <div class="card">
        <h2>Historique</h2>
        <div class="timer-log" id="timerLog"><span style="color:var(--muted)">Aucun rappel aujourd'hui.</span></div>
      </div>
    </div>

    <!-- ═══ ONGLET CAMÉRA ═══ -->
    <div class="tab-content" id="pane-cam">
      <div class="card">
        <h2>Qualité vidéo</h2>
        <div class="btn-row" id="qualityBtns">
          <button class="btn btn-ghost"   id="q-hd"     onclick="setQuality('hd')">HD</button>
          <button class="btn btn-success" id="q-medium" onclick="setQuality('medium')">Moyen</button>
          <button class="btn btn-ghost"   id="q-low"    onclick="setQuality('low')">Éco</button>
        </div>
        <div style="margin-top:8px;font-size:.76rem;color:var(--muted)" id="qualityLabel">640×360 · ~4 Mbit/s</div>
      </div>
      <div class="card">
        <h2>Captures mouvement</h2>
        <div style="display:flex;align-items:center;justify-content:space-between">
          <span style="font-size:.82rem;color:var(--muted)" id="captureStatus">Désactivées</span>
          <div id="captureToggle" onclick="toggleCaptures()" class="toggle-pill"></div>
        </div>
      </div>
      <div class="card">
        <h2>PiP – Fenêtre flottante</h2>
        <p style="font-size:.78rem;color:var(--muted);margin-bottom:10px">
          Lance la vidéo dans une fenêtre Picture-in-Picture redimensionnable, toujours au-dessus.
        </p>
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
          <label style="font-size:.82rem;color:var(--muted)">Largeur initiale</label>
          <input type="range" id="pipWidth"  min="200" max="900" step="10" value="480"
                 style="flex:1;accent-color:var(--accent)">
          <span id="pipWidthLabel" style="font-size:.78rem;color:var(--muted);width:50px">480 px</span>
        </div>
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
          <label style="font-size:.82rem;color:var(--muted)">Hauteur initiale</label>
          <input type="range" id="pipHeight" min="120" max="600" step="10" value="270"
                 style="flex:1;accent-color:var(--accent)">
          <span id="pipHeightLabel" style="font-size:.78rem;color:var(--muted);width:50px">270 px</span>
        </div>
        <div class="btn-row">
          <button class="btn btn-primary" onclick="openPiPWindow()" id="pipOpenBtn">⧉ Ouvrir PiP</button>
          <button class="btn btn-ghost"   onclick="closePiPWindow()" id="pipCloseBtn" style="display:none">✕ Fermer PiP</button>
        </div>
        <p style="font-size:.72rem;color:var(--muted);margin-top:8px">
          💡 Redimensionnez la fenêtre librement après ouverture.
        </p>
      </div>
    </div>

    <!-- ═══ ONGLET ÉCOUTE ═══ -->
    <div class="tab-content" id="pane-listen">
      <div class="card">
        <h2>Écoute en direct (micro salle)</h2>
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
          <div id="audioIndicator" style="width:10px;height:10px;border-radius:50%;background:#444;flex-shrink:0"></div>
          <span id="audioStatus" style="font-size:.82rem;color:var(--muted)">Non connecté</span>
        </div>
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
          <label style="font-size:.82rem;color:var(--muted);white-space:nowrap">Volume</label>
          <input type="range" id="listenVolume" min="0" max="2" step="0.05" value="1"
                 style="flex:1;accent-color:var(--accent)">
          <span id="volLabel" style="font-size:.78rem;color:var(--muted);width:36px;text-align:right">100%</span>
        </div>
        <div class="btn-row">
          <button class="btn btn-primary" id="btnListen" onclick="toggleListen()">🎧 Écouter</button>
        </div>
      </div>
    </div>

  </div><!-- .ctrl-panel -->
</div><!-- .layout -->

<!-- ── Modal Renommer MP3 ── -->
<div class="modal-overlay" id="renameModal">
  <div class="modal-box">
    <h3>✎ Renommer le fichier audio</h3>
    <input type="text" id="renameOld" readonly style="color:var(--muted);margin-bottom:12px">
    <input type="text" id="renameNew" placeholder="Nouveau nom du fichier…">
    <div style="font-size:.75rem;color:var(--muted);margin-bottom:10px">
      Le libellé affiché peut être différent du nom de fichier.
    </div>
    <input type="text" id="renameAlias" placeholder="Libellé affiché (optionnel)…">
    <div class="modal-btns">
      <button class="btn btn-ghost"   onclick="closeRenameModal()">Annuler</button>
      <button class="btn btn-primary" onclick="confirmRename()">Renommer</button>
    </div>
  </div>
</div>

<div id="toast"></div>

<script>
const SERVER = 'http://{ip}:5000';

// ══════════════════════════════════════════════
//  ONGLETS
// ══════════════════════════════════════════════
function switchTab(name) {{
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(p => p.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  document.getElementById('pane-' + name).classList.add('active');
  if (name === 'timer') {{ startTimerClock(); loadTimerStatus(); }}
  if (name === 'mp3') loadMP3List();
}}

// ══════════════════════════════════════════════
//  TOAST
// ══════════════════════════════════════════════
function toast(msg, type='ok') {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'show ' + type;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.className = '', 3000);
}}

// ══════════════════════════════════════════════
//  FLUX VIDÉO
// ══════════════════════════════════════════════
const feed = document.getElementById('videoFeed');
feed.onerror = () => {{ feed.src = SERVER + '/video_feed?t=' + Date.now(); }};
setInterval(() => {{ feed.src = SERVER + '/video_feed?t=' + Date.now(); }}, 30000);

// ── PiP (Picture-in-Picture via window popup) ──
let pipWin = null;

function openPiPWindow() {{
  const w = parseInt(document.getElementById('pipWidth').value);
  const h = parseInt(document.getElementById('pipHeight').value);
  const left = window.screen.width  - w - 20;
  const top  = window.screen.height - h - 60;
  pipWin = window.open('', 'jvo_pip',
    `width=${{w}},height=${{h}},left=${{left}},top=${{top}},` +
    `resizable=yes,scrollbars=no,status=no,menubar=no,toolbar=no`);
  if (!pipWin) {{
    toast('Autorisez les popups pour ce site puis réessayez.', 'err');
    return;
  }}
  pipWin.document.write(`<!DOCTYPE html><html>
<head><title>JVO – PiP</title>
<style>*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#000;display:flex;align-items:center;justify-content:center;height:100vh;overflow:hidden}}
img{{width:100%;height:100%;object-fit:contain}}</style></head>
<body><img src="${{SERVER}}/video_feed" id="pipImg"></body></html>`);
  pipWin.document.close();
  pipWin.onbeforeunload = () => {{
    pipWin = null;
    document.getElementById('pipOpenBtn').style.display  = '';
    document.getElementById('pipCloseBtn').style.display = 'none';
    document.getElementById('pipBtn').textContent = '⧉ Mode PiP';
  }};
  document.getElementById('pipOpenBtn').style.display  = 'none';
  document.getElementById('pipCloseBtn').style.display = '';
  document.getElementById('pipBtn').textContent = '✕ Fermer PiP';
  toast('✓ Fenêtre PiP ouverte');
}}

function closePiPWindow() {{
  if (pipWin && !pipWin.closed) pipWin.close();
  pipWin = null;
  document.getElementById('pipOpenBtn').style.display  = '';
  document.getElementById('pipCloseBtn').style.display = 'none';
  document.getElementById('pipBtn').textContent = '⧉ Mode PiP';
}}

function togglePiP() {{
  if (pipWin && !pipWin.closed) closePiPWindow();
  else openPiPWindow();
}}

document.getElementById('pipWidth').addEventListener('input', function() {{
  document.getElementById('pipWidthLabel').textContent = this.value + ' px';
}});
document.getElementById('pipHeight').addEventListener('input', function() {{
  document.getElementById('pipHeightLabel').textContent = this.value + ' px';
}});

// ══════════════════════════════════════════════
//  TTS
// ══════════════════════════════════════════════
async function sendTTS() {{
  const text = document.getElementById('ttsText').value.trim();
  if (!text) {{ toast('Aucun texte saisi', 'err'); return; }}
  try {{
    const r = await fetch(SERVER + '/tts', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{text}})
    }});
    const d = await r.json();
    if (d.status === 'ok') toast('✓ Message envoyé à la salle');
    else toast('Erreur: ' + d.message, 'err');
  }} catch(e) {{ toast('Connexion impossible', 'err'); }}
}}
document.getElementById('ttsText').addEventListener('keydown', e => {{
  if (e.ctrlKey && e.key === 'Enter') sendTTS();
}});

async function loadVoices() {{
  try {{
    const r = await fetch(SERVER + '/voices');
    const d = await r.json();
    const sel = document.getElementById('voiceSelect');
    sel.innerHTML = '';
    d.voices.forEach(v => {{
      const o = document.createElement('option');
      o.value = v.id; o.textContent = v.label;
      if (v.id === d.current) o.selected = true;
      sel.appendChild(o);
    }});
  }} catch(e) {{ console.error('loadVoices', e); }}
}}
async function setVoice(id) {{
  if (!id) return;
  try {{
    const r = await fetch(SERVER + '/set_voice', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{voice: id}})
    }});
    const d = await r.json();
    if (d.status === 'ok') toast('Voix : ' + id.split('-').slice(2).join(' '));
    else toast('Erreur voix', 'err');
  }} catch(e) {{ toast('Connexion impossible','err'); }}
}}

// ── Phrases rapides ──
function buildQuickBtns(phrases) {{
  const wrap = document.getElementById('quickBtns');
  wrap.innerHTML = '';
  phrases.forEach(p => {{
    const row = document.createElement('div');
    row.className = 'quick-item';
    const btn = document.createElement('button');
    btn.className = 'quick-btn';
    btn.textContent = '🔊 ' + p.text; btn.title = p.text;
    btn.onclick = () => {{ document.getElementById('ttsText').value = p.text; sendTTS(); }};
    const del = document.createElement('button');
    del.className = 'quick-del'; del.title = 'Supprimer'; del.textContent = '✕';
    del.onclick = () => deletePhrase(p.id);
    row.appendChild(btn); row.appendChild(del);
    wrap.appendChild(row);
  }});
}}
async function loadPhrases() {{
  try {{
    const r = await fetch(SERVER + '/phrases');
    const d = await r.json();
    buildQuickBtns(d.phrases);
  }} catch(e) {{ console.error('loadPhrases', e); }}
}}
async function addPhrase() {{
  const inp  = document.getElementById('newPhrase');
  const text = inp.value.trim();
  if (!text) {{ toast('Phrase vide', 'err'); return; }}
  try {{
    const r = await fetch(SERVER + '/phrases', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{text}})
    }});
    const d = await r.json();
    if (d.status === 'ok') {{ inp.value = ''; buildQuickBtns(d.phrases); toast('Phrase ajoutée'); }}
    else toast('Erreur', 'err');
  }} catch(e) {{ toast('Connexion impossible','err'); }}
}}
async function deletePhrase(id) {{
  try {{
    const r = await fetch(SERVER + '/phrases/' + id, {{method:'DELETE'}});
    const d = await r.json();
    if (d.status === 'ok') {{ buildQuickBtns(d.phrases); toast('Phrase supprimée'); }}
  }} catch(e) {{ toast('Connexion impossible','err'); }}
}}

// ══════════════════════════════════════════════
//  MP3 – LISTE AVEC DRAG & DROP + RENOMMER + SUPPRIMER
// ══════════════════════════════════════════════
let mp3Labels = {{}};
let mp3Order  = [];
let dragSrc   = null;

async function loadMP3List() {{
  try {{
    const [rFiles, rLabels] = await Promise.all([
      fetch(SERVER + '/list_mp3'),
      fetch(SERVER + '/mp3_labels'),
    ]);
    const dFiles  = await rFiles.json();
    const dLabels = await rLabels.json();
    mp3Labels = dLabels.labels || {{}};
    const files = dFiles.files || [];
    mp3Order = files;
    buildMP3List(files);
  }} catch(e) {{ console.error(e); }}
}}

function buildMP3List(files) {{
  const ul = document.getElementById('mp3List');
  ul.innerHTML = '';
  if (!files.length) {{
    ul.innerHTML = '<li style="color:var(--muted);font-size:.82rem">Aucun fichier audio</li>';
    return;
  }}
  files.forEach((f, idx) => {{
    const li = document.createElement('li');
    li.className = 'mp3-item';
    li.draggable  = true;
    li.dataset.file = f;

    const alias = mp3Labels[f] || '';
    li.innerHTML = `
      <div class="mp3-row1">
        <span class="mp3-handle" title="Glisser pour réordonner">☰</span>
        <div style="flex:1;overflow:hidden">
          <div class="mp3-label" title="${{f}}">${{alias || f}}</div>
          ${{alias ? `<div class="mp3-alias">${{f}}</div>` : ''}}
        </div>
      </div>
      <div class="mp3-row2">
        <button class="btn btn-success" onclick="playMP3('${{f}}')" style="font-size:.75rem;padding:4px 10px">▶ Jouer</button>
        <button class="btn btn-ghost"   onclick="openRenameModal('${{f}}')" style="font-size:.75rem;padding:4px 9px">✎ Renommer</button>
        <button class="btn btn-danger"  onclick="deleteMP3('${{f}}')" style="font-size:.75rem;padding:4px 9px">🗑</button>
      </div>`;

    // Drag & drop
    li.addEventListener('dragstart', e => {{
      dragSrc = li;
      li.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
    }});
    li.addEventListener('dragend',  () => {{ li.classList.remove('dragging'); }});
    li.addEventListener('dragover', e => {{
      e.preventDefault(); e.dataTransfer.dropEffect = 'move';
      ul.querySelectorAll('.mp3-item').forEach(i => i.classList.remove('drag-over'));
      li.classList.add('drag-over');
    }});
    li.addEventListener('dragleave', () => li.classList.remove('drag-over'));
    li.addEventListener('drop', e => {{
      e.preventDefault();
      li.classList.remove('drag-over');
      if (dragSrc && dragSrc !== li) {{
        const items = [...ul.querySelectorAll('.mp3-item')];
        const srcIdx  = items.indexOf(dragSrc);
        const destIdx = items.indexOf(li);
        if (srcIdx < destIdx) ul.insertBefore(dragSrc, li.nextSibling);
        else                   ul.insertBefore(dragSrc, li);
        saveMP3Order();
      }}
    }});

    ul.appendChild(li);
  }});
}}

async function saveMP3Order() {{
  const order = [...document.querySelectorAll('#mp3List .mp3-item')].map(li => li.dataset.file);
  try {{
    await fetch(SERVER + '/mp3_order', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{order}})
    }});
    toast('✓ Ordre sauvegardé');
  }} catch(e) {{ toast('Erreur sauvegarde ordre', 'err'); }}
}}

async function playMP3(filename) {{
  try {{
    const r = await fetch(SERVER + '/play_mp3', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{filename}})
    }});
    const d = await r.json();
    if (d.status === 'ok') toast('▶ ' + (mp3Labels[filename] || filename));
    else toast('Erreur: ' + d.message, 'err');
  }} catch(e) {{ toast('Connexion impossible', 'err'); }}
}}

async function stopAudio() {{
  try {{
    await fetch(SERVER + '/stop_audio', {{method:'POST'}});
    toast('■ Audio arrêté');
  }} catch(e) {{ toast('Connexion impossible', 'err'); }}
}}

async function deleteMP3(filename) {{
  if (!confirm('Supprimer « ' + (mp3Labels[filename] || filename) + ' » ?')) return;
  try {{
    const r = await fetch(SERVER + '/delete_mp3', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{filename}})
    }});
    const d = await r.json();
    if (d.status === 'ok') {{ toast('🗑 Supprimé : ' + filename); loadMP3List(); }}
    else toast('Erreur : ' + d.message, 'err');
  }} catch(e) {{ toast('Connexion impossible', 'err'); }}
}}

// ── Modal Renommer ──
let _renameTarget = '';
function openRenameModal(filename) {{
  _renameTarget = filename;
  document.getElementById('renameOld').value   = filename;
  document.getElementById('renameNew').value   = filename;
  document.getElementById('renameAlias').value = mp3Labels[filename] || '';
  document.getElementById('renameModal').classList.add('open');
  setTimeout(() => document.getElementById('renameAlias').focus(), 50);
}}
function closeRenameModal() {{
  document.getElementById('renameModal').classList.remove('open');
}}
async function confirmRename() {{
  const oldName  = _renameTarget;
  const newName  = document.getElementById('renameNew').value.trim();
  const alias    = document.getElementById('renameAlias').value.trim();
  let changed = false;

  // Renommer le fichier si le nom a changé
  if (newName && newName !== oldName) {{
    try {{
      const r = await fetch(SERVER + '/rename_mp3', {{
        method:'POST', headers:{{'Content-Type':'application/json'}},
        body: JSON.stringify({{old_name: oldName, new_name: newName}})
      }});
      const d = await r.json();
      if (d.status !== 'ok') {{ toast('Erreur renommage : ' + d.message, 'err'); return; }}
      changed = true;
    }} catch(e) {{ toast('Connexion impossible', 'err'); return; }}
  }}

  // Enregistrer le libellé (sur le nouveau nom si renommé)
  const targetName = changed ? newName : oldName;
  try {{
    await fetch(SERVER + '/mp3_labels', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{filename: targetName, label: alias}})
    }});
  }} catch(e) {{}}

  closeRenameModal();
  toast('✓ Modifié');
  loadMP3List();
}}

// ── Upload ──
async function uploadMP3(file) {{
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  toast('Envoi de ' + file.name + '…');
  try {{
    const r = await fetch(SERVER + '/upload_mp3', {{ method:'POST', body:fd }});
    const d = await r.json();
    if (d.status === 'ok') {{ toast('✓ ' + d.filename + ' uploadé'); loadMP3List(); }}
    else toast('Erreur upload: ' + d.message, 'err');
  }} catch(e) {{ toast('Connexion impossible', 'err'); }}
}}
const dz = document.getElementById('dropZone');
dz.addEventListener('dragover',  e => {{ e.preventDefault(); dz.style.borderColor='var(--accent)'; }});
dz.addEventListener('dragleave', () => {{ dz.style.borderColor=''; }});
dz.addEventListener('drop', e => {{
  e.preventDefault(); dz.style.borderColor='';
  const f = e.dataTransfer.files[0];
  if (f) uploadMP3(f);
}});

// ══════════════════════════════════════════════
//  TIMER VGT
// ══════════════════════════════════════════════
let _timerClockInterval = null;

function startTimerClock() {{
  if (_timerClockInterval) return;
  _timerClockInterval = setInterval(() => {{
    const now = new Date();
    document.getElementById('timerClock').textContent =
      now.toLocaleTimeString('fr-FR', {{hour:'2-digit',minute:'2-digit',second:'2-digit'}});
  }}, 500);
}}

async function loadTimerStatus() {{
  try {{
    const r = await fetch(SERVER + '/timer/status');
    const d = await r.json();
    applyTimerState(d.enabled);
    buildTimerTable(d.schedule || []);
    buildTimerLog(d.log || []);
  }} catch(e) {{ console.error('timer status', e); }}
}}

function applyTimerState(enabled) {{
  const pill  = document.getElementById('timerPill');
  const badge = document.getElementById('timerBadge');
  pill.classList.toggle('on', enabled);
  badge.textContent = enabled ? 'ON' : 'OFF';
  badge.className   = 'timer-badge ' + (enabled ? 'on' : 'off');
}}

async function timerToggle() {{
  try {{
    const r = await fetch(SERVER + '/timer/toggle', {{method:'POST'}});
    const d = await r.json();
    applyTimerState(d.enabled);
    toast(d.enabled ? '⏱ Timer activé' : '⏱ Timer désactivé');
  }} catch(e) {{ toast('Erreur', 'err'); }}
}}

function buildTimerTable(schedule) {{
  const tbody = document.getElementById('timerBody');
  tbody.innerHTML = '';
  schedule.forEach((row, i) => {{
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input type="text" value="${{row.time}}" placeholder="HH:MM"
                 style="width:68px" data-i="${{i}}" data-field="time"></td>
      <td><input type="text" value="${{row.file}}" placeholder="fichier.mp3"
                 style="width:120px" data-i="${{i}}" data-field="file"></td>
      <td><button class="timer-del" onclick="timerDelRow(${{i}})">✕</button></td>`;
    tbody.appendChild(tr);
  }});
}}

function buildTimerLog(logs) {{
  const el = document.getElementById('timerLog');
  if (!logs.length) {{
    el.innerHTML = '<span style="color:var(--muted)">Aucun rappel aujourd\'hui.</span>';
    return;
  }}
  el.innerHTML = logs.slice().reverse()
    .map(l => `<div><span style="color:var(--accent2)">${{l.ts}}</span> → ${{l.file}}</div>`)
    .join('');
}}

function timerGetSchedule() {{
  const rows = document.querySelectorAll('#timerBody tr');
  return [...rows].map(tr => {{
    const inputs = tr.querySelectorAll('input');
    return {{ time: inputs[0].value.trim(), file: inputs[1].value.trim() }};
  }}).filter(r => r.time && r.file);
}}

async function timerSave() {{
  const schedule = timerGetSchedule();
  try {{
    const r = await fetch(SERVER + '/timer/schedule', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{schedule}})
    }});
    const d = await r.json();
    if (d.status === 'ok') toast('✓ Planning sauvegardé');
    else toast('Erreur', 'err');
  }} catch(e) {{ toast('Connexion impossible', 'err'); }}
}}

async function timerReset() {{
  if (!confirm('Réinitialiser le planning par défaut ?')) return;
  try {{
    const r = await fetch(SERVER + '/timer/reset', {{method:'POST'}});
    const d = await r.json();
    buildTimerTable(d.schedule || []);
    toast('↺ Planning réinitialisé');
  }} catch(e) {{ toast('Erreur', 'err'); }}
}}

function timerAddRow() {{
  const schedule = timerGetSchedule();
  schedule.push({{time: '', file: ''}});
  buildTimerTable(schedule);
  // Focus sur la nouvelle ligne
  const inputs = document.querySelectorAll('#timerBody tr:last-child input');
  if (inputs[0]) inputs[0].focus();
}}

function timerDelRow(i) {{
  const schedule = timerGetSchedule();
  schedule.splice(i, 1);
  buildTimerTable(schedule);
}}

async function timerFiredReset() {{
  try {{
    await fetch(SERVER + '/timer/fired_reset', {{method:'POST'}});
    toast('↺ Sonneries réarmées pour cette session');
  }} catch(e) {{ toast('Erreur', 'err'); }}
}}

// Rafraîchir le log toutes les 30s si onglet timer actif
setInterval(() => {{
  if (document.getElementById('pane-timer').classList.contains('active')) {{
    fetch(SERVER + '/timer/status').then(r=>r.json()).then(d => buildTimerLog(d.log||[])).catch(()=>{{}});
  }}
}}, 30000);

// ══════════════════════════════════════════════
//  CAMÉRA : qualité + captures
// ══════════════════════════════════════════════
const QUALITY_LABELS = {{
  hd:     'HD 960×540 · ~13 Mbit/s',
  medium: 'Moyen 640×360 · ~4 Mbit/s',
  low:    'Éco 480×270 · ~1 Mbit/s',
}};
async function setQuality(q) {{
  try {{
    const r = await fetch(SERVER + '/set_quality', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{quality: q}})
    }});
    const d = await r.json();
    if (d.status === 'ok') {{
      ['hd','medium','low'].forEach(k =>
        document.getElementById('q-' + k).className = 'btn ' + (k===q ? 'btn-success' : 'btn-ghost'));
      document.getElementById('qualityLabel').textContent = QUALITY_LABELS[q];
      toast('✓ Qualité : ' + QUALITY_LABELS[q]);
    }}
  }} catch(e) {{ toast('Erreur qualité', 'err'); }}
}}
(async () => {{
  try {{
    const r = await fetch(SERVER + '/get_quality');
    const d = await r.json();
    ['hd','medium','low'].forEach(k =>
      document.getElementById('q-' + k).className = 'btn ' + (k===d.quality ? 'btn-success' : 'btn-ghost'));
    document.getElementById('qualityLabel').textContent = QUALITY_LABELS[d.quality] || d.label;
  }} catch(e) {{}}
}})();

let capturesEnabled = false;
async function toggleCaptures() {{
  capturesEnabled = !capturesEnabled;
  try {{
    await fetch(SERVER + '/set_captures', {{
      method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{enabled: capturesEnabled}})
    }});
    const tog   = document.getElementById('captureToggle');
    const label = document.getElementById('captureStatus');
    tog.classList.toggle('on', capturesEnabled);
    label.textContent = capturesEnabled ? 'Activées' : 'Désactivées';
    toast(capturesEnabled ? '✓ Captures activées' : 'Captures désactivées');
  }} catch(e) {{ toast('Erreur', 'err'); }}
}}

// ══════════════════════════════════════════════
//  ÉCOUTE MICRO EN DIRECT
// ══════════════════════════════════════════════
let audioCtx = null, gainNode = null, audioSSE = null, listening = false;
let sampleRate = 44100, nextTime = 0;
const AHEAD_SEC = 0.10;

document.getElementById('listenVolume').addEventListener('input', function() {{
  document.getElementById('volLabel').textContent = Math.round(this.value*100) + '%';
  if (gainNode) gainNode.gain.value = parseFloat(this.value);
}});
function setAudioStatus(text, color) {{
  document.getElementById('audioStatus').textContent = text;
  document.getElementById('audioIndicator').style.background = color;
}}
function toggleListen() {{ listening ? stopListen() : startListen(); }}
function startListen() {{
  if (listening) return;
  listening = true;
  document.getElementById('btnListen').textContent = '⏹ Arrêter';
  document.getElementById('btnListen').className   = 'btn btn-danger';
  setAudioStatus('Ouverture du micro…', '#f0a500');
  fetch(SERVER + '/mic_start', {{method:'POST'}}).catch(()=>{{}});
  audioCtx = new (window.AudioContext || window.webkitAudioContext)({{ sampleRate }});
  gainNode = audioCtx.createGain();
  gainNode.gain.value = parseFloat(document.getElementById('listenVolume').value);
  gainNode.connect(audioCtx.destination);
  nextTime = audioCtx.currentTime + AHEAD_SEC;
  audioSSE = new EventSource(SERVER + '/audio_stream');
  audioSSE.addEventListener('config', e => {{
    const cfg = JSON.parse(e.data); sampleRate = cfg.sampleRate;
    if (audioCtx.sampleRate !== sampleRate) {{
      audioCtx.close();
      audioCtx = new (window.AudioContext || window.webkitAudioContext)({{ sampleRate }});
      gainNode = audioCtx.createGain();
      gainNode.gain.value = parseFloat(document.getElementById('listenVolume').value);
      gainNode.connect(audioCtx.destination);
      nextTime = audioCtx.currentTime + AHEAD_SEC;
    }}
    setAudioStatus('🔴 Micro en direct', '#3ecf8e');
  }});
  audioSSE.onmessage = e => {{
    if (!audioCtx || !gainNode) return;
    try {{
      const binStr = atob(e.data);
      const bytes  = new Uint8Array(binStr.length);
      for (let i=0; i<binStr.length; i++) bytes[i] = binStr.charCodeAt(i);
      const pcm16   = new Int16Array(bytes.buffer);
      const float32 = new Float32Array(pcm16.length);
      for (let i=0; i<pcm16.length; i++) float32[i] = pcm16[i] / 32768.0;
      const buf = audioCtx.createBuffer(1, float32.length, sampleRate);
      buf.copyToChannel(float32, 0);
      const src = audioCtx.createBufferSource();
      src.buffer = buf; src.connect(gainNode);
      const now = audioCtx.currentTime;
      if (nextTime < now + 0.01) nextTime = now + AHEAD_SEC;
      src.start(nextTime); nextTime += buf.duration;
    }} catch(err) {{ console.warn('[Audio]', err); }}
  }};
  audioSSE.onerror = () => {{ if (listening) setAudioStatus('⚠ Reconnexion…', '#e35b5b'); }};
}}
function stopListen() {{
  listening = false;
  if (audioSSE)  {{ audioSSE.close();  audioSSE = null; }}
  if (audioCtx)  {{ audioCtx.close();  audioCtx = null; gainNode = null; }}
  nextTime = 0;
  fetch(SERVER + '/mic_stop', {{method:'POST'}}).catch(()=>{{}});
  document.getElementById('btnListen').textContent = '🎧 Écouter';
  document.getElementById('btnListen').className   = 'btn btn-primary';
  setAudioStatus('Micro fermé', '#444');
}}

// ══════════════════════════════════════════════
//  INIT
// ══════════════════════════════════════════════
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