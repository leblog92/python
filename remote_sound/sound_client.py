import socket
import json
import argparse
import sys

class SoundClient:
    def __init__(self, server_ip, port=5000):
        self.server_ip = server_ip
        self.port = port
    
    def send_command(self, command_type, data):
        """Send command to server"""
        command = {
            'type': command_type,
            'data': data
        }
        
        try:
            # Create socket and connect
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(5)  # 5 second timeout
            client_socket.connect((self.server_ip, self.port))
            
            # Send command
            client_socket.send(json.dumps(command).encode('utf-8'))
            
            # Receive response
            response = client_socket.recv(4096).decode('utf-8')
            response_data = json.loads(response)
            
            client_socket.close()
            return response_data
            
        except socket.timeout:
            return {"status": "error", "message": "Connection timeout"}
        except ConnectionRefusedError:
            return {"status": "error", "message": "Connection refused. Is the server running?"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def play_sound(self, sound_path):
        """Command to play sound"""
        return self.send_command('sound', sound_path)
    
    def text_to_speech(self, text):
        """Command to speak text"""
        return self.send_command('tts', text)
    
    def ping(self):
        """Check if server is reachable"""
        return self.send_command('ping', '')

def main():
    parser = argparse.ArgumentParser(description='Remote Sound Client')
    parser.add_argument('server_ip', help='IP address of the server')
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Play sound command
    sound_parser = subparsers.add_parser('play', help='Play a sound file')
    sound_parser.add_argument('filepath', help='Path to sound file')
    
    # TTS command
    tts_parser = subparsers.add_parser('tts', help='Text to speech')
    tts_parser.add_argument('text', help='Text to speak')
    
    # Ping command
    ping_parser = subparsers.add_parser('ping', help='Ping server')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    client = SoundClient(args.server_ip)
    
    if args.command == 'play':
        result = client.play_sound(args.filepath)
    elif args.command == 'tts':
        result = client.text_to_speech(args.text)
    elif args.command == 'ping':
        result = client.ping()
    
    print(f"Status: {result['status']}")
    if 'message' in result:
        print(f"Message: {result['message']}")

if __name__ == "__main__":
    main()