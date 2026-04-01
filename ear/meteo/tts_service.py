"""
Service de Text-to-Speech
"""
from gtts import gTTS
import pygame
import os
from datetime import datetime
import tempfile
from typing import Dict, List, Optional

class TTSService:
    def __init__(self, config):
        self.config = config
        pygame.mixer.init()
    
    def generate_weather_report(self, weather_summary: Dict) -> str:
        """
        Génère un rapport textuel à partir des données
        """
        report_parts = []
        
        # En-tête
        report_parts.append(f"Bulletin pour {weather_summary['date']}")
        report_parts.append(f"Localisation : {weather_summary['location']}")
        report_parts.append("")
        
        # Températures
        temp = weather_summary['temperature']
        report_parts.append("Températures :")
        report_parts.append(f"  Minimum : {temp['min']} degrés")
        report_parts.append(f"  Maximum : {temp['max']} degrés")
        report_parts.append(f"  Ressenti entre {temp['feels_like_min']} et {temp['feels_like_max']} degrés")
        report_parts.append("")
        
        # Conditions
        conditions = weather_summary['conditions']
        main_condition = conditions['main'].lower()
        
        if main_condition == 'clear':
            condition_desc = "Ciel dégagé"
        elif main_condition == 'clouds':
            condition_desc = "Ciel nuageux"
        elif main_condition == 'rain':
            condition_desc = "Pluie"
        elif main_condition == 'snow':
            condition_desc = "Neige"
        elif main_condition == 'thunderstorm':
            condition_desc = "Orages"
        else:
            condition_desc = conditions['descriptions'][0] if conditions['descriptions'] else "Conditions variables"
        
        report_parts.append(f"Conditions : {condition_desc}")
        
        # Précipitations
        precip = weather_summary['precipitation']
        if precip['rain_mm'] > 0:
            report_parts.append(f"Précipitations : {precip['rain_mm']} millimètres de pluie")
        if precip['snow_mm'] > 0:
            report_parts.append(f"Précipitations : {precip['snow_mm']} millimètres de neige")
        if precip['probability'] > 30:
            report_parts.append(f"Probabilité de pluie : {precip['probability']} pour cent")
        report_parts.append("")
        
        # Vent
        wind = weather_summary['wind']
        if wind['average_speed'] > 5:
            wind_desc = "venté"
            if wind['average_speed'] > 10:
                wind_desc = "très venté"
            report_parts.append(f"Vent : {wind['average_speed']} kilomètres par heure en moyenne, {wind_desc}")
        
        # Recommandations
        recommendations = weather_summary['recommendations']
        if recommendations['clothing']:
            report_parts.append("")
            report_parts.append("Recommandations vestimentaires :")
            for item in recommendations['clothing'][:3]:  # Limiter à 3 items
                report_parts.append(f"  • {item}")
        
        if recommendations['precautions']:
            report_parts.append("")
            report_parts.append("Précautions :")
            for precaution in recommendations['precautions']:
                report_parts.append(f"  • {precaution}")
        
        # Conclusion
        report_parts.append("")
        report_parts.append("Bon courage pour votre journée !")
        
        return "\n".join(report_parts)
    
    def text_to_speech(self, text: str, output_format: str = 'mp3') -> str:
        """
        Convertit le texte en parole
        """
        tts_config = self.config.tts_config
        
        try:
            # Créer un objet TTS
            tts = gTTS(
                text=text,
                lang=tts_config['lang'],
                slow=tts_config['slow']
            )
            
            if output_format == 'mp3':
                # Générer un nom de fichier unique
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"meteo_{timestamp}.mp3"
                
                # Sauvegarder le fichier
                tts.save(filename)
                print(f"Fichier audio généré : {filename}")
                return filename
            
            else:  # TTS direct
                # Créer un fichier temporaire
                with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp_file:
                    temp_filename = tmp_file.name
                
                # Sauvegarder et jouer
                tts.save(temp_filename)
                self.play_audio(temp_filename)
                
                # Nettoyer
                if not self.config.app_config['keep_audio_files']:
                    os.unlink(temp_filename)
                
                return "played"
                
        except Exception as e:
            print(f"Erreur lors de la synthèse vocale : {e}")
            return None
    
    def play_audio(self, filename: str):
        """
        Joue un fichier audio
        """
        try:
            pygame.mixer.music.load(filename)
            pygame.mixer.music.play()
            
            # Attendre la fin de la lecture
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)
                
        except Exception as e:
            print(f"Erreur lors de la lecture audio : {e}")
    
    def cleanup_old_files(self, max_files: int = 10):
        """
        Nettoie les anciens fichiers audio
        """
        mp3_files = [f for f in os.listdir('.') if f.endswith('.mp3') and f.startswith('meteo_')]
        
        if len(mp3_files) > max_files:
            # Trier par date (le plus ancien en premier)
            mp3_files.sort(key=lambda x: os.path.getmtime(x))
            
            # Supprimer les plus anciens
            for file_to_delete in mp3_files[:-max_files]:
                try:
                    os.remove(file_to_delete)
                    print(f"Fichier supprimé : {file_to_delete}")
                except Exception as e:
                    print(f"Erreur lors de la suppression de {file_to_delete} : {e}")