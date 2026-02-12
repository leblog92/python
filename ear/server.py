# server.py (or add to ear.py)
from flask import Flask, request, jsonify
from flask_cors import CORS
import threading
import subprocess
import os

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Store reference to your audio recognizer
audio_recognizer = None

@app.route('/play_sound', methods=['POST', 'OPTIONS'])
def play_sound():
    """Play a sound based on command"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json
    command = data.get('command', '')
    
    print(f"Received command: {command}")
    
    # Here you can trigger your audio player
    # For example, play corresponding MP3 file
    if command in audio_recognizer.commands:
        sound_file = audio_recognizer.commands[command]
        audio_recognizer.jouer_audio(sound_file)
        return jsonify({'status': 'success', 'message': f'Playing {sound_file}'})
    
    return jsonify({'status': 'error', 'message': 'Command not found'})

@app.route('/status', methods=['GET'])
def status():
    return jsonify({'status': 'running', 'port': 5000})

def start_server(recognizer):
    """Start the Flask server"""
    global audio_recognizer
    audio_recognizer = recognizer
    
    print("Starting web server on http://127.0.0.1:5000")
    print("CAM.html can now connect to this server")
    
    # Run Flask in a separate thread
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)

# In your main function or __main__ block:
if __name__ == "__main__":
    # Create your audio recognizer
    app = AudioCommandRecognizer()
    
    # Start the web server in background thread
    server_thread = threading.Thread(target=start_server, args=(app,))
    server_thread.daemon = True
    server_thread.start()
    
    # Start your main application
    app.demarrer()