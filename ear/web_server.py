# web_server.py
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import sys
import threading

# Add the current directory to path to import ear.py
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)
CORS(app)  # Enable CORS for ALL origins

# Audio recognizer instance
audio_recognizer = None

@app.route('/play_sound', methods=['POST', 'OPTIONS'])
def play_sound():
    """Handle sound play requests"""
    if request.method == 'OPTIONS':
        # Handle preflight requests
        response = jsonify({'status': 'preflight'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response
    
    try:
        data = request.json
        command = data.get('command', '').lower()
        
        print(f"[SERVER] Received command: {command}")
        
        # Check if it's a system command
        if command in audio_recognizer.system_actions:
            print(f"[SERVER] Executing system command: {command}")
            audio_recognizer.executer_action_systeme(audio_recognizer.system_actions[command])
            return jsonify({
                'status': 'success', 
                'message': f'Executed system command: {command}'
            })
        
        # Check if it's an audio command
        elif command in audio_recognizer.commands:
            sound_file = audio_recognizer.commands[command]
            print(f"[SERVER] Playing audio: {sound_file}")
            
            # Play in a separate thread to avoid blocking
            threading.Thread(
                target=audio_recognizer.jouer_audio,
                args=(sound_file,),
                daemon=True
            ).start()
            
            return jsonify({
                'status': 'success', 
                'message': f'Playing: {command}',
                'file': sound_file
            })
        
        else:
            return jsonify({
                'status': 'error', 
                'message': f'Command not found: {command}'
            }), 404
            
    except Exception as e:
        print(f"[SERVER] Error: {e}")
        return jsonify({
            'status': 'error', 
            'message': str(e)
        }), 500

@app.route('/commands', methods=['GET'])
def get_commands():
    """Get list of available commands"""
    return jsonify({
        'audio_commands': list(audio_recognizer.commands.keys()),
        'system_commands': list(audio_recognizer.system_actions.keys())
    })

@app.route('/cam', methods=['GET'])
@app.route('/cam.html', methods=['GET'])
def serve_cam():
    """Serve the CAM.html file"""
    return send_from_directory('.', 'CAM.html')

@app.route('/<path:filename>')
def serve_static(filename):
    """Serve static files"""
    return send_from_directory('.', filename)

@app.route('/')
def index():
    """Default route"""
    return """
    <html>
        <head><title>Voice Control Server</title></head>
        <body>
            <h1>Voice Control Server</h1>
            <p>Server is running!</p>
            <ul>
                <li><a href="/cam.html">Open CAM Interface</a></li>
                <li><a href="/commands">View Available Commands</a></li>
                <li>API Endpoint: POST /play_sound</li>
            </ul>
        </body>
    </html>
    """

def start_web_server(recognizer, host='0.0.0.0', port=5000):
    """Start the Flask web server"""
    global audio_recognizer
    audio_recognizer = recognizer
    
    print("\n" + "="*50)
    print("WEB SERVER STARTING")
    print("="*50)
    print(f"Local:    http://127.0.0.1:{port}")
    print(f"Network:  http://{get_local_ip()}:{port}")
    print(f"LAN URL:  http://10.151.0.66:{port} (if that's your IP)")
    print("\nAccess CAM interface at: http://<your-ip>:5000/cam.html")
    print("="*50 + "\n")
    
    # Disable Flask development server warning
    import warnings
    warnings.filterwarnings("ignore", message=".*development server.*")
    
    # Run Flask
    app.run(host=host, port=port, debug=False, threaded=True)

def get_local_ip():
    """Get local IP address"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

if __name__ == "__main__":
    # Import and create audio recognizer
    from ear import AudioCommandRecognizer
    recognizer = AudioCommandRecognizer()
    
    # Start web server
    start_web_server(recognizer)