import cv2
import flask
import numpy as np
import datetime
import os
import time
import socket
import getpass
from flask import Response, request, jsonify
import subprocess
import threading
import pyttsx3
import pygame

app = flask.Flask(__name__)

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
                    print("✓ Caméra initialisée avec succès")
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


# ── Interface de contrôle principale ──────────
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
    border:2px dashed var(--border); border-radius:8px; padding:16px;
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
  'Si vous venez participer à l'heure de code vous pouvez vous installer dans la salle du fond.',
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
    print("=== LOGITECH C270 - SURVEILLANCE HD ===")
    print("Démarrage du serveur...")
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