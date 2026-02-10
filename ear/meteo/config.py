"""
Configuration sécurisée de l'application météo
"""
import os
from dotenv import load_dotenv

class Config:
    def __init__(self):
        """Charge la configuration depuis les variables d'environnement"""
        # Charger .env si présent
        load_dotenv()
        
        # Valider la configuration
        self._validate_config()
    
    def _validate_config(self):
        """Valide que toutes les configurations nécessaires sont présentes"""
        required_vars = ['OPENWEATHER_API_KEY']
        
        for var in required_vars:
            if not os.getenv(var):
                raise ValueError(f"Variable d'environnement manquante: {var}")
    
    @property
    def api_key(self):
        """Clé API OpenWeatherMap"""
        return os.getenv('OPENWEATHER_API_KEY')
    
    @property
    def coordinates(self):
        """Coordonnées GPS"""
        return {
            'lat': float(os.getenv('LATITUDE', '48.8014')),
            'lon': float(os.getenv('LONGITUDE', '2.1301'))
        }
    
    @property
    def weather_config(self):
        """Configuration de l'API météo"""
        return {
            'units': os.getenv('UNITS', 'metric'),
            'lang': os.getenv('LANGUAGE', 'fr')
        }
    
    @property
    def tts_config(self):
        """Configuration du Text-to-Speech"""
        return {
            'lang': os.getenv('TTS_LANG', 'fr'),
            'slow': os.getenv('TTS_SLOW', 'false').lower() == 'true'
        }
    
    @property
    def app_config(self):
        """Configuration de l'application"""
        return {
            'location_name': os.getenv('LOCATION_NAME', 'Ouest Parisien'),
            'audio_format': os.getenv('AUDIO_FORMAT', 'mp3'),
            'keep_audio_files': os.getenv('KEEP_AUDIO_FILES', 'false').lower() == 'true'
        }