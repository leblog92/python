import socket
import threading
import json
import sys
import os
from pathlib import Path

class SoundServer:
    def __init__(self, host='0.0.0.0', port=5000):
        self.host = host
        self.port = port
        self.running = True
        
    def play_sound(self, sound_path):
        """Play a sound file"""
        try:
            if not os.path.exists(sound_path):
                return {"status": "error", "message": "File not found"}
            
            # Use winsound for .wav files
            if sound_path.lower().endswith('.wav'):
                import winsound
                winsound.PlaySound(sound_path, winsound.SND_FILENAME)
                return {"status": "success", "message": f"Played {sound_path}"}
            else:
                # For other formats, use pygame if available
                try:
                    import pygame
                    pygame.mixer.init()
                    pygame.mixer.music.load(sound_path)
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy():
                        continue
                    return {"status": "success", "message": f"Played {sound_path}"}
                except ImportError:
                    return {"status": "error", "message": "Install pygame for non-WAV files"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def text_to_speech(self, text):
        """Convert text to speech"""
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
            return {"status": "success", "message": f"Spoke: {text}"}
        except ImportError:
            try:
                # Try using Windows built-in TTS
                import win32com.client
                speaker = win32com.client.Dispatch("SAPI.SpVoice")
                speaker.Speak(text)
                return {"status": "success", "message": f"Spoke: {text}"}
            except:
                return {"status": "error", "message": "Install pyttsx3 or pywin32 for TTS"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def handle_client(self, client_socket, address):
        """Handle client connection"""
        print(f"[+] Connection from {address}")
        
        try:
            # Receive data
            data = client_socket.recv(4096).decode('utf-8')
            if not data:
                return
            
            command = json.loads(data)
            response = {}
            
            if command['type'] == 'sound':
                response = self.play_sound(command['data'])
            elif command['type'] == 'tts':
                response = self.text_to_speech(command['data'])
            elif command['type'] == 'ping':
                response = {"status": "success", "message": "pong"}
            else:
                response = {"status": "error", "message": "Unknown command"}
            
            # Send response
            client_socket.send(json.dumps(response).encode('utf-8'))
            
        except json.JSONDecodeError:
            error_response = {"status": "error", "message": "Invalid JSON"}
            client_socket.send(json.dumps(error_response).encode('utf-8'))
        except Exception as e:
            error_response = {"status": "error", "message": str(e)}
            client_socket.send(json.dumps(error_response).encode('utf-8'))
        finally:
            client_socket.close()
    
    def start(self):
        """Start the server"""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            server.bind((self.host, self.port))
            server.listen(5)
            print(f"[*] Server started on {self.host}:{self.port}")
            print("[*] Waiting for connections...")
            
            while self.running:
                client_socket, address = server.accept()
                client_thread = threading.Thread(
                    target=self.handle_client,
                    args=(client_socket, address)
                )
                client_thread.daemon = True
                client_thread.start()
                
        except KeyboardInterrupt:
            print("\n[*] Shutting down server...")
        except Exception as e:
            print(f"[!] Error: {e}")
        finally:
            server.close()
    
    def stop(self):
        """Stop the server"""
        self.running = False

def check_dependencies():
    """Check and install required packages"""
    required = ['pyttsx3']
    
    print("Checking dependencies...")
    for package in required:
        try:
            __import__(package)
            print(f"✓ {package} installed")
        except ImportError:
            print(f"✗ {package} not installed")
            install = input(f"Install {package}? (y/n): ").lower()
            if install == 'y':
                import subprocess
                subprocess.check_call([sys.executable, "-m", "pip", "install", package])
                print(f"✓ {package} installed successfully")

if __name__ == "__main__":
    print("Sound Server v1.0")
    print("=" * 50)
    
    # Check dependencies
    check_dependencies()
    
    # Get server IP
    import socket
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    print(f"\nYour IP address: {local_ip}")
    print(f"Server will listen on port: 5000")
    
    # Start server
    server = SoundServer()
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()