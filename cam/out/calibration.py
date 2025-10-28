    # Script de test pour régler manuellement
def camera_calibration_tool():
    camera = cv2.VideoCapture(0)
    
    # Valeurs initiales
    exposure = -6
    brightness = 100
    gain = 40
    
    while True:
        camera.set(cv2.CAP_PROP_EXPOSURE, exposure)
        camera.set(cv2.CAP_PROP_BRIGHTNESS, brightness)
        camera.set(cv2.CAP_PROP_GAIN, gain)
        
        ret, frame = camera.read()
        if not ret:
            break
            
        # Affichage des valeurs actuelles
        cv2.putText(frame, f"Exposure: {exposure}", (10, 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(frame, f"Brightness: {brightness}", (10, 60), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(frame, f"Gain: {gain}", (10, 90), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(frame, "Q/A: Exposure | W/S: Brightness | E/D: Gain | ESC: Quit", 
                   (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        cv2.imshow('C270 Calibration Tool', frame)
        
        key = cv2.waitKey(1) & 0xFF
        if key == 27:  # ESC
            break
        elif key == ord('q'):
            exposure = min(0, exposure + 1)
        elif key == ord('a'):
            exposure = max(-10, exposure - 1)
        elif key == ord('w'):
            brightness = min(255, brightness + 5)
        elif key == ord('s'):
            brightness = max(0, brightness - 5)
        elif key == ord('e'):
            gain = min(100, gain + 5)
        elif key == ord('d'):
            gain = max(0, gain - 5)
    
    camera.release()
    cv2.destroyAllWindows()
    
    print(f"Paramètres optimaux trouvés:")
    print(f"  Exposure: {exposure}")
    print(f"  Brightness: {brightness}")
    print(f"  Gain: {gain}")

# Décommentez pour utiliser l'outil de calibration
camera_calibration_tool()