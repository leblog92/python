import cv2
import flask
import numpy as np
import datetime
import os
import time
import socket
import getpass
from flask import Response, request, jsonify, stream_with_context
import subprocess
import threading
import pyttsx3
import pygame
import sounddevice as sd
import queue
import base64
import json
import struct

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

def _audio_callback(indata, frames, time_info, status):
    """Reçoit chaque bloc micro et le pousse vers tous les clients SSE."""
    if status:
        print(f"[MICRO] {status}")
    pcm = (indata[:, 0] * 32767).astype(np.int16).tobytes()
    b64 = base64.b64encode(pcm).decode('ascii')
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

def _start_audio_stream():
    """Demarre la capture micro en arriere-plan."""
    try:
        device_idx = _find_mic_device()
        stream = sd.InputStream(
            device=device_idx,
            samplerate=AUDIO_SAMPLERATE,
            channels=AUDIO_CHANNELS,
            dtype='float32',
            blocksize=AUDIO_CHUNK,
            callback=_audio_callback,
        )
        stream.start()
        print(f"[MICRO] Capture demarree ({AUDIO_SAMPLERATE} Hz, chunk={AUDIO_CHUNK})\n")
    except Exception as e:
        print(f"[MICRO] Impossible de demarrer : {e}")
        print("[MICRO]   -> pip install sounddevice --break-system-packages")

# ─────────────────────────────────────────────
#  TTS ENGINE (pyttsx3 – moteur Windows SAPI5)
# ─────────────────────────────────────────────
tts_lock = threading.Lock()

def speak_text(text: str):
    """Lit le texte via le moteur TTS Windows (SAPI5) dans un thread dédié."""
    def _run():
        with tts_lock:
            try:
                engine = pyttsx3.init()
                engine.setProperty('rate', 160)   # vitesse (mots/min)
                engine.setProperty('volume', 1.0) # volume max
                # Choisir une voix française si disponible
                voices = engine.getProperty('voices')
                for v in voices:
                    if 'french' in v.name.lower() or 'fr_' in v.id.lower() or 'hortense' in v.name.lower():
                        engine.setProperty('voice', v.id)
                        break
                engine.say(text)
                engine.runAndWait()
                engine.stop()
            except Exception as e:
                print(f"Erreur TTS: {e}")
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
        self.init_camera()

    def init_camera(self):
        if self.cap is not None:
            self.cap.release()
            time.sleep(1)
        try:
            self.cap = cv2.VideoCapture(0, self.backend)
            if not self.cap.isOpened():
                print("Tentative avec backend par défaut...")
                self.cap = cv2.VideoCapture(0)
            if not self.cap.isOpened():
                print("ERREUR: Impossible d'ouvrir la caméra")
                return False
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.cap.set(cv2.CAP_PROP_FPS, 25)
            try:
                self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            except:
                pass
            self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
            for _ in range(5):
                success, frame = self.cap.read()
                if success and frame is not None:
                    print("✓ Caméra C920 initialisée avec succès")
                    return True
                time.sleep(0.1)
            print("✗ Caméra ouverte mais ne renvoie pas d'image")
            return False
        except Exception as e:
            print(f"ERREUR initialisation caméra: {e}")
            return False

    def read(self):
        if self.cap is None:
            if not self.init_camera():
                return False, None
        try:
            success, frame = self.cap.read()
            if not success or frame is None:
                print("Tentative de récupération de la caméra...")
                self.init_camera()
                success, frame = self.cap.read() if self.cap else (False, None)
            return success, frame
        except Exception as e:
            print(f"ERREUR lecture: {e}")
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
        subprocess.Popen(f'start "" "{server_url}"', shell=True)
        print(f"Navigateur ouvert sur {server_url}")
    except Exception as e:
        print(f"Impossible d'ouvrir le navigateur : {e}")


# ─────────────────────────────────────────────
#  INITIALISATION
# ─────────────────────────────────────────────
camera = RobustCamera()
motion_detected = False
last_frame = None
motion_threshold = 500
capture_count = 0
MAX_CAPTURES = 100

user_profile = os.environ.get('USERPROFILE', os.path.expanduser('~'))
motion_captures_dir = os.path.join(user_profile, 'Pictures', 'motion_captures')
os.makedirs(motion_captures_dir, exist_ok=True)


def save_capture(frame):
    global capture_count
    if capture_count >= MAX_CAPTURES:
        try:
            files = sorted(os.listdir(motion_captures_dir))
            if len(files) > MAX_CAPTURES:
                for old_file in files[:len(files) - MAX_CAPTURES]:
                    os.remove(os.path.join(motion_captures_dir, old_file))
                capture_count = MAX_CAPTURES
        except Exception as e:
            print(f"Erreur nettoyage: {e}")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"motion_{timestamp}.jpg"
    file_path = os.path.join(motion_captures_dir, filename)
    try:
        cv2.imwrite(file_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        capture_count += 1
        print(f"Capture: {file_path}")
        return file_path
    except Exception as e:
        print(f"Erreur capture: {e}")
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
    while True:
        success, frame = camera.read()
        if not success or frame is None:
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(frame, "CAMERA ERROR - RECONNECTION...", (50, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        else:
            frame_count += 1
            if frame_count % 2 == 0:
                motion_detected, frame = detect_motion(frame)
                if motion_detected and motion_cooldown == 0:
                    save_capture(frame)
                    motion_cooldown = 15
            if motion_cooldown > 0:
                motion_cooldown -= 1
        stream_frame = cv2.resize(frame, (960, 540))
        ret, buffer = cv2.imencode('.jpg', stream_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ret:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        else:
            error_frame = np.zeros((540, 960, 3), dtype=np.uint8)
            cv2.putText(error_frame, "ENCODING ERROR", (300, 270),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            _, buffer = cv2.imencode('.jpg', error_frame)
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')


# ─────────────────────────────────────────────
#  ROUTES FLASK
# ─────────────────────────────────────────────

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


# ── TTS ──────────────────────────────────────
@app.route('/tts', methods=['POST'])
def tts():
    """
    POST JSON : {"text": "Bonjour la salle !"}
    Déclenche la lecture TTS sur la machine caméra.
    """
    data = request.get_json(silent=True) or {}
    text = data.get('text', '').strip()
    if not text:
        return jsonify({"status": "error", "message": "Champ 'text' manquant ou vide"}), 400
    print(f"[TTS] ← {text}")
    speak_text(text)
    return jsonify({"status": "ok", "text": text})


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
    """Retourne la liste des fichiers audio disponibles."""
    try:
        files = [f for f in os.listdir(MP3_DIR)
                 if f.lower().endswith(('.mp3', '.wav', '.ogg'))]
        files.sort()
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
    --text: #e8e8e8;
    --muted: #888;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:var(--bg); color:var(--text); font-family:'Segoe UI',Arial,sans-serif; min-height:100vh; }}

  header {{
    background:var(--surface);
    border-bottom:1px solid var(--border);
    padding:14px 28px;
    display:flex; align-items:center; gap:12px;
  }}
  header h1 {{ font-size:1.1rem; font-weight:600; letter-spacing:.05em; }}
  .dot {{ width:9px; height:9px; border-radius:50%; background:var(--accent2); box-shadow:0 0 6px var(--accent2); animation:pulse 2s infinite; }}
  @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.4}} }}

  .layout {{
    display:grid;
    grid-template-columns: 1fr 380px;
    gap:0;
    height:calc(100vh - 57px);
  }}

  /* ── Vidéo ── */
  .video-panel {{
    background:#000;
    display:flex; align-items:center; justify-content:center;
    overflow:hidden;
  }}
  .video-panel img {{ width:100%; height:100%; object-fit:contain; }}

  /* ── Panneau de contrôle ── */
  .ctrl-panel {{
    background:var(--surface);
    border-left:1px solid var(--border);
    padding:20px;
    display:flex; flex-direction:column; gap:20px;
    overflow-y:auto;
  }}

  .card {{
    background:var(--bg);
    border:1px solid var(--border);
    border-radius:10px;
    padding:16px;
  }}
  .card h2 {{
    font-size:.8rem; text-transform:uppercase; letter-spacing:.1em;
    color:var(--muted); margin-bottom:12px; display:flex; align-items:center; gap:6px;
  }}
  .card h2 svg {{ flex-shrink:0; }}

  textarea, input[type=text] {{
    width:100%; background:#111; border:1px solid var(--border); border-radius:6px;
    color:var(--text); padding:10px; font-size:.9rem; resize:vertical;
    outline:none; transition:border .2s;
  }}
  textarea:focus, input[type=text]:focus {{ border-color:var(--accent); }}

  .btn {{
    display:inline-flex; align-items:center; justify-content:center; gap:6px;
    padding:9px 16px; border:none; border-radius:6px; font-size:.88rem;
    cursor:pointer; font-weight:600; transition:opacity .15s, transform .1s;
    white-space:nowrap;
  }}
  .btn:active {{ transform:scale(.97); }}
  .btn:disabled {{ opacity:.4; cursor:not-allowed; }}
  .btn-primary {{ background:var(--accent); color:#fff; }}
  .btn-success {{ background:var(--accent2); color:#000; }}
  .btn-danger  {{ background:var(--red); color:#fff; }}
  .btn-ghost   {{ background:var(--border); color:var(--text); }}
  .btn-row {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }}

  /* ── Phrases rapides ── */
  .quick-btns {{ display:flex; flex-direction:column; gap:6px; }}
  .quick-btn {{
    background:#111; border:1px solid var(--border); border-radius:6px;
    color:var(--text); padding:8px 12px; font-size:.82rem; cursor:pointer;
    text-align:left; transition:border .2s, background .2s;
  }}
  .quick-btn:hover {{ border-color:var(--accent); background:#1a1a2e; }}

  /* ── Liste MP3 ── */
  #mp3List {{ list-style:none; display:flex; flex-direction:column; gap:6px; max-height:180px; overflow-y:auto; }}
  #mp3List li {{
    display:flex; align-items:center; justify-content:space-between;
    background:#111; border:1px solid var(--border); border-radius:6px; padding:8px 10px;
    font-size:.83rem;
  }}
  #mp3List li button {{ font-size:.78rem; padding:4px 10px; }}

  /* ── Upload ── */
  .upload-area {{
    border:2px dashed var(--border); border-radius:8px; padding:8px;
    text-align:center; cursor:pointer; font-size:.83rem; color:var(--muted);
    transition:border .2s;
  }}
  .upload-area:hover {{ border-color:var(--accent); color:var(--text); }}
  input[type=file] {{ display:none; }}

  /* ── Toast ── */
  #toast {{
    position:fixed; bottom:20px; right:20px; z-index:999;
    background:#222; border:1px solid var(--border); border-radius:8px;
    padding:10px 18px; font-size:.85rem; opacity:0; pointer-events:none;
    transition:opacity .3s; max-width:280px;
  }}
  #toast.show {{ opacity:1; }}
  #toast.ok {{ border-color:var(--accent2); color:var(--accent2); }}
  #toast.err {{ border-color:var(--red); color:var(--red); }}
</style>
</head>
<body>

<header>
  <div class="dot"></div>
  <h1>SALLE JVO – Surveillance &amp; Diffusion</h1>
</header>

<div class="layout">
  <!-- Flux vidéo -->
  <div class="video-panel">
    <img id="videoFeed" src="/video_feed" alt="Flux vidéo">
  </div>

  <!-- Panneau de contrôle -->
  <div class="ctrl-panel">

    <!-- TTS -->
    <div class="card">
      <h2>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 5L6 9H2v6h4l5 4V5z"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>
        Synthèse vocale (TTS)
      </h2>
      <textarea id="ttsText" rows="3" placeholder="Tapez votre message ici…"></textarea>
      <div class="btn-row">
        <button class="btn btn-primary" onclick="sendTTS()">▶ Lire</button>
        <button class="btn btn-ghost" onclick="document.getElementById('ttsText').value=''">Effacer</button>
      </div>
    </div>

    <!-- Phrases rapides -->
    <div class="card">
      <h2>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        Phrases rapides
      </h2>
      <div class="quick-btns" id="quickBtns"></div>
    </div>

    <!-- Écoute en direct -->
    <div class="card">
      <h2>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 18v-6a9 9 0 0 1 18 0v6"/><path d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z"/></svg>
        Écoute en direct
      </h2>
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
        <div id="audioIndicator" style="width:10px;height:10px;border-radius:50%;background:#444;flex-shrink:0;transition:background .15s"></div>
        <span id="audioStatus" style="font-size:.82rem;color:var(--muted)">Non connecté</span>
      </div>
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
        <label style="font-size:.82rem;color:var(--muted);white-space:nowrap">Volume</label>
        <input type="range" id="listenVolume" min="0" max="2" step="0.05" value="1"
               style="flex:1;accent-color:var(--accent)">
        <span id="volLabel" style="font-size:.78rem;color:var(--muted);width:32px;text-align:right">100%</span>
      </div>
      <div class="btn-row">
        <button class="btn btn-primary" id="btnListen" onclick="toggleListen()">🎧 Écouter</button>
      </div>
    </div>

    <!-- Upload MP3 -->
    <div class="card">
      <h2>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
        Ajouter un fichier audio
      </h2>
      <label class="upload-area" for="mp3Input" id="dropZone">
        📂 Cliquez ou déposez MP3 / WAV
      </label>
      <input type="file" id="mp3Input" accept=".mp3,.wav,.ogg" onchange="uploadMP3(this.files[0])">
    </div>

    <!-- Lecteur MP3 -->
    <div class="card">
      <h2>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/></svg>
        Fichiers audio
      </h2>
      <ul id="mp3List"><li style="color:var(--muted);font-size:.82rem">Chargement…</li></ul>
      <div class="btn-row" style="margin-top:12px">
        <button class="btn btn-danger" onclick="stopAudio()">■ Stop</button>
        <button class="btn btn-ghost" onclick="loadMP3List()">↺ Actualiser</button>
      </div>
    </div>

  </div>
</div>

<div id="toast"></div>

<script>
const SERVER = 'http://{ip}:5000';

// ── Écoute micro en direct (Web Audio API + SSE) ─────
let audioCtx    = null;
let gainNode    = null;
let audioSSE    = null;
let listening   = false;
let sampleRate  = 44100;
let nextTime    = 0;          // horloge de planification
const AHEAD_SEC = 0.10;       // buffer d'anticipation (100 ms)

document.getElementById('listenVolume').addEventListener('input', function() {{
  const pct = Math.round(this.value * 100);
  document.getElementById('volLabel').textContent = pct + '%';
  if (gainNode) gainNode.gain.value = parseFloat(this.value);
}});

function setAudioStatus(text, color) {{
  document.getElementById('audioStatus').textContent = text;
  document.getElementById('audioIndicator').style.background = color;
}}

function toggleListen() {{
  listening ? stopListen() : startListen();
}}

function startListen() {{
  if (listening) return;
  listening = true;
  document.getElementById('btnListen').textContent = '⏹ Arrêter';
  document.getElementById('btnListen').className = 'btn btn-danger';
  setAudioStatus('Connexion au micro…', '#f0a500');

  // Créer le contexte audio avec le bon sample rate
  audioCtx = new (window.AudioContext || window.webkitAudioContext)({{ sampleRate }});
  gainNode = audioCtx.createGain();
  gainNode.gain.value = parseFloat(document.getElementById('listenVolume').value);
  gainNode.connect(audioCtx.destination);
  nextTime = audioCtx.currentTime + AHEAD_SEC;

  audioSSE = new EventSource(SERVER + '/audio_stream');

  // Premier événement : config (sampleRate)
  audioSSE.addEventListener('config', e => {{
    const cfg = JSON.parse(e.data);
    sampleRate = cfg.sampleRate;
    // Recréer le contexte si le sample rate diffère
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

  // Chaque trame PCM base64
  audioSSE.onmessage = e => {{
    if (!audioCtx || !gainNode) return;
    try {{
      // Décoder base64 → ArrayBuffer
      const binStr = atob(e.data);
      const bytes  = new Uint8Array(binStr.length);
      for (let i = 0; i < binStr.length; i++) bytes[i] = binStr.charCodeAt(i);

      // PCM int16 little-endian → float32
      const pcm16   = new Int16Array(bytes.buffer);
      const float32 = new Float32Array(pcm16.length);
      for (let i = 0; i < pcm16.length; i++) float32[i] = pcm16[i] / 32768.0;

      // Créer un AudioBuffer et le planifier
      const buf = audioCtx.createBuffer(1, float32.length, sampleRate);
      buf.copyToChannel(float32, 0);
      const src = audioCtx.createBufferSource();
      src.buffer = buf;
      src.connect(gainNode);

      const now = audioCtx.currentTime;
      if (nextTime < now + 0.01) nextTime = now + AHEAD_SEC; // rattrapage si retard
      src.start(nextTime);
      nextTime += buf.duration;
    }} catch(err) {{
      console.warn('[Audio] decode error:', err);
    }}
  }};

  audioSSE.onerror = () => {{
    if (listening) setAudioStatus('⚠ Reconnexion…', '#e35b5b');
  }};
}}

function stopListen() {{
  listening = false;
  if (audioSSE)  {{ audioSSE.close();  audioSSE = null; }}
  if (audioCtx)  {{ audioCtx.close();  audioCtx = null; gainNode = null; }}
  nextTime = 0;
  document.getElementById('btnListen').textContent = '🎧 Écouter';
  document.getElementById('btnListen').className = 'btn btn-primary';
  setAudioStatus('Non connecté', '#444');
}}

// ── Flux vidéo ──────────────────────────────
const feed = document.getElementById('videoFeed');
feed.onerror = () => {{ feed.src = SERVER + '/video_feed?t=' + Date.now(); }};
setInterval(() => {{
  feed.src = SERVER + '/video_feed?t=' + Date.now();
}}, 30000);

// ── Toast ────────────────────────────────────
function toast(msg, type='ok') {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'show ' + type;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.className = '', 3000);
}}

// ── TTS ──────────────────────────────────────
async function sendTTS() {{
  const text = document.getElementById('ttsText').value.trim();
  if (!text) {{ toast('Aucun texte saisi', 'err'); return; }}
  try {{
    const r = await fetch(SERVER + '/tts', {{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{text}})
    }});
    const d = await r.json();
    if (d.status === 'ok') toast('✓ Message envoyé à la salle');
    else toast('Erreur: ' + d.message, 'err');
  }} catch(e) {{ toast('Connexion impossible', 'err'); }}
}}

// Envoi avec Ctrl+Entrée
document.getElementById('ttsText').addEventListener('keydown', e => {{
  if (e.ctrlKey && e.key === 'Enter') sendTTS();
}});

// ── Phrases rapides ──────────────────────────
const QUICK_PHRASES = [
  'Bonjour, bienvenue dans la salle jeux vidéo.',
  'Un membre du personnel va arriver dans quelques instants. Veuillez patienter.',
  'Vous pouvez vous installer dans la salle du fond.',
  'Attention, la salle fermera dans quelques minutes !',
  'Vous pouvez consulter les jeux disponibles sur place sur le panneau.',
];
function buildQuickBtns() {{
  const c = document.getElementById('quickBtns');
  QUICK_PHRASES.forEach(p => {{
    const b = document.createElement('button');
    b.className = 'quick-btn';
    b.textContent = '🔊 ' + p;
    b.onclick = () => {{
      document.getElementById('ttsText').value = p;
      sendTTS();
    }};
    c.appendChild(b);
  }});
}}
buildQuickBtns();

// ── Upload MP3 ────────────────────────────────
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

// ── Drag & drop ───────────────────────────────
const dz = document.getElementById('dropZone');
dz.addEventListener('dragover', e => {{ e.preventDefault(); dz.style.borderColor='var(--accent)'; }});
dz.addEventListener('dragleave', () => {{ dz.style.borderColor=''; }});
dz.addEventListener('drop', e => {{
  e.preventDefault(); dz.style.borderColor='';
  const f = e.dataTransfer.files[0];
  if (f) uploadMP3(f);
}});

// ── Liste MP3 ─────────────────────────────────
async function loadMP3List() {{
  try {{
    const r = await fetch(SERVER + '/list_mp3');
    const d = await r.json();
    const ul = document.getElementById('mp3List');
    ul.innerHTML = '';
    if (!d.files || d.files.length === 0) {{
      ul.innerHTML = '<li style="color:var(--muted);font-size:.82rem">Aucun fichier audio disponible</li>';
      return;
    }}
    d.files.forEach(f => {{
      const li = document.createElement('li');
      li.innerHTML = `<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:200px" title="${{f}}">${{f}}</span>
        <button class="btn btn-success" onclick="playMP3('${{f}}')">▶ Jouer</button>`;
      ul.appendChild(li);
    }});
  }} catch(e) {{ console.error(e); }}
}}

async function playMP3(filename) {{
  try {{
    const r = await fetch(SERVER + '/play_mp3', {{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{filename}})
    }});
    const d = await r.json();
    if (d.status === 'ok') toast('▶ Lecture: ' + filename);
    else toast('Erreur: ' + d.message, 'err');
  }} catch(e) {{ toast('Connexion impossible', 'err'); }}
}}

async function stopAudio() {{
  try {{
    await fetch(SERVER + '/stop_audio', {{method:'POST'}});
    toast('■ Audio arrêté');
  }} catch(e) {{ toast('Connexion impossible', 'err'); }}
}}

// Chargement initial
loadMP3List();
</script>
</body>
</html>'''


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────
if __name__ == '__main__':
    print("=== LOGITECH C920 - SURVEILLANCE HD ===")
    print("Démarrage du serveur...")
    _start_audio_stream()
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