import socket

def check_port(port):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        return result == 0  # 0 means port is open/in use
    except:
        return False

# Test common development ports
ports_to_test = [5001, 5002, 5003, 8000, 8080, 3000, 3001, 8888]
print("Checking port availability on localhost:")
for port in ports_to_test:
    if not check_port(port):
        print(f"✅ Port {port} appears available")
    else:
        print(f"❌ Port {port} is in use")