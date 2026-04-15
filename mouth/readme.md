# VoiceForge — Installation Windows (Python 3.13)

## Installation (3 commandes)

```
pip install flask edge-tts
python app.py
```

Puis ouvrir http://127.0.0.1:5000

## Copier votre fichier WAV (Windows)
```
copy ma_voix.wav voices\
```

## Fonctionnalités
- Voix neurales Microsoft (edge-tts) — très naturelles, multilingues
- 10 langues, ~20 voix sélectionnables
- Contrôle vitesse (-50% à +100%) et hauteur (-20Hz à +20Hz)
- Phrases pré-écrites + zone texte libre
- Sauvegarde/lecture/suppression dans phrases.json (avec mémo voix/langue/paramètres)
- Upload WAV de référence (mémo personnel)
- Nécessite une connexion internet (edge-tts utilise les serveurs Microsoft)