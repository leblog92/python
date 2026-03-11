# web_server.py
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import sys
import threading
import platform
import subprocess
import pygame
import tempfile
from gtts import gTTS
import uuid

# Add the current directory to path to import ear.py
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)
CORS(app, origins=['*'])  # Enable CORS for ALL origins

# Audio recognizer instance
audio_recognizer = None

@app.route('/play_sound', methods=['POST', 'OPTIONS'])
def play_sound():
    """Handle sound play requests"""
    if request.method == 'OPTIONS':
        return handle_preflight()
    
    try:
        data = request.json
        command = data.get('command', '').lower().strip()
        
        print(f"[SERVER] Received command: '{command}'")
        
        # Check if it's a system command
        if command in audio_recognizer.system_actions:
            print(f"[SERVER] Executing system command: {command}")
            threading.Thread(
                target=audio_recognizer.executer_action_systeme,
                args=(audio_recognizer.system_actions[command],),
                daemon=True
            ).start()
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

@app.route('/play_mp3', methods=['POST', 'OPTIONS'])
def play_mp3():
    """Play a specific MP3 file"""
    if request.method == 'OPTIONS':
        return handle_preflight()
    
    try:
        data = request.json
        filename = data.get('filename', '')
        
        # Security: prevent directory traversal
        filename = os.path.basename(filename)
        
        # Look in sounds directory
        sound_path = os.path.join('sounds', filename)
        
        if os.path.exists(sound_path):
            print(f"[SERVER] Playing MP3: {filename}")
            threading.Thread(
                target=audio_recognizer.jouer_audio,
                args=(sound_path,),
                daemon=True
            ).start()
            
            return jsonify({
                'status': 'success',
                'message': f'Playing: {filename}'
            })
        else:
            return jsonify({
                'status': 'error',
                'message': f'File not found: {filename}'
            }), 404
            
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/tts', methods=['POST', 'OPTIONS'])
def text_to_speech():
    """Convert text to speech and play it"""
    if request.method == 'OPTIONS':
        return handle_preflight()
    
    try:
        data = request.json
        text = data.get('text', '')
        lang = data.get('lang', 'fr')  # Default to French
        
        if not text:
            return jsonify({'status': 'error', 'message': 'No text provided'}), 400
        
        print(f"[SERVER] TTS: '{text}' ({lang})")
        
        # Create a unique filename
        temp_filename = f"tts_{uuid.uuid4().hex[:8]}.mp3"
        temp_path = os.path.join(tempfile.gettempdir(), temp_filename)
        
        # Generate TTS
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.save(temp_path)
        
        # Play the audio
        def play_and_cleanup():
            try:
                pygame.mixer.music.load(temp_path)
                pygame.mixer.music.play()
                
                # Wait for playback to finish
                while pygame.mixer.music.get_busy():
                    pygame.time.wait(100)
                    
            except Exception as e:
                print(f"[SERVER] TTS playback error: {e}")
            finally:
                # Clean up temp file
                try:
                    os.remove(temp_path)
                except:
                    pass
        
        threading.Thread(target=play_and_cleanup, daemon=True).start()
        
        return jsonify({
            'status': 'success',
            'message': f'TTS played: {text[:50]}...'
        })
        
    except Exception as e:
        print(f"[SERVER] TTS error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/list_sounds', methods=['GET'])
def list_sounds():
    """List all available sound files"""
    try:
        sounds_dir = 'sounds'
        if os.path.exists(sounds_dir):
            files = [f for f in os.listdir(sounds_dir) if f.endswith('.mp3')]
            return jsonify({
                'status': 'success',
                'sounds': files
            })
        else:
            return jsonify({'status': 'error', 'message': 'Sounds directory not found'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/list_commands', methods=['GET'])
def list_commands():
    """List all available commands"""
    return jsonify({
        'status': 'success',
        'audio_commands': list(audio_recognizer.commands.keys()),
        'system_commands': list(audio_recognizer.system_actions.keys())
    })

@app.route('/status', methods=['GET'])
def status():
    """Get server status"""
    return jsonify({
        'status': 'running',
        'listening': audio_recognizer.is_listening if audio_recognizer else False,
        'commands_count': len(audio_recognizer.commands) if audio_recognizer else 0,
        'system_actions_count': len(audio_recognizer.system_actions) if audio_recognizer else 0
    })

@app.route('/cam.html', methods=['GET'])
def serve_cam():
    """Serve the CAM.html file"""
    try:
        return send_from_directory('.', 'cam.html')
    except:
        return "CAM.html not found. Please create the file or check the path.", 404

@app.route('/')
def index():
    """Default route"""
    host = request.host.split(':')[0] if request else 'localhost'
    port = 5000
    
    html_content = f"""
    <html>
        <head>
            <title>Voice Control Server</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; background: #f0f0f0; }}
                .container {{ max-width: 800px; margin: auto; background: white; padding: 20px; border-radius: 10px; }}
                h1 {{ color: #333; }}
                .endpoint {{ background: #e8e8e8; padding: 10px; margin: 10px 0; border-radius: 5px; }}
                code {{ background: #ddd; padding: 2px 5px; border-radius: 3px; }}
                .success {{ color: green; }}
                .info {{ background: #e3f2fd; padding: 10px; border-radius: 5px; margin: 10px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🎤 Voice Control Server</h1>
                <p class="success">✅ Server is running!</p>
                
                <div class="info">
                    <strong>Server URL:</strong> http://{host}:{port}<br>
                    <strong>CAM Interface:</strong> <a href="/cam.html">http://{host}:{port}/cam.html</a>
                </div>
                
                <h2>Available Endpoints:</h2>
                
                <div class="endpoint">
                    <strong>POST /play_sound</strong> - Play command sound<br>
                    <code>{{"command": "bonjour"}}</code>
                </div>
                
                <div class="endpoint">
                    <strong>POST /play_mp3</strong> - Play specific MP3 file<br>
                    <code>{{"filename": "bonjour.mp3"}}</code>
                </div>
                
                <div class="endpoint">
                    <strong>POST /tts</strong> - Text to Speech<br>
                    <code>{{"text": "Bonjour le monde", "lang": "fr"}}</code>
                </div>
                
                <div class="endpoint">
                    <strong>GET /list_sounds</strong> - List available MP3 files
                </div>
                
                <div class="endpoint">
                    <strong>GET /list_commands</strong> - List available voice commands
                </div>
                
                <div class="endpoint">
                    <strong>GET /status</strong> - Server status
                </div>
                
                <h2>Testing with curl:</h2>
                <code>curl -X POST http://{host}:{port}/tts -H "Content-Type: application/json" -d '{{"text":"Bonjour tout le monde"}}'</code>
                
                <h2>Server Info:</h2>
                <p>Host: {host}</p>
                <p>Port: {port}</p>
                <p>Local IP: {get_local_ip()}</p>
            </div>
        </body>
    </html>
    """
    return html_content

def handle_preflight():
    """Handle CORS preflight requests"""
    response = jsonify({'status': 'preflight'})
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
    return response

def start_web_server(recognizer, host='0.0.0.0', port=5000):
    """Start the Flask web server"""
    global audio_recognizer
    audio_recognizer = recognizer
    
    # Get local IP
    local_ip = get_local_ip()
    
    print("\n" + "="*60)
    print("🌐 WEB SERVER STARTED")
    print("="*60)
    print(f"📍 Local URL:    http://127.0.0.1:{port}")
    print(f"📍 Network URL:  http://{local_ip}:{port}")
    print(f"📍 CAM Interface: http://{local_ip}:{port}/cam.html")
    print("\n📡 Available on your local network!")
    print("\n🎯 Test commands:")
    print(f"   curl -X POST http://{local_ip}:{port}/tts -H \"Content-Type: application/json\" -d '{{\"text\":\"Test vocal\"}}'")
    print(f"   curl http://{local_ip}:{port}/status")
    print("="*60 + "\n")
    
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
    
    # Initialize pygame mixer if not already done
    if not pygame.mixer.get_init():
        pygame.mixer.init()
    
    # Start web server
    start_web_server(recognizer)