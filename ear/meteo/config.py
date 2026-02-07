# config.py
import os
from dotenv import load_dotenv

class Config:
    def __init__(self):
        load_dotenv()
        
    @property
    def openweather_api_key(self):
        key = os.getenv('OPENWEATHER_API_KEY')
        if not key:
            raise ValueError("OPENWEATHER_API_KEY non définie")
        return key
    
    @property
    def coordinates(self):
        return {
            'lat': os.getenv('LATITUDE', '48.8014'),
            'lon': os.getenv('LONGITUDE', '2.1301')
        }