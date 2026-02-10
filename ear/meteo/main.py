"""
Application principale Météo Ouest Parisien
"""
import sys
import os

# Ajouter le répertoire courant au path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import Config
from weather_service import WeatherService
from tts_service import TTSService

class MeteoApp:
    def __init__(self):
        """Initialise l'application"""
        print("=" * 50)
        print("   APPLICATION MÉTÉO - OUEST PARISIEN")
        print("=" * 50)
        
        # Charger la configuration
        try:
            self.config = Config()
        except ValueError as e:
            print(f"\n❌ ERREUR DE CONFIGURATION : {e}")
            print("\nInstructions :")
            print("1. Copiez .env.example en .env")
            print("2. Éditez .env avec votre clé API OpenWeatherMap")
            print("3. Obtenez une clé gratuite sur : https://openweathermap.org/api")
            sys.exit(1)
        
        # Initialiser les services
        self.weather_service = WeatherService(self.config)
        self.tts_service = TTSService(self.config)
    
    def display_menu(self):
        """Affiche le menu principal"""
        print("\n" + "=" * 30)
        print("MENU PRINCIPAL")
        print("=" * 30)
        print("1. Voir les prévisions détaillées")
        print("2. Générer un fichier MP3")
        print("3. Écouter directement (TTS)")
        print("4. Afficher la configuration")
        print("5. Nettoyer les fichiers audio")
        print("0. Quitter")
        print("=" * 30)
    
    def run(self):
        """Exécute l'application"""
        while True:
            self.display_menu()
            
            try:
                choice = input("\nVotre choix (0-5) : ").strip()
                
                if choice == '0':
                    print("\nAu revoir ! Bonne journée")
                    break
                
                elif choice == '1':
                    self.show_detailed_forecast()
                
                elif choice == '2':
                    self.generate_mp3()
                
                elif choice == '3':
                    self.play_tts_direct()
                
                elif choice == '4':
                    self.show_config()
                
                elif choice == '5':
                    self.cleanup_audio_files()
                
                else:
                    print("\nChoix invalide. Veuillez réessayer.")
                    
                input("\nAppuyez sur Entrée pour continuer...")
                
            except KeyboardInterrupt:
                print("\n\nInterruption. Au revoir !")
                break
            except Exception as e:
                print(f"\nErreur : {e}")
    
    def show_detailed_forecast(self):
        """Affiche les prévisions détaillées"""
        print("\n" + "=" * 50)
        print("PRÉVISIONS DÉTAILLÉES POUR DEMAIN")
        print("=" * 50)
        
        # Récupérer les données
        print("Récupération des données météo...")
        forecast_data = self.weather_service.get_forecast()
        
        if not forecast_data:
            print("Impossible de récupérer les données météo.")
            return
        
        # Analyser les données
        tomorrow_forecasts = self.weather_service.get_tomorrow_forecast(forecast_data)
        
        if not tomorrow_forecasts:
            print("Aucune prévision disponible pour demain.")
            return
        
        weather_summary = self.weather_service.analyze_tomorrow_weather(tomorrow_forecasts)
        
        # Afficher le résumé
        print(f"\n{weather_summary['location']} - {weather_summary['date']}")
        print("=" * 30)
        
        # Températures
        temp = weather_summary['temperature']
        print(f"\nTEMPERATURES")
        print(f"   Minimum : {temp['min']}°C")
        print(f"   Maximum : {temp['max']}°C")
        print(f"   Ressenti : {temp['feels_like_min']}°C à {temp['feels_like_max']}°C")
        
        # Conditions
        conditions = weather_summary['conditions']
        print(f"\nCONDITIONS")
        print(f"   {conditions['main']}")
        if conditions['descriptions']:
            print(f"   {', '.join(conditions['descriptions'])}")
        
        # Précipitations
        precip = weather_summary['precipitation']
        if precip['rain_mm'] > 0 or precip['snow_mm'] > 0:
            print(f"\nPRECIPITATIONS")
            if precip['rain_mm'] > 0:
                print(f"   Pluie : {precip['rain_mm']} mm")
            if precip['snow_mm'] > 0:
                print(f"   Neige : {precip['snow_mm']} mm")
            if precip['probability'] > 0:
                print(f"   Probabilité : {precip['probability']}%")
        
        # Vent
        wind = weather_summary['wind']
        if wind['average_speed'] > 0:
            print(f"\nVENT")
            print(f"   Vitesse : {wind['average_speed']} km/h")
            if wind['max_gust'] > 0:
                print(f"   Rafales : {wind['max_gust']} km/h")
        
        # Recommandations
        recommendations = weather_summary['recommendations']
        if recommendations['clothing']:
            print(f"\nRECOMMANDATIONS")
            print("   Vetements :")
            for item in recommendations['clothing'][:3]:
                print(f"     • {item}")
    
    def generate_mp3(self):
        """Génère un fichier MP3 avec la météo"""
        print("\n" + "=" * 50)
        print("GENERATION DE FICHIER MP3")
        print("=" * 50)
        
        # Récupérer les données
        print("Récupération des données météo...")
        forecast_data = self.weather_service.get_forecast()
        
        if not forecast_data:
            print("Impossible de récupérer les données météo.")
            return
        
        # Analyser les données
        tomorrow_forecasts = self.weather_service.get_tomorrow_forecast(forecast_data)
        
        if not tomorrow_forecasts:
            print("Aucune prévision disponible pour demain.")
            return
        
        weather_summary = self.weather_service.analyze_tomorrow_weather(tomorrow_forecasts)
        
        # Générer le rapport
        weather_report = self.tts_service.generate_weather_report(weather_summary)
        
        print("\nRapport météo généré :")
        print("-" * 40)
        print(weather_report)
        print("-" * 40)
        
        # Convertir en MP3
        print("\nConversion en MP3...")
        filename = self.tts_service.text_to_speech(weather_report, 'mp3')
        
        if filename:
            print(f"\nFichier audio créé : {filename}")
            
            # Demander si l'utilisateur veut écouter
            play = input("\nVoulez-vous écouter le fichier maintenant ? (o/n) : ").lower()
            if play == 'o':
                self.tts_service.play_audio(filename)
        else:
            print("Erreur lors de la génération du fichier audio.")
    
    def play_tts_direct(self):
        """Joue la météo directement sans sauvegarder"""
        print("\n" + "=" * 50)
        print("ECOUTE DIRECTE (TTS)")
        print("=" * 50)
        
        # Récupérer les données
        print("Récupération des données météo...")
        forecast_data = self.weather_service.get_forecast()
        
        if not forecast_data:
            print("Impossible de récupérer les données météo.")
            return
        
        # Analyser les données
        tomorrow_forecasts = self.weather_service.get_tomorrow_forecast(forecast_data)
        
        if not tomorrow_forecasts:
            print("Aucune prévision disponible pour demain.")
            return
        
        weather_summary = self.weather_service.analyze_tomorrow_weather(tomorrow_forecasts)
        
        # Générer le rapport
        weather_report = self.tts_service.generate_weather_report(weather_summary)
        
        print("\nBulletin météo :")
        print("-" * 40)
        print(weather_report[:200] + "..." if len(weather_report) > 200 else weather_report)
        print("-" * 40)
        
        # Jouer directement
        print("\nLecture audio en cours...")
        result = self.tts_service.text_to_speech(weather_report, 'tts')
        
        if result == "played":
            print("\nLecture terminée.")
        else:
            print("Erreur lors de la lecture audio.")
    
    def show_config(self):
        """Affiche la configuration actuelle (sans la clé API)"""
        print("\n" + "=" * 50)
        print("CONFIGURATION")
        print("=" * 50)
        
        print(f"\nLocalisation :")
        print(f"   Nom : {self.config.app_config['location_name']}")
        print(f"   Latitude : {self.config.coordinates['lat']}")
        print(f"   Longitude : {self.config.coordinates['lon']}")
        
        print(f"\nMétéo :")
        print(f"   Unités : {self.config.weather_config['units']}")
        print(f"   Langue : {self.config.weather_config['lang']}")
        
        print(f"\nAudio :")
        print(f"   Langue TTS : {self.config.tts_config['lang']}")
        print(f"   Vitesse : {'lente' if self.config.tts_config['slow'] else 'normale'}")
        print(f"   Format : {self.config.app_config['audio_format']}")
        
        print(f"\nClé API : {'Configurée' if self.config.api_key else 'Non configurée'}")
    
    def cleanup_audio_files(self):
        """Nettoie les anciens fichiers audio"""
        print("\n" + "=" * 50)
        print("NETTOYAGE DES FICHIERS AUDIO")
        print("=" * 50)
        
        self.tts_service.cleanup_old_files()
        print("\nNettoyage terminé.")

def main():
    """Point d'entrée principal de l'application"""
    try:
        app = MeteoApp()
        app.run()
    except KeyboardInterrupt:
        print("\n\nApplication interrompue. Au revoir !")
    except Exception as e:
        print(f"\nErreur inattendue : {e}")

if __name__ == "__main__":
    main()