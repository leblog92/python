import cv2
import flask
import numpy as np
import datetime
import os
import time
from flask import Response, request

app = flask.Flask(__name__)

# Configuration optimisée pour éviter les erreurs MSMF
class RobustCamera:
    def __init__(self):
        self.cap = None
        self.backend = cv2.CAP_DSHOW  # Préférer DSHOW pour Windows
        self.init_camera()
        
    def init_camera(self):
        """Initialise la caméra avec gestion d'erreurs"""
        if self.cap is not None:
            self.cap.release()
            time.sleep(1)  # Pause pour la réinitialisation matérielle
            
        try:
            self.cap = cv2.VideoCapture(0, self.backend)
            
            if not self.cap.isOpened():
                print("Tentative avec backend par défaut...")
                self.cap = cv2.VideoCapture(0)
                
            if not self.cap.isOpened():
                print("ERREUR: Impossible d'ouvrir la caméra")
                return False
            
            # Configuration minimale pour stabilité
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.cap.set(cv2.CAP_PROP_FPS, 25)
            
            # Essayer MJPG, sinon laisser par défaut
            try:
                self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            except:
                print("MJPG non supporté, utilisation du codec par défaut")
            
            # Désactiver l'auto-focus pour plus de stabilité
            self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
            
            # Test de lecture
            for i in range(5):  # Plusieurs tentatives
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
        """Lecture robuste avec récupération d'erreurs"""
        if self.cap is None:
            if not self.init_camera():
                return False, None
                
        try:
            success, frame = self.cap.read()
            
            if not success or frame is None:
                # Tentative de récupération
                print("Tentative de récupération de la caméra...")
                self.init_camera()
                success, frame = self.cap.read() if self.cap else (False, None)
                
            return success, frame
            
        except Exception as e:
            print(f"ERREUR lecture: {e}")
            return False, None

# Initialisation
camera = RobustCamera()

# Variables pour la détection de mouvement
motion_detected = False
last_frame = None
motion_threshold = 500
capture_count = 0
MAX_CAPTURES = 100

if not os.path.exists('motion_captures'):
    os.makedirs('motion_captures')

def save_capture(frame):
    """Sauvegarde une capture d'écran"""
    global capture_count
    
    if capture_count >= MAX_CAPTURES:
        # Nettoyer les anciennes captures
        files = sorted(os.listdir('motion_captures'))
        for old_file in files[:-50]:
            os.remove(os.path.join('motion_captures', old_file))
        capture_count = 50
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"motion_captures/motion_{timestamp}.jpg"
    
    # Sauvegarde en JPG avec qualité optimisée
    cv2.imwrite(filename, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    capture_count += 1
    print(f"Capture sauvegardée: {filename}")
    
    return filename

def detect_motion(current_frame):
    """Détecte les mouvements dans l'image"""
    global last_frame, motion_detected
    
    if current_frame is None:
        return False, None
        
    # Réduction pour performance
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
    """Génère le flux vidéo pour le streaming"""
    global motion_detected
    motion_cooldown = 0
    frame_count = 0
    
    while True:
        success, frame = camera.read()
        
        if not success or frame is None:
            # Image de remplacement en cas d'erreur
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(frame, "CAMERA ERROR - RECONNECTION...", (50, 240), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        else:
            # Traitement normal
            frame_count += 1
            if frame_count % 2 == 0:  # Traiter 1 frame sur 2
                motion_detected, frame = detect_motion(frame)
                
                if motion_detected and motion_cooldown == 0:
                    save_capture(frame)  # MAINTENANT DÉFINIE !
                    motion_cooldown = 15
                
            if motion_cooldown > 0:
                motion_cooldown -= 1
        
        # Encodage pour streaming
        stream_frame = cv2.resize(frame, (960, 540))
        ret, buffer = cv2.imencode('.jpg', stream_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        
        if ret:
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        else:
            # Frame d'erreur
            error_frame = np.zeros((540, 960, 3), dtype=np.uint8)
            cv2.putText(error_frame, "ENCODING ERROR", (300, 270), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            ret, buffer = cv2.imencode('.jpg', error_frame)
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Logitech C270 - Surveillance HD</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; background: #f0f0f0; }
            .container { max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; }
            h1 { color: #333; text-align: center; }
            .video-container { text-align: center; margin: 20px 0; }
            #videoStream { max-width: 100%; border: 3px solid #333; border-radius: 5px; }
            .controls { text-align: center; margin: 20px 0; }
            .btn { padding: 10px 20px; margin: 5px; background: #007cba; color: white; border: none; border-radius: 5px; cursor: pointer; text-decoration: none; display: inline-block; }
            .info { background: #e7f3ff; padding: 15px; border-radius: 5px; margin: 10px 0; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔍 Logitech C270 - Surveillance HD 720p</h1>
            <div class="info">
                <strong>Configuration optimisée:</strong><br>
                • Résolution: 1280x720 HD<br>
                • FPS: 25 (stream: ~12 FPS)<br>
                • Détection mouvement: Active<br>
                • Backend: DSHOW (Windows)<br>
                • Gestion d'erreurs: Active
            </div>
            <div class="video-container">
                <img id="videoStream" src="/video_feed" width="960" height="540" alt="Flux HD Logitech C270">
            </div>
            <div class="controls">
                <button class="btn" onclick="manualCapture()">📸 Capture Manuelle</button>
                <a href="/config" class="btn">⚙️ Configuration</a>
                <a href="/captures" class="btn">🖼️ Voir Captures</a>
                <a href="/status" class="btn">📊 Status</a>
            </div>
        </div>
        <script>
            function manualCapture() {
                fetch('/manual_capture')
                    .then(response => response.text())
                    .then(data => alert('Capture HD effectuée!'));
            }
            
            // Recharger l'image en cas d'erreur
            document.getElementById('videoStream').onerror = function() {
                this.src = '/video_feed?t=' + new Date().getTime();
            };
        </script>
    </body>
    </html>
    '''

@app.route('/manual_capture')
def manual_capture():
    """Capture manuelle"""
    success, frame = camera.read()
    if success and frame is not None:
        filename = save_capture(frame)
        return f'Capture manuelle HD effectuée: <a href="/captures/{os.path.basename(filename)}">Voir</a><br><a href="/">Retour</a>'
    return 'Erreur lors de la capture <a href="/">Retour</a>'

@app.route('/captures')
def list_captures():
    """Liste toutes les captures"""
    if not os.path.exists('motion_captures'):
        return 'Aucune capture pour le moment <a href="/">Retour</a>'
    
    files = sorted(os.listdir('motion_captures'), reverse=True)
    html = '<h1>Captures HD Logitech C270</h1><div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px;">'
    for file in files[:20]:
        html += f'''
        <div style="border: 1px solid #ccc; padding: 10px; border-radius: 5px;">
            <img src="/captures/{file}" width="100%" style="max-width: 300px;">
            <div>{file}</div>
            <a href="/captures/{file}" target="_blank">Voir en HD</a>
        </div>
        '''
    html += '</div><br><a href="/">Retour au stream</a>'
    return html

@app.route('/captures/<filename>')
def get_capture(filename):
    """Sert une capture spécifique"""
    return flask.send_from_directory('motion_captures', filename)

@app.route('/status')
def status():
    """Page de statut"""
    global capture_count, motion_detected
    total_captures = len(os.listdir('motion_captures')) if os.path.exists('motion_captures') else 0
    
    return f'''
    <h1>Status Logitech C270</h1>
    <div style="background: #f8f9fa; padding: 20px; border-radius: 10px;">
        <p><strong>Captures totales:</strong> {total_captures}</p>
        <p><strong>Mouvement détecté:</strong> {motion_detected}</p>
        <p><strong>Résolution:</strong> 1280x720 HD</p>
        <p><strong>Dossier captures:</strong> {os.path.abspath('motion_captures')}</p>
        <p><strong>Backend caméra:</strong> DSHOW</p>
    </div>
    <br><a href="/">Retour au stream</a>
    '''

@app.route('/config', methods=['GET', 'POST'])
def config():
    """Page de configuration"""
    global motion_threshold
    
    if request.method == 'POST':
        motion_threshold = int(request.form.get('threshold', motion_threshold))
        return f'Seuil modifié: {motion_threshold} <br><a href="/config">Retour</a>'
    
    return f'''
    <h1>Configuration Logitech C270</h1>
    <form method="POST" style="background: #f8f9fa; padding: 20px; border-radius: 10px;">
        <label><strong>Seuil de détection (actuel: {motion_threshold}):</strong></label><br>
        <input type="range" name="threshold" value="{motion_threshold}" min="100" max="2000" step="50" 
               oninput="document.getElementById('thresholdValue').innerText = this.value">
        <span id="thresholdValue">{motion_threshold}</span>
        <small>(Plus bas = plus sensible)</small><br><br>
        
        <strong>Paramètres actuels:</strong><br>
        <ul>
            <li>Résolution: 1280x720</li>
            <li>FPS: 25</li>
            <li>Backend: DSHOW</li>
            <li>Gestion d'erreurs: Active</li>
        </ul>
        
        <input type="submit" value="Appliquer" style="padding: 10px 20px; background: #007cba; color: white; border: none; border-radius: 5px; cursor: pointer;">
    </form>
    <br><a href="/">Retour au stream</a>
    '''

if __name__ == '__main__':
    print("=== LOGITECH C270 - SURVEILLANCE HD AVEC GESTION D'ERREURS ===")
    print("Démarrage du serveur...")
    print("Accédez à http://localhost:5000")
    print("Résolution: 1280x720 HD")
    print("Backend: DSHOW (Windows)")
    print("Dossier des captures:", os.path.abspath('motion_captures'))
    app.run(host='0.0.0.0', port=5000, debug=False)