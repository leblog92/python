import cv2
import flask
import numpy as np
import datetime
import os
import time
from flask import Response

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
                    save_capture(frame)
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
    <title>Flux Vidéo</title>
    <style>
        body {
            margin: 0;
            padding: 0;
            background-color: black;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            overflow: hidden;
        }
        
        #videoStream {
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
        }
    </style>
</head>
<body>
    <img id="videoStream" src="http://10.151.0.66/video_feed" alt="Flux vidéo en direct">
    
    <script>
        // Rechargement automatique en cas d'erreur
        document.getElementById('videoStream').onerror = function() {
            this.src = '/video_feed?t=' + new Date().getTime();
        };
        
        // Rechargement périodique pour maintenir la connexion
        setInterval(function() {
            var img = document.getElementById('videoStream');
            var currentSrc = img.src;
            img.src = currentSrc.split('?')[0] + '?t=' + new Date().getTime();
        }, 30000); // Toutes les 30 secondes
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    print("=== LOGITECH C270 - SURVEILLANCE HD AVEC GESTION D'ERREURS ===")
    print("Démarrage du serveur...")
    print("Accédez à http://localhost:5000")
    print("Résolution: 1280x720 HD")
    print("Backend: DSHOW (Windows)")
    print("Dossier des captures:", os.path.abspath('motion_captures'))
    print("Détection de mouvement: Active")
    print("Captures automatiques: Activées")
    app.run(host='0.0.0.0', port=5000, debug=False)