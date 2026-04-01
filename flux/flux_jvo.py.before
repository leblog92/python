import cv2
import flask
import numpy as np
import datetime
import os
import time
import socket
import getpass
from flask import Response
import subprocess

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

def get_local_ip():
    """Obtenir l'adresse IP locale du serveur"""
    try:
        # Créer une connexion pour déterminer l'IP utilisée pour les connexions externes
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Ne se connecte pas réellement, prépare juste le socket
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception as e:
        print(f"Erreur lors de la récupération de l'IP: {e}")
        return "127.0.0.1"

def generate_html_file(ip_address):
    """Génère le fichier HTML avec l'adresse IP correcte"""
    html_content = f'''<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="icon" type="image/png" href="https://upload.wikimedia.org/wikipedia/commons/b/b4/Blue_eye_icon.png"/>
    <title>Flux Salle JVO</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            background-color: #000;
            color: #fff;
            font-family: Arial, sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{
            text-align: center;
            max-width: 100%;
        }}
        .video-container {{
            position: relative;
            display: inline-block;
            margin-bottom: 20px;
        }}
        
        img {{
            max-width: 100%;
            height: auto;
            border-radius: 8px;
            box-shadow: 0 4px 15px rgba(255, 255, 255, 0.1);
        }}

        
        .ip-dot {{
            margin: 0 5px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="video-container">
            <img id="videoFeed" src="http://{ip_address}:5000/video_feed" width="960" height="540" alt="Flux vidéo">
        </div>
    </div>
</body>
</html>'''
    
    return html_content

def save_html_file():
    """Sauvegarde le fichier HTML à l'emplacement spécifié"""
    try:
        # Chemin de destination
        destination_path = r"L:\Groups\mediatheque\06- SECTEUR INFORMATIQUE\7- SALLE JVO"
        
        # Vérifier si le chemin existe
        if not os.path.exists(destination_path):
            print(f"Le chemin n'existe pas: {destination_path}")
            print("Création du chemin...")
            try:
                os.makedirs(destination_path, exist_ok=True)
                print(f"Chemin créé: {destination_path}")
            except Exception as e:
                print(f"Impossible de créer le chemin: {e}")
                # Essayer de sauvegarder dans le répertoire courant
                destination_path = "."
        
        # Obtenir l'adresse IP
        ip_address = get_local_ip()
        print(f"Adresse IP détectée: {ip_address}")
        
        # Générer le contenu HTML
        html_content = generate_html_file(ip_address)
        
        # Chemin complet du fichier
        html_file_path = os.path.join(destination_path, "cam.html")
        
        # Sauvegarder le fichier
        with open(html_file_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"Fichier HTML généré avec succès: {html_file_path}")
        print(f"URL du flux: http://{ip_address}:5000/video_feed")
        
        # Essayer d'ouvrir le fichier HTML
        try:
            subprocess.Popen(f'explorer "{html_file_path}"', shell=True)
            print("Fichier HTML ouvert dans le navigateur par défaut")
        except:
            print(f"Fichier disponible à: {html_file_path}")
            
    except Exception as e:
        print(f"Erreur lors de la génération du fichier HTML: {e}")
        # Essayer de sauvegarder dans le répertoire courant en cas d'erreur
        try:
            ip_address = get_local_ip()
            html_content = generate_html_file(ip_address)
            with open("flux_jvo_local.html", 'w', encoding='utf-8') as f:
                f.write(html_content)
            print("Fichier HTML sauvegardé localement: flux_jvo_local.html")
        except Exception as e2:
            print(f"Échec de la sauvegarde locale: {e2}")

# Initialisation
camera = RobustCamera()

# Variables pour la détection de mouvement
motion_detected = False
last_frame = None
motion_threshold = 500
capture_count = 0
MAX_CAPTURES = 100

# Définir le dossier des captures dans %USERPROFILE%\Pictures\motion_captures
user_profile = os.environ.get('USERPROFILE', os.path.expanduser('~'))
motion_captures_dir = os.path.join(user_profile, 'Pictures', 'motion_captures')

# Créer le dossier s'il n'existe pas
if not os.path.exists(motion_captures_dir):
    os.makedirs(motion_captures_dir, exist_ok=True)
    print(f"Dossier créé: {motion_captures_dir}")

def save_capture(frame):
    """Sauvegarde une capture d'écran dans %USERPROFILE%\Pictures\motion_captures"""
    global capture_count
    
    if capture_count >= MAX_CAPTURES:
        # Nettoyer les anciennes captures
        try:
            files = sorted(os.listdir(motion_captures_dir))
            if len(files) > MAX_CAPTURES:
                for old_file in files[:len(files) - MAX_CAPTURES]:
                    os.remove(os.path.join(motion_captures_dir, old_file))
                capture_count = MAX_CAPTURES
        except Exception as e:
            print(f"Erreur lors du nettoyage des anciennes captures: {e}")
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"motion_{timestamp}.jpg"
    file_path = os.path.join(motion_captures_dir, filename)
    
    try:
        # Sauvegarde en JPG avec qualité optimisée
        cv2.imwrite(file_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        capture_count += 1
        print(f"Capture sauvegardée: {file_path}")
        return file_path
    except Exception as e:
        print(f"Erreur lors de la sauvegarde de la capture: {e}")
        return None

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
    <img id="videoStream" src="/video_feed" alt="Flux vidéo en direct">
    
    <script>
        // Rechargement automatique en cas d'erreur
        document.getElementById('videoStream').onerror = function() {{
            this.src = '/video_feed?t=' + new Date().getTime();
        }};
        
        // Rechargement périodique pour maintenir la connexion
        setInterval(function() {{
            var img = document.getElementById('videoStream');
            var currentSrc = img.src;
            img.src = currentSrc.split('?')[0] + '?t=' + new Date().getTime();
        }}, 30000); // Toutes les 30 secondes
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    print("=== LOGITECH C270 - SURVEILLANCE HD AVEC GESTION D'ERREURS ===")
    print("Démarrage du serveur...")
    
    # Générer et sauvegarder le fichier HTML
    save_html_file()
    
    # Obtenir l'adresse IP pour l'affichage
    ip_address = get_local_ip()
    
    print(f"Accédez à http://{ip_address}:5000")
    print("Résolution: 1280x720 HD")
    print("Backend: DSHOW (Windows)")
    print(f"Dossier des captures: {motion_captures_dir}")
    print("Détection de mouvement: Active")
    print("Captures automatiques: Activées")
    print("\nFichier HTML disponible à:")
    print(r"L:\Groups\mediatheque\06- SECTEUR INFORMATIQUE\7- SALLE JVO\cam.html")
    
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)