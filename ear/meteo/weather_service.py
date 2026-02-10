"""
Service de récupération et traitement des données météo
"""
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

class WeatherService:
    def __init__(self, config):
        self.config = config
        self.base_url = "https://api.openweathermap.org/data/2.5"
        
    def get_forecast(self) -> Optional[Dict]:
        """
        Récupère les prévisions météo sur 5 jours
        """
        url = f"{self.base_url}/forecast"
        
        params = {
            'lat': self.config.coordinates['lat'],
            'lon': self.config.coordinates['lon'],
            'appid': self.config.api_key,
            'units': self.config.weather_config['units'],
            'lang': self.config.weather_config['lang'],
            'cnt': 40  # 5 jours * 8 prévisions par jour
        }
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Erreur lors de la récupération des données météo: {e}")
            return None
    
    def get_tomorrow_forecast(self, forecast_data: Dict) -> List[Dict]:
        """
        Extrait les prévisions pour demain
        """
        if not forecast_data or 'list' not in forecast_data:
            return []
        
        forecasts = forecast_data['list']
        tomorrow = datetime.now() + timedelta(days=1)
        tomorrow_date = tomorrow.date()
        
        tomorrow_forecasts = []
        
        for forecast in forecasts:
            forecast_time = datetime.fromtimestamp(forecast['dt'])
            if forecast_time.date() == tomorrow_date:
                tomorrow_forecasts.append(forecast)
        
        return tomorrow_forecasts
    
    def analyze_tomorrow_weather(self, tomorrow_forecasts: List[Dict]) -> Dict:
        """
        Analyse les prévisions pour demain et génère un résumé
        """
        if not tomorrow_forecasts:
            return {'error': 'Aucune donnée disponible'}
        
        # Données de température
        temperatures = [f['main']['temp'] for f in tomorrow_forecasts]
        feels_like = [f['main']['feels_like'] for f in tomorrow_forecasts]
        
        # Conditions météo
        weather_conditions = []
        for forecast in tomorrow_forecasts:
            for weather in forecast['weather']:
                weather_conditions.append({
                    'main': weather['main'],
                    'description': weather['description'],
                    'icon': weather['icon']
                })
        
        # Précipitations
        total_rain = sum(f.get('rain', {}).get('3h', 0) for f in tomorrow_forecasts)
        total_snow = sum(f.get('snow', {}).get('3h', 0) for f in tomorrow_forecasts)
        
        # Vent
        wind_speeds = [f['wind']['speed'] for f in tomorrow_forecasts]
        wind_gusts = [f['wind'].get('gust', 0) for f in tomorrow_forecasts]
        
        # Humidité
        humidities = [f['main']['humidity'] for f in tomorrow_forecasts]
        
        # Trouver les prévisions pour différents moments de la journée
        morning_forecast = self._find_forecast_by_time(tomorrow_forecasts, 8)
        afternoon_forecast = self._find_forecast_by_time(tomorrow_forecasts, 14)
        evening_forecast = self._find_forecast_by_time(tomorrow_forecasts, 20)
        
        # Générer le résumé
        summary = {
            'date': (datetime.now() + timedelta(days=1)).strftime('%d/%m/%Y'),
            'location': self.config.app_config['location_name'],
            
            'temperature': {
                'min': round(min(temperatures), 1),
                'max': round(max(temperatures), 1),
                'average': round(sum(temperatures) / len(temperatures), 1),
                'feels_like_min': round(min(feels_like), 1),
                'feels_like_max': round(max(feels_like), 1),
            },
            
            'conditions': {
                'main': self._get_main_condition(weather_conditions),
                'descriptions': list(set([w['description'] for w in weather_conditions])),
                'icons': list(set([w['icon'] for w in weather_conditions]))
            },
            
            'precipitation': {
                'rain_mm': round(total_rain, 1),
                'snow_mm': round(total_snow, 1),
                'probability': self._calculate_precipitation_probability(tomorrow_forecasts)
            },
            
            'wind': {
                'average_speed': round(sum(wind_speeds) / len(wind_speeds), 1),
                'max_gust': round(max(wind_gusts), 1) if wind_gusts else 0,
                'direction': tomorrow_forecasts[0]['wind'].get('deg', 'N/A')
            },
            
            'humidity': {
                'min': min(humidities),
                'max': max(humidities),
                'average': round(sum(humidities) / len(humidities))
            },
            
            'day_parts': {
                'morning': morning_forecast,
                'afternoon': afternoon_forecast,
                'evening': evening_forecast
            },
            
            'recommendations': self._generate_recommendations(
                min(temperatures), max(temperatures), total_rain, total_snow
            )
        }
        
        return summary
    
    def _find_forecast_by_time(self, forecasts: List[Dict], target_hour: int) -> Optional[Dict]:
        """Trouve la prévision la plus proche d'une heure cible"""
        closest = None
        min_diff = float('inf')
        
        for forecast in forecasts:
            forecast_hour = datetime.fromtimestamp(forecast['dt']).hour
            diff = abs(forecast_hour - target_hour)
            
            if diff < min_diff:
                min_diff = diff
                closest = forecast
        
        return closest
    
    def _get_main_condition(self, conditions: List[Dict]) -> str:
        """Détermine la condition météo principale"""
        condition_priority = {
            'Thunderstorm': 1,
            'Drizzle': 2,
            'Rain': 3,
            'Snow': 4,
            'Atmosphere': 5,
            'Clear': 6,
            'Clouds': 7
        }
        
        main_conditions = [c['main'] for c in conditions]
        return min(main_conditions, key=lambda x: condition_priority.get(x, 99))
    
    def _calculate_precipitation_probability(self, forecasts: List[Dict]) -> int:
        """Calcule la probabilité de précipitation"""
        rainy_forecasts = sum(1 for f in forecasts if f.get('rain', {}).get('3h', 0) > 0)
        probability = int((rainy_forecasts / len(forecasts)) * 100)
        return min(probability, 100)
    
    def _generate_recommendations(self, temp_min: float, temp_max: float, 
                                 rain: float, snow: float) -> Dict:
        """Génère des recommandations basées sur la météo"""
        recommendations = {
            'clothing': [],
            'activities': [],
            'precautions': []
        }
        
        # Recommandations vestimentaires
        if temp_max < 5:
            recommendations['clothing'].extend([
                "Manteau d'hiver",
                "Écharpe et gants",
                "Chaussures chaudes"
            ])
        elif temp_max < 15:
            recommendations['clothing'].extend([
                "Veste",
                "Pull ou sweat",
                "Chaussures fermées"
            ])
        elif temp_max < 25:
            recommendations['clothing'].extend([
                "T-shirt ou chemise",
                "Veste légère",
                "Tenue confortable"
            ])
        else:
            recommendations['clothing'].extend([
                "T-shirt léger",
                "Short ou jupe",
                "Chapeau ou casquette",
                "Lunettes de soleil"
            ])
        
        # Recommandations pour la pluie
        if rain > 5:
            recommendations['clothing'].append("Parapluie ou imperméable")
            recommendations['precautions'].append("Prévoyez un parapluie")
            recommendations['activities'].append("Activités en intérieur")
        elif rain > 0:
            recommendations['precautions'].append("Petite averse possible")
        
        # Recommandations pour la neige
        if snow > 0:
            recommendations['clothing'].extend([
                "Bottes de neige",
                "Gants chauds",
                "Bonnet"
            ])
            recommendations['precautions'].append("Attention aux routes glissantes")
        
        # Recommandations pour le vent
        recommendations['precautions'].append(
            "Consultez les prévisions avant de sortir"
        )
        
        return recommendations