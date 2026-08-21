"""
═══════════════════════════════════════════════════════════════════════════
  P.I.G.E. — Programme Intelligent de Guet et d'Écoute
  Surveillance 24/24 d'un couple de pigeons ramiers, corniche de la médiathèque
═══════════════════════════════════════════════════════════════════════════
 
Caméra visée : Logitech C270 HD 720p (webcam USB standard, gérée nativement
par OpenCV/DirectShow — aucun pilote particulier à installer).
Python recommandé : 3.12 (voir requirements.txt et install_pige.bat).
 
  - Flux vidéo en direct (webcam USB, OpenCV/DirectShow)
  - Détection de mouvement (seuil abaissé : un oiseau est bien plus petit
    qu'une silhouette humaine — à réajuster selon la distance caméra↔nid)
  - Captures d'images déclenchées par le mouvement (nourrissage, couvaison…)
  - Snapshot à la demande + galerie
  - Écoute audio en direct (micro de la caméra → navigateur), utile pour
    entendre les cris/pépiements si la caméra est bien positionnée près du nid
  - Protection par mot de passe optionnelle, tunnel ngrok optionnel
  - Contrôle de la qualité vidéo (bande passante)
  - Boucle de capture caméra indépendante des visiteurs de la page web :
    dans le script original, chaque connexion au flux vidéo relançait sa
    propre lecture caméra — si personne ne regardait la page, rien n'était
    enregistré. Ici, une unique boucle tourne en arrière-plan en permanence
    et alimente le flux, les captures et le timelapse, que quelqu'un
    regarde ou non.
  - Timelapse : une image capturée à intervalle régulier (1/minute par
    défaut), avec génération à la demande d'une vidéo timelapse par journée.
  - Journal d'activité (horodatage des détections de mouvement).
 
CONFIGURATION (fichier ngrok_token.env à côté de pige.py, toutes les clés sont
optionnelles) :
  PIGE_PASSWORD          mot de passe de l'interface web (vide = accès libre, LAN uniquement)
  FLASK_SECRET_KEY       clé de session Flask (générée aléatoirement sinon)
  NGROK_TOKEN            jeton ngrok pour un accès distant (nécessite ngrok.exe à côté du script)
  PIGE_NETWORK_HTML_DIR  dossier réseau où déposer pige.html (par défaut : le dossier
                         "ESPACE_SCI" de la médiathèque, voir DEFAULT_NETWORK_HTML_DIR
                         plus bas dans le code ; repli en local si inaccessible)
 
DÉPENDANCES PYTHON :
  pip install opencv-contrib-python flask numpy python-dotenv sounddevice
  (opencv-contrib-python n'est plus indispensable pour la reconnaissance
  faciale ici, mais opencv-python suffit largement — la version "contrib"
  ne pose pas de problème si déjà installée.)
"""
 
import cv2
import re
import flask
import numpy as np
import datetime
import os
from pathlib import Path
import time
import socket
import threading
import sounddevice as sd
import queue
import base64
import json
import logging
import traceback
import sys
import secrets
import shutil
import webbrowser
from flask import (
    Response, request, jsonify, stream_with_context,
    session, redirect, url_for, send_file
)
from functools import wraps
 
# ── Variables d'environnement (ngrok_token.env local, jamais committé) ───────
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ngrok_token.env'))
except ImportError:
    pass  # python-dotenv optionnel — fonctionne sans si variables déjà dans l'env
 
# ─────────────────────────────────────────────
#  SYSTÈME DE LOGS
#  Écrit dans la console ET dans pige_debug.log
#  (dans le même dossier que ce script)
# ─────────────────────────────────────────────
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pige_debug.log")
 
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8", mode="w"),  # écrase à chaque démarrage
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("NICHOIR")
log.info(f"=== Démarrage — logs dans : {LOG_FILE} ===")
 
# Intercepte toutes les exceptions non catchées
def _handle_uncaught(exc_type, exc_value, exc_tb):
    log.critical("EXCEPTION NON CATCHÉE !", exc_info=(exc_type, exc_value, exc_tb))
sys.excepthook = _handle_uncaught
 
app = flask.Flask(__name__)
ngrok_public_url = None   # rempli au démarrage si NGROK_TOKEN présent
 
# Clé de session Flask (générée aléatoirement au démarrage si absente de ngrok_token.env)
app.secret_key = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32)
 
# Mot de passe de l'interface (lu depuis ngrok_token.env — NE PAS mettre en dur ici)
APP_PASSWORD = os.environ.get('PIGE_PASSWORD', '')
 
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
#  ÉCOUTE AUDIO EN TEMPS RÉEL (SSE)
#  Capture le micro de la caméra (utile pour entendre les oiseaux si la
#  caméra est proche du nid) et le diffuse aux clients web via
#  Server-Sent Events + Web Audio API.
# ─────────────────────────────────────────────
AUDIO_SAMPLERATE = 44100   # Hz
AUDIO_CHANNELS   = 1       # Mono
AUDIO_CHUNK      = 4096    # ~93 ms par trame à 44100 Hz
 
audio_clients      = []
audio_clients_lock = threading.Lock()
 
def _audio_callback(indata, frames, time_info, status):
    """Reçoit chaque bloc micro et le pousse vers tous les clients SSE.
    IMPORTANT : pas d'allocation lourde ici - thread temps-réel."""
    if status:
        log.warning(f"[MICRO] sounddevice status : {status}")
    try:
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
      1. Micro de la webcam (Logitech ou autre)
      2. Tout autre micro USB
      3. Micro par défaut du système (None)
    """
    devices = sd.query_devices()
    print("\n[MICRO] Périphériques d'entrée disponibles :")
    for i, d in enumerate(devices):
        if d['max_input_channels'] > 0:
            print(f"  [{i}] {d['name']}  (ch={d['max_input_channels']}, sr={int(d['default_samplerate'])})")
 
    for i, d in enumerate(devices):
        name = d['name'].lower()
        if d['max_input_channels'] > 0 and ('logitech' in name or 'c920' in name or 'c270' in name or 'webcam' in name):
            print(f"[MICRO] Webcam trouvée : {d['name']} (idx {i})")
            return i
 
    for i, d in enumerate(devices):
        name = d['name'].lower()
        if d['max_input_channels'] > 0 and 'usb' in name:
            print(f"[MICRO] Micro USB trouvé : {d['name']} (idx {i})")
            return i
 
    print("[MICRO] Aucun micro USB/webcam trouvé, utilisation du micro par défaut.")
    return None
 
_mic_stream      = None   # instance sd.InputStream active
_mic_stream_lock = threading.Lock()
mic_active       = False  # état courant
 
def mic_start():
    """Ouvre le micro et démarre la capture. Appelé uniquement à la demande."""
    global _mic_stream, mic_active
    with _mic_stream_lock:
        if mic_active:
            return True
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
#  QUALITÉ VIDÉO — modifiable à chaud via /set_quality
# ─────────────────────────────────────────────
QUALITY_PRESETS = {
    "hd":     {"res": (960, 540), "jpeg": 80, "fps_div": 1, "label": "HD  960×540 q80 ~13 Mbit/s"},
    "medium": {"res": (640, 360), "jpeg": 65, "fps_div": 1, "label": "Moyen 640×360 q65 ~4 Mbit/s"},
    "low":    {"res": (480, 270), "jpeg": 50, "fps_div": 2, "label": "Éco  480×270 q50 ~1 Mbit/s"},
}
stream_quality = "medium"   # défaut économique
 
# ─────────────────────────────────────────────
#  CAMÉRA
# ─────────────────────────────────────────────
class RobustCamera:
    def __init__(self):
        self.cap = None
        self.backend = cv2.CAP_DSHOW
        self._lock = threading.Lock()  # empêche les race conditions multi-threads
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
            except Exception:
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
        with self._lock:
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
    except Exception:
        return "127.0.0.1"
 
 
# Dossier réseau par défaut où déposer pige.html (médiathèque — Espace Sciences
# et Société). Modifiable sans toucher au code via PIGE_NETWORK_HTML_DIR dans
# ngrok_token.env, si ce chemin venait à changer.
DEFAULT_NETWORK_HTML_DIR = r"L:\Groups\mediatheque\02- GESTION COLLECTIONS\07-SECTEUR SCIENCES ET SOCIETE\ESPACE_SCI"
 
def save_html_file():
    """
    Génère un fichier pige.html qui redirige simplement vers http://IP:5000.
    Ainsi, depuis n'importe quel poste du LAN, ouvrir pige.html ouvre
    l'interface complète servie par Flask — sans problème de sécurité file://.
    Le dossier réseau de destination est DEFAULT_NETWORK_HTML_DIR ci-dessus ;
    PIGE_NETWORK_HTML_DIR dans ngrok_token.env permet de le remplacer sans
    toucher au code. Si le chemin choisi est inaccessible (lecteur réseau non monté...),
    le fichier est écrit en local à côté du script, en repli.
    """
    ip_address = get_local_ip()
    print(f"Adresse IP détectée: {ip_address}")
    server_url = f"http://{ip_address}:5000"
 
    html_content = f'''<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="0; url={server_url}">
  <title>Redirection P.I.G.E.…</title>
</head>
<body>
  <p>Redirection vers <a href="{server_url}">{server_url}</a>…</p>
  <script>window.location.replace("{server_url}");</script>
</body>
</html>'''
 
    destination_path = os.environ.get('PIGE_NETWORK_HTML_DIR', '').strip() or DEFAULT_NETWORK_HTML_DIR
    if not os.path.exists(destination_path):
        print(f"Chemin réseau inaccessible ({destination_path}), sauvegarde locale.")
        destination_path = "."
 
    html_file_path = os.path.join(destination_path, "pige.html")
    try:
        with open(html_file_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"Fichier pige.html généré : {html_file_path}")
    except Exception as e:
        print(f"Impossible d'écrire pige.html : {e}")
 
 
# ─────────────────────────────────────────────
#  INITIALISATION
# ─────────────────────────────────────────────
camera = RobustCamera()
motion_detected  = False
last_frame       = None
_latest_raw_frame    = None   # dernière frame brute (pour snapshot / timelapse)
_latest_stream_frame  = None  # dernière frame à diffuser (annotée si mouvement)
motion_threshold = 700        # abaissé vs script salle : un oiseau est petit — à ajuster selon le cadrage
capture_count    = 0
MAX_CAPTURES     = 400        # surveillance 24/24 → plus de place que pour une salle
SAVE_CAPTURES    = True       # activé par défaut : on veut les événements du nid dès le démarrage
 
user_profile = os.environ.get('USERPROFILE', os.path.expanduser('~'))
motion_captures_dir = os.path.join(user_profile, 'Pictures', 'pige', 'captures')
os.makedirs(motion_captures_dir, exist_ok=True)
 
 
_capture_queue = queue.Queue(maxsize=10)
 
def _capture_writer():
    """Thread dédié écriture captures disque - ne bloque jamais le flux."""
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
            filename  = f"nid_{timestamp}.jpg"
            file_path = os.path.join(motion_captures_dir, filename)
            small = cv2.resize(frame, (640, 360))
            cv2.imwrite(file_path, small, [cv2.IMWRITE_JPEG_QUALITY, 80])
            capture_count += 1
            log.debug(f"[CAPTURE] Sauvegarde : {filename}")
        except Exception as e:
            log.error(f"[CAPTURE] Erreur écriture : {e}")
 
threading.Thread(target=_capture_writer, daemon=True).start()
 
 
def save_capture(frame):
    """Enfile la capture pour écriture asynchrone - ne bloque jamais le flux."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    try:
        _capture_queue.put_nowait((frame.copy(), timestamp))
    except queue.Full:
        log.warning("[CAPTURE] File pleine, capture ignorée")
    return None
 
 
def detect_motion(current_frame):
    """Détection de mouvement générique par différence d'image.
    Le seuil (motion_threshold) est volontairement plus bas que dans le
    script salle car un pigeon occupe une surface bien plus faible qu'une
    personne — à réajuster à l'usage (trop bas = faux positifs sur les
    variations de lumière, trop haut = petits mouvements ignorés)."""
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
    is_motion = False
    output_frame = current_frame.copy()
    for contour in contours:
        if cv2.contourArea(contour) > motion_threshold:
            is_motion = True
            (x, y, w, h) = cv2.boundingRect(contour)
            x, y, w, h = x*2, y*2, w*2, h*2
            cv2.rectangle(output_frame, (x, y), (x + w, y + h), (0, 255, 0), 3)
            cv2.putText(output_frame, "MOUVEMENT", (10, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3)
    last_frame = gray
    motion_detected = is_motion
    return is_motion, output_frame
 
 
# ─────────────────────────────────────────────
#  JOURNAL D'ACTIVITÉ (détections de mouvement)
# ─────────────────────────────────────────────
_activity_log       = []
_activity_lock       = threading.Lock()
MAX_ACTIVITY_LOG     = 50
 
def _log_activity(kind: str):
    with _activity_lock:
        _activity_log.insert(0, {
            "time": datetime.datetime.now().strftime("%d/%m %H:%M:%S"),
            "type": kind,
        })
        del _activity_log[MAX_ACTIVITY_LOG:]
 
 
# ─────────────────────────────────────────────
#  TIMELAPSE
#  Capture régulière d'une image, indépendamment du mouvement, pour
#  reconstituer plus tard l'activité de la journée (couvaison, relèves,
#  éclosion, envol...).
# ─────────────────────────────────────────────
TIMELAPSE_DIR = os.path.join(user_profile, 'Pictures', 'pige', 'timelapse')
os.makedirs(TIMELAPSE_DIR, exist_ok=True)
TIMELAPSE_EXPORTS_DIR = os.path.join(TIMELAPSE_DIR, 'exports')
os.makedirs(TIMELAPSE_EXPORTS_DIR, exist_ok=True)
 
TIMELAPSE_ENABLED       = True
TIMELAPSE_INTERVAL_S    = 60     # 1 image / minute par défaut
TIMELAPSE_RETENTION_DAYS = 21    # purge automatique des journées plus anciennes
 
_timelapse_build_lock  = threading.Lock()
_timelapse_build_state = {
    "running": False, "day": None, "progress": 0, "total": 0,
    "done_file": None, "error": None,
}
 
def save_timelapse_frame(frame):
    now = datetime.datetime.now()
    day_dir = os.path.join(TIMELAPSE_DIR, now.strftime("%Y-%m-%d"))
    try:
        os.makedirs(day_dir, exist_ok=True)
        fname = now.strftime("%H%M%S") + ".jpg"
        path  = os.path.join(day_dir, fname)
        small = cv2.resize(frame, (960, 540))
        cv2.imwrite(path, small, [cv2.IMWRITE_JPEG_QUALITY, 78])
    except Exception as e:
        log.warning(f"[TIMELAPSE] Écriture échouée : {e}")
 
def _purge_old_timelapse_days():
    try:
        cutoff = datetime.datetime.now() - datetime.timedelta(days=TIMELAPSE_RETENTION_DAYS)
        for name in os.listdir(TIMELAPSE_DIR):
            full = os.path.join(TIMELAPSE_DIR, name)
            if not os.path.isdir(full) or name == 'exports':
                continue
            try:
                day = datetime.datetime.strptime(name, "%Y-%m-%d")
            except ValueError:
                continue
            if day < cutoff:
                shutil.rmtree(full, ignore_errors=True)
                log.info(f"[TIMELAPSE] Purge ancien dossier : {name}")
    except Exception as e:
        log.warning(f"[TIMELAPSE] Purge : {e}")
 
def _build_timelapse_video(day: str, fps: int = 12):
    """Assemble toutes les images d'une journée en une vidéo mp4 (thread dédié)."""
    global _timelapse_build_state
    day_dir = os.path.join(TIMELAPSE_DIR, day)
    if not os.path.isdir(day_dir):
        _timelapse_build_state.update(running=False, error="Journée introuvable")
        return
    files = sorted(f for f in os.listdir(day_dir) if f.lower().endswith('.jpg'))
    if not files:
        _timelapse_build_state.update(running=False, error="Aucune image pour cette journée")
        return
    out_name = f"nichoir_{day}.mp4"
    out_path = os.path.join(TIMELAPSE_EXPORTS_DIR, out_name)
    first = cv2.imread(os.path.join(day_dir, files[0]))
    if first is None:
        _timelapse_build_state.update(running=False, error="Image illisible")
        return
    h, w = first.shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(out_path, fourcc, fps, (w, h))
    _timelapse_build_state.update(running=True, day=day, progress=0, total=len(files),
                                   done_file=None, error=None)
    try:
        for i, fname in enumerate(files):
            img = cv2.imread(os.path.join(day_dir, fname))
            if img is not None:
                if img.shape[:2] != (h, w):
                    img = cv2.resize(img, (w, h))
                writer.write(img)
            _timelapse_build_state["progress"] = i + 1
        writer.release()
        _timelapse_build_state.update(running=False, done_file=out_name)
        log.info(f"[TIMELAPSE] Vidéo générée : {out_name} ({len(files)} images)")
    except Exception as e:
        writer.release()
        _timelapse_build_state.update(running=False, error=str(e))
        log.error(f"[TIMELAPSE] Erreur génération vidéo : {e}")
 
 
# ─────────────────────────────────────────────
#  BOUCLE DE CAPTURE UNIQUE — 24/24, indépendante des visiteurs de la page
# ─────────────────────────────────────────────
def capture_loop():
    """
    Boucle unique qui lit la caméra en continu, tant que le programme tourne,
    que quelqu'un regarde la page web ou non. C'est elle qui alimente :
      - _latest_stream_frame (servi par /video_feed à tous les clients)
      - la détection de mouvement + les captures d'événements
      - le timelapse
 
    Dans le script original (salle JVO), c'était chaque connexion au flux
    vidéo qui relançait sa propre lecture caméra : viable quand un écran
    reste allumé en permanence sur la page, mais inadapté à une surveillance
    24/24 sans personne devant l'écran.
    """
    global motion_detected, _latest_raw_frame, _latest_stream_frame
    motion_cooldown  = 0
    frame_count      = 0
    last_timelapse   = 0.0
    log.info("[CAPTURE] Boucle de capture 24/24 démarrée")
    while True:
        try:
            success, frame = camera.read()
            if not success or frame is None:
                blank = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(blank, "CAMERA INDISPONIBLE - RECONNEXION...", (30, 240),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                _latest_stream_frame = blank
                time.sleep(0.5)
                continue
 
            frame_count += 1
            _latest_raw_frame = frame
            display_frame = frame
 
            # Détection de mouvement 1 frame sur 2 (comme le script original)
            if frame_count % 2 == 0:
                is_motion, annotated = detect_motion(frame)
                if annotated is not None:
                    display_frame = annotated
                if is_motion and motion_cooldown == 0:
                    _log_activity("mouvement")
                    if SAVE_CAPTURES:
                        log.info("[CAPTURE] Mouvement détecté au nid — capture sauvegardée")
                        save_capture(annotated if annotated is not None else frame)
                    motion_cooldown = 30
            if motion_cooldown > 0:
                motion_cooldown -= 1
 
            _latest_stream_frame = display_frame
 
            # Timelapse : échantillonnage périodique, indépendant du mouvement
            now = time.time()
            if TIMELAPSE_ENABLED and (now - last_timelapse) >= TIMELAPSE_INTERVAL_S:
                last_timelapse = now
                save_timelapse_frame(frame)
                _purge_old_timelapse_days()
 
            if frame_count % 200 == 0:
                log.debug(f"[CAPTURE] {frame_count} frames traitées")
 
            time.sleep(1 / 15)   # ~15 im/s suffit largement pour un nichoir
        except Exception as e:
            log.error(f"[CAPTURE] Exception dans la boucle : {type(e).__name__}: {e}")
            log.debug(traceback.format_exc())
            time.sleep(1)
 
threading.Thread(target=capture_loop, daemon=True).start()
 
 
def generate_frames():
    """Générateur MJPEG servi à chaque client connecté à /video_feed.
    Se contente de relire la dernière frame produite par capture_loop() —
    aucune lecture caméra ici, donc plusieurs visiteurs simultanés ne se
    gênent pas et ne surchargent pas la caméra."""
    log.info("[STREAM] Nouveau client connecté au flux vidéo")
    frame_idx = 0
    try:
        while True:
            frame = _latest_stream_frame
            if frame is None:
                time.sleep(0.1)
                continue
            q = QUALITY_PRESETS[stream_quality]
            frame_idx += 1
            if frame_idx % q["fps_div"] != 0:
                time.sleep(1 / 20)
                continue
            try:
                stream_frame = cv2.resize(frame, q["res"])
                ret, buffer = cv2.imencode('.jpg', stream_frame, [cv2.IMWRITE_JPEG_QUALITY, q["jpeg"]])
                if ret:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            except Exception as e:
                log.error(f"[STREAM] Erreur encodage frame : {e}")
            time.sleep(1 / 20)
    except GeneratorExit:
        log.info("[STREAM] Client déconnecté (GeneratorExit normal)")
    except Exception as e:
        log.error(f"[STREAM] Exception : {type(e).__name__}: {e}")
        log.debug(traceback.format_exc())
 
 
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
        return resp
    except Exception as e:
        log.error(f"[HTTP] Erreur création Response /video_feed: {e}")
        log.debug(traceback.format_exc())
        return Response("Erreur serveur", status=500)
 
 
# ── Snapshot à la demande ────────────────────
SNAPSHOTS_DIR = os.path.join(user_profile, 'Pictures', 'pige', 'snapshots')
os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
MAX_SNAPSHOTS = 50
 
@app.route('/snapshot', methods=['POST'])
@api_auth
def take_snapshot():
    """Capture la frame courante et la sauvegarde."""
    frame = _latest_raw_frame
    if frame is None:
        return jsonify({"status": "error", "message": "Aucune frame disponible"}), 503
    ts       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"snap_{ts}.jpg"
    path     = os.path.join(SNAPSHOTS_DIR, filename)
    try:
        cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
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
    safe = os.path.basename(filename)
    path = os.path.join(SNAPSHOTS_DIR, safe)
    if not os.path.exists(path):
        return ('', 404)
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
 
 
# ── Journal d'activité ───────────────────────
@app.route('/activity/recent')
@api_auth
def activity_recent():
    return jsonify({"activity": _activity_log})
 
 
# ── Captures sur mouvement (on/off) ──────────
@app.route('/set_captures', methods=['POST'])
@api_auth
def set_captures():
    global SAVE_CAPTURES
    data = request.get_json(silent=True) or {}
    SAVE_CAPTURES = bool(data.get('enabled', False))
    log.info(f"[CAPTURE] Sauvegarde événements {'activée' if SAVE_CAPTURES else 'désactivée'}")
    return jsonify({"status": "ok", "enabled": SAVE_CAPTURES})
 
@app.route('/get_captures')
@api_auth
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
@api_auth
def get_quality():
    return jsonify({"quality": stream_quality, "label": QUALITY_PRESETS[stream_quality]["label"]})
 
 
# ── Timelapse ─────────────────────────────────
@app.route('/timelapse/status')
@api_auth
def timelapse_status():
    return jsonify({
        "enabled": TIMELAPSE_ENABLED,
        "interval": TIMELAPSE_INTERVAL_S,
        "retention_days": TIMELAPSE_RETENTION_DAYS,
    })
 
@app.route('/timelapse/toggle', methods=['POST'])
@api_auth
def timelapse_toggle():
    global TIMELAPSE_ENABLED
    data = request.get_json(silent=True) or {}
    TIMELAPSE_ENABLED = bool(data.get('active', not TIMELAPSE_ENABLED))
    log.info(f"[TIMELAPSE] {'Activé' if TIMELAPSE_ENABLED else 'Désactivé'}")
    return jsonify({"status": "ok", "enabled": TIMELAPSE_ENABLED})
 
@app.route('/timelapse/interval', methods=['POST'])
@api_auth
def timelapse_set_interval():
    global TIMELAPSE_INTERVAL_S
    data = request.get_json(silent=True) or {}
    try:
        sec = int(data.get('seconds', TIMELAPSE_INTERVAL_S))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Valeur invalide"}), 400
    sec = max(10, min(3600, sec))
    TIMELAPSE_INTERVAL_S = sec
    log.info(f"[TIMELAPSE] Intervalle réglé à {sec}s")
    return jsonify({"status": "ok", "interval": sec})
 
@app.route('/timelapse/days')
@api_auth
def timelapse_days():
    try:
        days = sorted(
            [d for d in os.listdir(TIMELAPSE_DIR)
             if d != 'exports' and os.path.isdir(os.path.join(TIMELAPSE_DIR, d))],
            reverse=True
        )
        counts = {}
        for d in days:
            counts[d] = len([f for f in os.listdir(os.path.join(TIMELAPSE_DIR, d))
                              if f.lower().endswith('.jpg')])
        return jsonify({"days": days, "counts": counts})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
 
@app.route('/timelapse/build', methods=['POST'])
@api_auth
def timelapse_build():
    data = request.get_json(silent=True) or {}
    day = data.get('day', '').strip()
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', day):
        return jsonify({"status": "error", "message": "Journée invalide"}), 400
    with _timelapse_build_lock:
        if _timelapse_build_state.get("running"):
            return jsonify({"status": "error", "message": "Une génération est déjà en cours"}), 409
    threading.Thread(target=_build_timelapse_video, args=(day,), daemon=True).start()
    return jsonify({"status": "ok"})
 
@app.route('/timelapse/build/status')
@api_auth
def timelapse_build_status():
    return jsonify(_timelapse_build_state)
 
@app.route('/timelapse/exports')
@api_auth
def timelapse_exports():
    try:
        files = sorted(Path(TIMELAPSE_EXPORTS_DIR).glob('*.mp4'), reverse=True)
        return jsonify({"files": [f.name for f in files]})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
 
@app.route('/timelapse/exports/<filename>')
@api_auth
def timelapse_export_file(filename):
    safe = os.path.basename(filename)
    path = os.path.join(TIMELAPSE_EXPORTS_DIR, safe)
    if not os.path.exists(path):
        return ('', 404)
    return send_file(path, mimetype='video/mp4')
 
 
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
 
@app.route('/mic_status')
def route_mic_status():
    return jsonify({"active": mic_active})
 
@app.route('/ngrok_url')
def get_ngrok_url():
    # Route publique — l'URL ngrok n'est pas un secret
    return jsonify({"url": ngrok_public_url})
 
 
# ── Flux audio SSE ────────────────────────────
@app.route('/audio_stream')
@api_auth
def audio_stream():
    """Server-Sent Events : envoie les trames PCM base64 aux clients web.
    Le navigateur décode et joue via Web Audio API."""
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
 
 
# ─────────────────────────────────────────────
#  PAGES HTML
# ─────────────────────────────────────────────
LOGIN_HTML_TEMPLATE = '''<!DOCTYPE html><html lang="fr"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>P.I.G.E. — Connexion</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#0f0f17;display:flex;align-items:center;justify-content:center;
       min-height:100vh;font-family:system-ui,sans-serif}
  .box{background:#1a1a2e;border:1px solid #2a2a3e;border-radius:14px;
        padding:40px 36px;width:320px;display:flex;flex-direction:column;gap:16px}
  h1{color:#e0e0f0;font-size:1.05rem;text-align:center;letter-spacing:.03em}
  .dot{width:10px;height:10px;border-radius:50%;background:#3ecf8e;
        box-shadow:0 0 8px #3ecf8e;margin:0 auto 4px}
  input[type=password]{background:#111;border:1px solid #2a2a3e;border-radius:8px;
    color:#e0e0f0;padding:11px 13px;font-size:.95rem;width:100%;outline:none;
    transition:border .2s}
  input[type=password]:focus{border-color:#4f8ef7}
  button{background:#4f8ef7;border:none;border-radius:8px;color:#fff;
          padding:11px;font-size:.95rem;cursor:pointer;transition:background .2s}
  button:hover{background:#3a7ae0}
  .err{color:#e35b5b;font-size:.82rem;text-align:center}
</style></head><body>
<form class="box" method="POST">
  <div class="dot"></div>
  <h1>🐦 P.I.G.E. — Pigeon ramier</h1>
  <input type="password" name="password" placeholder="Mot de passe" autofocus>
  __ERROR_BLOCK__
  <button type="submit">Connexion</button>
</form></body></html>'''
 
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
    error_html = f"<div class='err'>{error}</div>" if error else ""
    return LOGIN_HTML_TEMPLATE.replace('__ERROR_BLOCK__', error_html)
 
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))
 
 
INDEX_HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>P.I.G.E. — Nichoir Pigeon Ramier – Médiathèque</title>
<style>
:root {
  --bg:#0d0d0d; --surface:#1a1a1a; --border:#2e2e2e;
  --accent:#4f8ef7; --accent2:#3ecf8e; --red:#e35b5b;
  --text:#e8e8e8; --muted:#888;
}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:'Segoe UI',Arial,sans-serif;min-height:100vh}
header{background:var(--surface);border-bottom:1px solid var(--border);
        padding:12px 24px;display:flex;align-items:center;gap:10px}
@media (max-width: 960px) {
  header{padding:8px 14px}
  h1{font-size:.9rem}
}
h1{font-size:1.02rem;font-weight:600;letter-spacing:.02em}
.dot{width:8px;height:8px;border-radius:50%;background:var(--accent2);
      box-shadow:0 0 6px var(--accent2);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.layout{display:grid;grid-template-columns:1fr 380px;height:calc(100vh - 49px)}
@media (orientation: portrait), (max-width: 960px) {
  .layout{grid-template-columns:1fr;grid-template-rows:40vh 1fr;height:calc(100vh - 49px)}
  .video-panel{min-height:0}
  .ctrl-panel{border-left:none;border-top:1px solid var(--border)}
}
.video-panel{background:#000;display:flex;align-items:center;justify-content:center;
              overflow:hidden;position:relative;min-height:0}
.video-panel img{width:100%;height:100%;object-fit:contain}
 
.ctrl-panel{background:var(--surface);border-left:1px solid var(--border);
             display:flex;flex-direction:column;overflow:hidden;height:100%}
.tabs{display:flex;border-bottom:1px solid var(--border);flex-shrink:0}
.tab{flex:1;padding:10px 1px;font-size:.78rem;text-align:center;cursor:pointer;
      color:var(--muted);border-bottom:2px solid transparent;
      transition:color .15s,border-color .15s;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tab.active{color:var(--accent);border-bottom-color:var(--accent)}
.tab-content{display:none;flex-direction:column;gap:13px;overflow-y:auto;padding:13px;flex:1;
              scrollbar-width:thin;scrollbar-color:var(--border) transparent}
.tab-content.active{display:flex}
.card{background:var(--bg);border:1px solid var(--border);border-radius:9px;padding:12px}
.card h2{font-size:.73rem;text-transform:uppercase;letter-spacing:.1em;
          color:var(--muted);margin-bottom:9px;display:flex;align-items:center;gap:5px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:4px;
      padding:6px 12px;border:none;border-radius:6px;font-size:.82rem;
      cursor:pointer;font-weight:600;transition:opacity .15s,transform .1s;white-space:nowrap}
.btn:active{transform:scale(.97)}
.btn:disabled{opacity:.4;cursor:not-allowed}
.btn-primary{background:var(--accent);color:#fff}
.btn-success{background:var(--accent2);color:#000}
.btn-danger{background:var(--red);color:#fff}
.btn-ghost{background:var(--border);color:var(--text)}
.btn-row{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
select,input[type=text],input[type=number]{width:100%;background:#111;border:1px solid var(--border);
        border-radius:6px;color:var(--text);padding:7px 8px;font-size:.82rem;outline:none;
        transition:border .2s;margin-bottom:7px}
select:focus,input:focus{border-color:var(--accent)}
.snap-gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(72px,1fr));
              gap:6px;width:100%}
.snap-thumb{position:relative;aspect-ratio:4/3;border-radius:6px;overflow:hidden;
             cursor:pointer;border:1px solid var(--border);background:#000}
.snap-thumb img{width:100%;height:100%;object-fit:cover;display:block}
.snap-del{position:absolute;top:2px;right:2px;background:rgba(0,0,0,.65);
           border:none;color:#fff;border-radius:4px;font-size:.65rem;
           padding:1px 5px;cursor:pointer;line-height:1.5;opacity:0;
           transition:opacity .15s}
.snap-thumb:hover .snap-del{opacity:1}
.snap-thumb:hover img{opacity:.8}
.toggle-pill{width:40px;height:22px;border-radius:11px;background:#333;
              position:relative;cursor:pointer;transition:background .2s;flex-shrink:0}
.toggle-pill.on{background:var(--accent2)}
.toggle-pill::after{content:'';width:16px;height:16px;border-radius:50%;background:#fff;
  position:absolute;top:3px;left:3px;transition:left .2s}
.toggle-pill.on::after{left:21px}
.row-between{display:flex;align-items:center;justify-content:space-between}
#toast{position:fixed;bottom:16px;right:16px;z-index:999;background:#222;
        border:1px solid var(--border);border-radius:8px;padding:8px 15px;
        font-size:.82rem;opacity:0;pointer-events:none;transition:opacity .3s;max-width:270px}
#toast.show{opacity:1}
#toast.ok{border-color:var(--accent2);color:var(--accent2)}
#toast.err{border-color:var(--red);color:var(--red)}
.day-row{display:flex;align-items:center;justify-content:space-between;background:#111;
          border:1px solid var(--border);border-radius:7px;padding:7px 10px;margin-bottom:5px}
.export-link{display:block;font-size:.79rem;color:var(--accent);padding:4px 0;text-decoration:none}
.activity-item{padding:3px 0;font-size:.78rem;border-bottom:1px solid #1a1a1a}
</style>
</head>
<body>
<header>
  <div class="dot"></div>
  <h1>🐦 P.I.G.E. — Nichoir Pigeon ramier &ndash; M&eacute;diath&egrave;que</h1>
</header>
 
<div class="layout">
  <div class="video-panel">
    <img id="videoFeed" src="/video_feed" alt="Flux vid&eacute;o du nichoir">
  </div>
  <div class="ctrl-panel">
    <div class="tabs">
      <div class="tab active" id="tab-direct"    onclick="switchTab('direct')">&#128225; Direct</div>
      <div class="tab"        id="tab-timelapse" onclick="switchTab('timelapse')">&#127909; Timelapse</div>
      <div class="tab"        id="tab-listen"    onclick="switchTab('listen')">&#127911; &Eacute;coute</div>
    </div>
 
    <!-- onglet Direct -->
    <div class="tab-content active" id="pane-direct">
      <div class="card" id="ngrokCard" style="display:none">
        <div style="display:flex;align-items:center;gap:8px">
          <div style="width:8px;height:8px;border-radius:50%;background:#3ecf8e;
                      box-shadow:0 0 6px #3ecf8e;flex-shrink:0"></div>
          <span style="font-size:.73rem;color:var(--muted)">Acc&egrave;s externe :</span>
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
        <div class="row-between">
          <h2 style="margin:0">Captures sur mouvement</h2>
          <div class="toggle-pill" id="captureToggle" onclick="toggleCaptures()"></div>
        </div>
        <div style="font-size:.79rem;color:var(--muted);margin-top:6px" id="captureStatus">D&eacute;sactiv&eacute;es</div>
      </div>
 
      <div class="card">
        <div class="row-between" style="margin-bottom:8px">
          <h2 style="margin:0">&#128247; Snapshot</h2>
          <button class="btn btn-primary" style="padding:4px 10px;font-size:.78rem"
                  onclick="takeSnapshot()">Capturer</button>
        </div>
        <div id="snapshotGallery" class="snap-gallery"></div>
      </div>
 
      <div class="card">
        <h2>Journal d'activit&eacute;</h2>
        <div id="activityList"></div>
      </div>
    </div>
 
    <!-- onglet Timelapse -->
    <div class="tab-content" id="pane-timelapse">
      <div class="card">
        <div class="row-between">
          <h2 style="margin:0">Timelapse</h2>
          <div class="toggle-pill" id="timelapseToggle" onclick="toggleTimelapse()"></div>
        </div>
        <div style="font-size:.79rem;color:var(--muted);margin-top:6px" id="timelapseStatus">D&eacute;sactiv&eacute;</div>
        <div style="display:flex;align-items:center;gap:8px;margin-top:10px">
          <label style="font-size:.78rem;color:var(--muted);white-space:nowrap">Intervalle (s)</label>
          <input type="number" id="timelapseInterval" min="10" max="3600" style="margin-bottom:0">
          <button class="btn btn-ghost" style="font-size:.75rem;padding:5px 10px" onclick="setTimelapseInterval()">OK</button>
        </div>
      </div>
      <div class="card">
        <h2>Journ&eacute;es enregistr&eacute;es</h2>
        <div id="timelapseDays"></div>
        <div id="buildStatus" style="font-size:.73rem;color:var(--muted);margin-top:6px"></div>
      </div>
      <div class="card">
        <h2>Vid&eacute;os g&eacute;n&eacute;r&eacute;es</h2>
        <div id="timelapseExports"></div>
      </div>
    </div>
 
    <!-- onglet Ecoute -->
    <div class="tab-content" id="pane-listen">
      <div class="card">
        <h2>&#127911; &Eacute;coute micro en direct</h2>
        <div style="font-size:.72rem;color:var(--muted);margin-bottom:8px">
          N&eacute;cessite que le micro de la cam&eacute;ra soit bien orient&eacute; vers le nid.
        </div>
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
          <div id="audioIndicator" style="width:8px;height:8px;border-radius:50%;background:#444;flex-shrink:0"></div>
          <span id="audioStatus" style="font-size:.79rem;color:var(--muted)">Non connect&eacute;</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:7px">
          <label style="font-size:.79rem;color:var(--muted);white-space:nowrap">Volume</label>
          <input type="range" id="listenVolume" min="0" max="2" step="0.05" value="1"
                 style="flex:1;accent-color:var(--accent);margin-bottom:0">
          <span id="volLabel" style="font-size:.73rem;color:var(--muted);width:34px;text-align:right">100%</span>
        </div>
        <div class="btn-row">
          <button class="btn btn-primary" id="btnListen" onclick="toggleListen()">&#127911; &Eacute;couter</button>
        </div>
      </div>
    </div>
 
  </div>
</div>
 
<div id="toast"></div>
<script>
const SERVER = window.location.origin;
const NGROK_URL = __NGROK_URL_JSON__;
 
// ── Onglets ───────────────────────────────────
function switchTab(name) {
  document.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
  document.querySelectorAll('.tab-content').forEach(function(p) { p.classList.remove('active'); });
  document.getElementById('tab-' + name).classList.add('active');
  document.getElementById('pane-' + name).classList.add('active');
  if (name === 'direct') { loadSnapshots(); loadActivity(); }
  if (name === 'timelapse') { loadTimelapseStatus(); loadTimelapseDays(); loadTimelapseExports(); }
}
 
function toast(msg, type) {
  var t = document.getElementById('toast');
  t.textContent = msg; t.className = 'show ' + (type || 'ok');
  clearTimeout(t._t); t._t = setTimeout(function() { t.className = ''; }, 3000);
}
 
// ── Flux vidéo ────────────────────────────────
var feed = document.getElementById('videoFeed');
feed.onerror = function() { feed.src = SERVER + '/video_feed?t=' + Date.now(); };
setInterval(function() { feed.src = SERVER + '/video_feed?t=' + Date.now(); }, 60000);
 
// ── ngrok ─────────────────────────────────────
function showNgrokBar(url) {
  if (!url) return;
  var card = document.getElementById('ngrokCard');
  var link = document.getElementById('ngrokLink');
  if (card) card.style.display = '';
  if (link) { link.href = url; link.textContent = url; }
}
if (NGROK_URL) {
  showNgrokBar(NGROK_URL);
} else {
  (function pollNgrok(tries) {
    fetch(SERVER + '/ngrok_url', {credentials: 'same-origin'})
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (d.url) { showNgrokBar(d.url); }
        else if (tries < 10) { setTimeout(function() { pollNgrok(tries + 1); }, 3000); }
      }).catch(function() {
        if (tries < 10) { setTimeout(function() { pollNgrok(tries + 1); }, 3000); }
      });
  })(0);
}
 
// ── Qualité vidéo ─────────────────────────────
async function setQuality(q) {
  try {
    var r = await fetch(SERVER + '/set_quality', {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({quality: q})
    });
    var d = await r.json();
    if (d.status === 'ok') {
      updateQualityButtons(q);
      document.getElementById('qualityLabel').textContent = d.label;
      toast('Qualité : ' + d.label);
    } else toast('Erreur qualité', 'err');
  } catch (e) { toast('Connexion impossible', 'err'); }
}
function updateQualityButtons(q) {
  ['hd', 'medium', 'low'].forEach(function(k) {
    var btn = document.getElementById('q-' + k);
    if (btn) btn.className = 'btn ' + (k === q ? 'btn-success' : 'btn-ghost');
  });
}
async function loadQuality() {
  try {
    var r = await fetch(SERVER + '/get_quality', {credentials: 'same-origin'});
    var d = await r.json();
    updateQualityButtons(d.quality);
    document.getElementById('qualityLabel').textContent = d.label;
  } catch (e) {}
}
 
// ── Captures sur mouvement ────────────────────
var capturesOn = false;
async function toggleCaptures() {
  var next = !capturesOn;
  try {
    var r = await fetch(SERVER + '/set_captures', {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({enabled: next})
    });
    var d = await r.json();
    capturesOn = d.enabled;
    updateCapturesUI();
    toast(capturesOn ? 'Captures sur mouvement activées' : 'Captures désactivées');
  } catch (e) { toast('Erreur', 'err'); }
}
function updateCapturesUI() {
  var tog = document.getElementById('captureToggle');
  var lbl = document.getElementById('captureStatus');
  if (!tog) return;
  tog.classList.toggle('on', capturesOn);
  lbl.textContent = capturesOn ? 'Activées' : 'Désactivées';
}
async function loadCapturesStatus() {
  try {
    var r = await fetch(SERVER + '/get_captures', {credentials: 'same-origin'});
    var d = await r.json();
    capturesOn = d.enabled;
    updateCapturesUI();
  } catch (e) {}
}
 
// ── Snapshots ──────────────────────────────────
async function takeSnapshot() {
  try {
    var r = await fetch(SERVER + '/snapshot', {method: 'POST', credentials: 'same-origin'});
    var d = await r.json();
    if (d.status === 'ok') { toast('📷 Snapshot sauvegardé'); loadSnapshots(); }
    else toast('Erreur snapshot', 'err');
  } catch (e) { toast('Connexion impossible', 'err'); }
}
async function loadSnapshots() {
  try {
    var r = await fetch(SERVER + '/snapshots', {credentials: 'same-origin'});
    var d = await r.json();
    renderSnapshots(d.snapshots || []);
  } catch (e) {}
}
function renderSnapshots(names) {
  var g = document.getElementById('snapshotGallery');
  if (!g) return;
  g.innerHTML = '';
  if (!names.length) {
    g.innerHTML = '<span style="font-size:.72rem;color:var(--muted)">Aucun snapshot</span>';
    return;
  }
  names.forEach(function(name) {
    var wrap = document.createElement('div'); wrap.className = 'snap-thumb';
    var img = document.createElement('img');
    img.src = SERVER + '/snapshots/' + encodeURIComponent(name);
    img.alt = name;
    img.onclick = function() { window.open(img.src, '_blank'); };
    var del = document.createElement('button'); del.className = 'snap-del';
    del.textContent = '✕'; del.title = 'Supprimer';
    del.onclick = function(e) {
      e.stopPropagation();
      fetch(SERVER + '/snapshots/' + encodeURIComponent(name), {method: 'DELETE', credentials: 'same-origin'})
        .then(function() { loadSnapshots(); });
    };
    wrap.appendChild(img); wrap.appendChild(del); g.appendChild(wrap);
  });
}
 
// ── Journal d'activité ─────────────────────────
async function loadActivity() {
  try {
    var r = await fetch(SERVER + '/activity/recent', {credentials: 'same-origin'});
    var d = await r.json();
    var wrap = document.getElementById('activityList');
    if (!wrap) return;
    if (!d.activity.length) {
      wrap.innerHTML = '<span style="color:var(--muted);font-size:.78rem">Aucune activité récente</span>';
      return;
    }
    wrap.innerHTML = d.activity.map(function(a) {
      return '<div class="activity-item">' + a.time + ' — mouvement détecté</div>';
    }).join('');
  } catch (e) {}
}
setInterval(loadActivity, 8000);
 
// ── Timelapse ──────────────────────────────────
async function loadTimelapseStatus() {
  try {
    var r = await fetch(SERVER + '/timelapse/status', {credentials: 'same-origin'});
    var d = await r.json();
    document.getElementById('timelapseToggle').classList.toggle('on', d.enabled);
    document.getElementById('timelapseStatus').textContent =
      d.enabled ? 'Activé — 1 image / ' + d.interval + ' s' : 'Désactivé';
    document.getElementById('timelapseInterval').value = d.interval;
  } catch (e) {}
}
async function toggleTimelapse() {
  try {
    var r = await fetch(SERVER + '/timelapse/toggle', {method: 'POST', credentials: 'same-origin'});
    var d = await r.json();
    loadTimelapseStatus();
    toast(d.enabled ? 'Timelapse activé' : 'Timelapse désactivé');
  } catch (e) { toast('Erreur', 'err'); }
}
async function setTimelapseInterval() {
  var sec = parseInt(document.getElementById('timelapseInterval').value, 10);
  if (!sec) { toast('Valeur invalide', 'err'); return; }
  try {
    var r = await fetch(SERVER + '/timelapse/interval', {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({seconds: sec})
    });
    var d = await r.json();
    if (d.status === 'ok') toast('Intervalle : ' + d.interval + ' s');
    loadTimelapseStatus();
  } catch (e) { toast('Erreur', 'err'); }
}
async function loadTimelapseDays() {
  try {
    var r = await fetch(SERVER + '/timelapse/days', {credentials: 'same-origin'});
    var d = await r.json();
    var wrap = document.getElementById('timelapseDays');
    wrap.innerHTML = '';
    if (!d.days.length) {
      wrap.innerHTML = '<span style="color:var(--muted);font-size:.78rem">Aucune journée enregistrée</span>';
      return;
    }
    d.days.forEach(function(day) {
      var row = document.createElement('div'); row.className = 'day-row';
      var lbl = document.createElement('span');
      lbl.style.fontSize = '.8rem';
      lbl.textContent = day + '  ';
      var count = document.createElement('span');
      count.style.cssText = 'color:var(--muted);font-size:.71rem';
      count.textContent = '(' + (d.counts[day] || 0) + ' images)';
      lbl.appendChild(count);
      var btn = document.createElement('button');
      btn.className = 'btn btn-primary'; btn.style.cssText = 'font-size:.72rem;padding:4px 9px';
      btn.textContent = 'Générer la vidéo';
      btn.onclick = function() { buildTimelapse(day); };
      row.appendChild(lbl); row.appendChild(btn);
      wrap.appendChild(row);
    });
  } catch (e) {}
}
async function buildTimelapse(day) {
  try {
    var r = await fetch(SERVER + '/timelapse/build', {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({day: day})
    });
    var d = await r.json();
    if (d.status === 'ok') { toast('Génération lancée…'); pollBuildStatus(); }
    else toast(d.message || 'Erreur', 'err');
  } catch (e) { toast('Connexion impossible', 'err'); }
}
var _buildPoll = null;
function pollBuildStatus() {
  clearInterval(_buildPoll);
  _buildPoll = setInterval(async function() {
    try {
      var r = await fetch(SERVER + '/timelapse/build/status', {credentials: 'same-origin'});
      var d = await r.json();
      var lbl = document.getElementById('buildStatus');
      if (d.running) {
        lbl.textContent = 'Génération ' + d.day + ' : ' + d.progress + '/' + d.total;
      } else {
        clearInterval(_buildPoll);
        if (d.done_file) {
          lbl.textContent = 'Terminé : ' + d.done_file;
          toast('Vidéo prête : ' + d.done_file);
          loadTimelapseExports();
        } else if (d.error) {
          lbl.textContent = 'Erreur : ' + d.error;
          toast(d.error, 'err');
        }
      }
    } catch (e) {}
  }, 1500);
}
async function loadTimelapseExports() {
  try {
    var r = await fetch(SERVER + '/timelapse/exports', {credentials: 'same-origin'});
    var d = await r.json();
    var wrap = document.getElementById('timelapseExports');
    wrap.innerHTML = '';
    if (!d.files.length) {
      wrap.innerHTML = '<span style="color:var(--muted);font-size:.78rem">Aucune vidéo générée</span>';
      return;
    }
    d.files.forEach(function(f) {
      var a = document.createElement('a');
      a.href = SERVER + '/timelapse/exports/' + encodeURIComponent(f);
      a.textContent = '⬇ ' + f;
      a.target = '_blank';
      a.className = 'export-link';
      wrap.appendChild(a);
    });
  } catch (e) {}
}
 
// ── Écoute micro ───────────────────────────────
var audioCtx = null, gainNode = null, audioSSE = null, listening = false;
var sampleRate = 44100, nextTime = 0;
var AHEAD = 0.10;
 
document.getElementById('listenVolume').addEventListener('input', function() {
  document.getElementById('volLabel').textContent = Math.round(this.value * 100) + '%';
  if (gainNode) gainNode.gain.value = parseFloat(this.value);
});
function setAudioStatus(text, color) {
  document.getElementById('audioStatus').textContent = text;
  document.getElementById('audioIndicator').style.background = color;
}
function toggleListen() { if (listening) stopListen(); else startListen(); }
function startListen() {
  if (listening) return;
  listening = true;
  document.getElementById('btnListen').textContent = 'Stop écoute';
  document.getElementById('btnListen').className = 'btn btn-danger';
  setAudioStatus('Ouverture micro...', '#f0a500');
  fetch(SERVER + '/mic_start', {method: 'POST', credentials: 'same-origin'}).catch(function() {});
  audioCtx = new (window.AudioContext || window.webkitAudioContext)({sampleRate: sampleRate});
  gainNode = audioCtx.createGain();
  gainNode.gain.value = parseFloat(document.getElementById('listenVolume').value);
  gainNode.connect(audioCtx.destination);
  nextTime = audioCtx.currentTime + AHEAD;
  audioSSE = new EventSource(SERVER + '/audio_stream');
  audioSSE.addEventListener('config', function(e) {
    var cfg = JSON.parse(e.data); sampleRate = cfg.sampleRate;
    if (audioCtx.sampleRate !== sampleRate) {
      audioCtx.close();
      audioCtx = new (window.AudioContext || window.webkitAudioContext)({sampleRate: sampleRate});
      gainNode = audioCtx.createGain();
      gainNode.gain.value = parseFloat(document.getElementById('listenVolume').value);
      gainNode.connect(audioCtx.destination);
      nextTime = audioCtx.currentTime + AHEAD;
    }
    setAudioStatus('Micro en direct', '#3ecf8e');
  });
  audioSSE.onmessage = function(e) {
    if (!audioCtx || !gainNode) return;
    try {
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
    } catch (err) { console.warn('[Audio]', err); }
  };
  audioSSE.onerror = function() { if (listening) setAudioStatus('Reconnexion...', '#e35b5b'); };
}
function stopListen() {
  listening = false;
  if (audioSSE) { audioSSE.close(); audioSSE = null; }
  if (audioCtx) { audioCtx.close(); audioCtx = null; gainNode = null; }
  nextTime = 0;
  fetch(SERVER + '/mic_stop', {method: 'POST', credentials: 'same-origin'}).catch(function() {});
  document.getElementById('btnListen').textContent = '🎧 Écouter';
  document.getElementById('btnListen').className = 'btn btn-primary';
  setAudioStatus('Micro fermé', '#444');
}
 
// ── Init ────────────────────────────────────────
loadQuality();
loadCapturesStatus();
loadSnapshots();
loadActivity();
</script>
</body>
</html>'''
 
@app.route('/')
@login_required
def index():
    html = INDEX_HTML_TEMPLATE.replace('__NGROK_URL_JSON__', json.dumps(ngrok_public_url))
    return html
 
 
# ─────────────────────────────────────────────
#  NGROK — tunnel public optionnel
# ─────────────────────────────────────────────
def start_ngrok(port: int = 5000):
    """
    Lance ngrok en subprocess et retourne l'URL publique.
    Nécessite ngrok.exe dans le même dossier que ce script
    ET NGROK_TOKEN défini dans ngrok_token.env
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
        import subprocess
        subprocess.run([ngrok_exe, 'config', 'add-authtoken', token],
                        capture_output=True, timeout=10)
 
        proc = subprocess.Popen(
            [ngrok_exe, 'http', str(port), '--log', 'stdout', '--log-format', 'json'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
 
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
    log.info("=== P.I.G.E. — Programme Intelligent de Guet et d'Écoute (nichoir pigeon ramier) — 24/24 ===")
    log.info(f"Fichier de log : {LOG_FILE}")
    log.info("Démarrage du serveur...")
    log.info("[MICRO] Micro en veille — s'active à la demande via le bouton Écouter")
    save_html_file()
    ip_address = get_local_ip()
    public_url = start_ngrok(port=5000)
    local_url  = f"http://{ip_address}:5000"
    print(f"\n  Interface LAN    : {local_url}")
    if public_url:
        print(f"  Accès externe    : {public_url}")
    print(f"  Flux vidéo       : {local_url}/video_feed")
    print(f"  Dossier captures : {motion_captures_dir}")
    print(f"  Dossier timelapse: {TIMELAPSE_DIR}")
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