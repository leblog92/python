"""Application Météo - TTS Direct Minimaliste"""
import sys
import os

# Hide console window on Windows
if sys.platform == "win32":
    import ctypes
    ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import Config
from weather_service import WeatherService
from tts_service import TTSService

def main():
    """Version ultra-simplifiée - juste le TTS"""
    try:
        # Configuration
        config = Config()
        
        # Services
        weather_service = WeatherService(config)
        tts_service = TTSService(config)
        
        # Données météo
        forecast_data = weather_service.get_forecast()
        if not forecast_data:
            print("Erreur : impossible de récupérer les données météo")
            return
            
        tomorrow_forecasts = weather_service.get_tomorrow_forecast(forecast_data)
        if not tomorrow_forecasts:
            print("Erreur : pas de prévisions pour demain")
            return
            
        # Analyse
        weather_summary = weather_service.analyze_tomorrow_weather(tomorrow_forecasts)
        
        # Génération et lecture
        weather_report = tts_service.generate_weather_report(weather_summary)
        tts_service.text_to_speech(weather_report, 'tts')
        
    except Exception as e:
        print(f"Erreur : {e}")

if __name__ == "__main__":
    main()