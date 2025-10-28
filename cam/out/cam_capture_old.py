import cv2
import flask
import numpy as np
import datetime
import os
from flask import Response, request

app = flask.Flask(__name__)
camera = cv2.VideoCapture(0)

# Variables pour la détection de mouvement
motion_detected = False
last_frame = None
motion_threshold = 1000  # Seuil de sensibilité (à ajuster)
capture_count = 0
MAX_CAPTURES = 200  # Nombre maximum de captures à conserver

# Créer le dossier de captures s'il n'existe pas
if not os.path.exists('motion_captures'):
    os.makedirs('motion_captures')

def detect_motion(current_frame):
    global last_frame, motion_detected
    
    # Conversion en niveaux de gris et flou
    gray = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (21, 21), 0)
    
    if last_frame is None:
        last_frame = gray
        return False, current_frame
    
    # Calcul de la différence entre les frames
    frame_diff = cv2.absdiff(last_frame, gray)
    thresh = cv2.threshold(frame_diff, 25, 255, cv2.THRESH_BINARY)[1]
    thresh = cv2.dilate(thresh, None, iterations=2)
    
    # Trouver les contours
    contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    motion_detected = False
    output_frame = current_frame.copy()
    
    for contour in contours:
        if cv2.contourArea(contour) > motion_threshold:
            motion_detected = True
            # Dessiner le rectangle autour du mouvement
            (x, y, w, h) = cv2.boundingRect(contour)
            cv2.rectangle(output_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(output_frame, "MOTION DETECTED", (10, 30), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
    
    last_frame = gray
    return motion_detected, output_frame

def save_capture(frame):
    global capture_count
    
    # Gestion du nombre maximum de captures
    if capture_count >= MAX_CAPTURES:
        # Supprimer les anciennes captures (on garde les 50 plus récentes)
        files = sorted(os.listdir('motion_captures'))
        for old_file in files[:-50]:
            os.remove(os.path.join('motion_captures', old_file))
        capture_count = 50
    
    # Sauvegarde avec timestamp
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"motion_captures/motion_{timestamp}.png"
    cv2.imwrite(filename, frame)
    capture_count += 1
    print(f"Capture sauvegardee: {filename}")
    
    return filename

def generate_frames():
    global motion_detected
    motion_cooldown = 0
    
    while True:
        success, frame = camera.read()
        if not success:
            break
        
        # Détection de mouvement
        motion_detected, processed_frame = detect_motion(frame)
        
        # Capture automatique si mouvement détecté
        if motion_detected and motion_cooldown == 0:
            save_capture(frame)
            motion_cooldown = 30  # Cooldown de 30 frames (~1 seconde)
        
        if motion_cooldown > 0:
            motion_cooldown -= 1
        
        # Encodage pour le streaming
        ret, buffer = cv2.imencode('.jpg', processed_frame)
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
    <html>
        <head>
            <title>Webcam avec Detection de Mouvement</title>
        </head>
        <body>
            <h1>Streaming Webcam avec Detection de Mouvement</h1>
            <img src="/video_feed" width="800" height="600">
            <br>
            <a href="/captures">Voir les captures</a> | 
            <a href="/manual_capture">Capture manuelle</a> |
            <a href="/status">Status</a>
        </body>
    </html>
    '''

@app.route('/manual_capture')
def manual_capture():
    success, frame = camera.read()
    if success:
        filename = save_capture(frame)
        return f'Capture manuelle effectuee: <a href="/captures/{os.path.basename(filename)}">Voir</a>'
    return 'Erreur lors de la capture'

@app.route('/captures')
def list_captures():
    files = sorted(os.listdir('motion_captures'), reverse=True)
    html = '<h1>Captures de mouvement</h1><ul>'
    for file in files[:20]:  # Afficher les 20 plus récentes
        html += f'<li><a href="/captures/{file}">{file}</a></li>'
    html += '</ul>'
    return html

@app.route('/captures/<filename>')
def get_capture(filename):
    return flask.send_from_directory('motion_captures', filename)

@app.route('/status')
def status():
    global capture_count, motion_detected
    return f'''
    <h1>Status du systeme</h1>
    <p>Captures sauvegardees: {capture_count}</p>
    <p>Mouvement detecte: {motion_detected}</p>
    <p>Dossier captures: {os.path.abspath('motion_captures')}</p>
    <a href="/">Retour au stream</a>
    '''

@app.route('/config', methods=['GET', 'POST'])
def config():
    global motion_threshold
    
    if request.method == 'POST':
        motion_threshold = int(request.form.get('threshold', motion_threshold))
        return f'Seuil modifie: {motion_threshold} <a href="/config">Retour</a>'
    
    return f'''
    <h1>Configuration</h1>
    <form method="POST">
        <label>Seuil de detection (actuel: {motion_threshold}):</label>
        <input type="number" name="threshold" value="{motion_threshold}">
        <small>(Plus bas = plus sensible)</small><br><br>
        <input type="submit" value="Appliquer">
    </form>
    <a href="/">Retour au stream</a>
    '''

if __name__ == '__main__':
    print("Démarrage du serveur...")
    print("Accédez à http://localhost:5000")
    print("Dossier des captures:", os.path.abspath('motion_captures'))
    app.run(host='0.0.0.0', port=5000, debug=False)