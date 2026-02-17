import cv2
import sys

print(f"Version d'OpenCV: {cv2.__version__}")
print(f"Version de Python: {sys.version}")

# Vérifier les fonctionnalités ArUco
print("\nFonctionnalités ArUco disponibles:")
print(f"cv2.aruco existe: {hasattr(cv2, 'aruco')}")

if hasattr(cv2, 'aruco'):
    print(f"Méthodes disponibles dans cv2.aruco:")
    methods = [m for m in dir(cv2.aruco) if not m.startswith('_')]
    print(methods[:10])  # Afficher les 10 premières méthodes
    
    # Vérifier les dictionnaires disponibles
    dicts = [d for d in dir(cv2.aruco) if 'DICT' in d]
    print(f"\nDictionnaires ArUco disponibles: {dicts[:5]}")

print("\nTest de détection ArUco:")
try:
    # Méthode moderne
    dict_aruco = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_250)
    print("✓ getPredefinedDictionary fonctionne")
except:
    try:
        # Ancienne méthode
        dict_aruco = cv2.aruco.Dictionary_get(cv2.aruco.DICT_6X6_250)
        print("✓ Dictionary_get fonctionne")
    except:
        print("✗ Aucune méthode de dictionnaire ne fonctionne")