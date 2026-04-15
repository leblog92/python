#!/usr/bin/env python3
"""
VoiceForge — TTS avec edge-tts (Python 3.13 compatible)
Voix neurales Microsoft très naturelles, multilingues.
"""

import os, json, uuid, time, asyncio, sys
from pathlib import Path
from flask import Flask, request, jsonify, render_template, send_from_directory

app = Flask(__name__, template_folder="templates", static_folder="static")

BASE_DIR     = Path(__file__).parent
PHRASES_FILE = BASE_DIR / "phrases.json"
AUDIO_DIR    = BASE_DIR / "static" / "audio"
WAV_DIR      = BASE_DIR / "voices"

AUDIO_DIR.mkdir(parents=True, exist_ok=True)
WAV_DIR.mkdir(parents=True, exist_ok=True)

# ── Voix edge-tts disponibles ─────────────────────────────────────────────────
VOICES = {
    "fr": [
        {"id": "fr-FR-DeniseNeural",   "label": "Denise (FR, féminin)"},
        {"id": "fr-FR-HenriNeural",    "label": "Henri (FR, masculin)"},
        {"id": "fr-FR-EloiseNeural",   "label": "Éloïse (FR, féminin)"},
        {"id": "fr-BE-CharlineNeural", "label": "Charline (BE, féminin)"},
        {"id": "fr-CH-ArianeNeural",   "label": "Ariane (CH, féminin)"},
        {"id": "fr-CA-SylvieNeural",   "label": "Sylvie (CA, féminin)"},
    ],
    "en": [
        {"id": "en-US-JennyNeural",  "label": "Jenny (US, féminin)"},
        {"id": "en-US-GuyNeural",    "label": "Guy (US, masculin)"},
        {"id": "en-GB-SoniaNeural",  "label": "Sonia (UK, féminin)"},
        {"id": "en-GB-RyanNeural",   "label": "Ryan (UK, masculin)"},
    ],
    "es": [
        {"id": "es-ES-ElviraNeural", "label": "Elvira (ES, féminin)"},
        {"id": "es-MX-DaliaNeural",  "label": "Dalia (MX, féminin)"},
    ],
    "de": [
        {"id": "de-DE-KatjaNeural",  "label": "Katja (DE, féminin)"},
        {"id": "de-DE-ConradNeural", "label": "Conrad (DE, masculin)"},
    ],
    "it": [
        {"id": "it-IT-ElsaNeural",   "label": "Elsa (IT, féminin)"},
        {"id": "it-IT-DiegoNeural",  "label": "Diego (IT, masculin)"},
    ],
    "pt": [
        {"id": "pt-BR-FranciscaNeural", "label": "Francisca (BR, féminin)"},
        {"id": "pt-PT-RaquelNeural",    "label": "Raquel (PT, féminin)"},
    ],
    "nl": [
        {"id": "nl-NL-ColetteNeural", "label": "Colette (NL, féminin)"},
    ],
    "zh": [
        {"id": "zh-CN-XiaoxiaoNeural", "label": "Xiaoxiao (CN, féminin)"},
        {"id": "zh-CN-YunxiNeural",    "label": "Yunxi (CN, masculin)"},
    ],
    "ja": [
        {"id": "ja-JP-NanamiNeural", "label": "Nanami (JP, féminin)"},
        {"id": "ja-JP-KeitaNeural",  "label": "Keita (JP, masculin)"},
    ],
    "ar": [
        {"id": "ar-SA-ZariyahNeural", "label": "Zariyah (SA, féminin)"},
        {"id": "ar-EG-SalmaNeural",   "label": "Salma (EG, féminin)"},
    ],
}

# ── Phrases helpers ────────────────────────────────────────────────────────────
def load_phrases():
    if PHRASES_FILE.exists():
        with open(PHRASES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_phrases(phrases):
    with open(PHRASES_FILE, "w", encoding="utf-8") as f:
        json.dump(phrases, f, ensure_ascii=False, indent=2)

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/voices", methods=["GET"])
def api_voices():
    return jsonify(VOICES)

@app.route("/api/voices/upload", methods=["POST"])
def upload_voice():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f = request.files["file"]
    if not f.filename.lower().endswith(".wav"):
        return jsonify({"error": "WAV uniquement"}), 400
    dest = WAV_DIR / f.filename
    f.save(dest)
    return jsonify({"filename": f.filename}), 201

@app.route("/api/voices/uploaded", methods=["GET"])
def list_uploaded():
    wavs = [f.name for f in WAV_DIR.glob("*.wav")]
    return jsonify(wavs)

@app.route("/api/phrases", methods=["GET"])
def get_phrases():
    return jsonify(load_phrases())

@app.route("/api/phrases", methods=["POST"])
def add_phrase():
    data = request.json
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Text requis"}), 400
    phrases = load_phrases()
    entry = {
        "id":      str(uuid.uuid4()),
        "text":    text,
        "voice":   data.get("voice", ""),
        "lang":    data.get("lang", "fr"),
        "rate":    data.get("rate", "+0%"),
        "pitch":   data.get("pitch", "+0Hz"),
        "created": int(time.time()),
    }
    phrases.append(entry)
    save_phrases(phrases)
    return jsonify(entry), 201

@app.route("/api/phrases/<pid>", methods=["DELETE"])
def delete_phrase(pid):
    phrases = load_phrases()
    new_phrases = [p for p in phrases if p["id"] != pid]
    if len(new_phrases) == len(phrases):
        return jsonify({"error": "Not found"}), 404
    save_phrases(new_phrases)
    return jsonify({"deleted": pid})

@app.route("/api/synthesize", methods=["POST"])
def synthesize():
    data  = request.json
    text  = (data.get("text") or "").strip()
    voice = (data.get("voice") or "").strip()
    rate  = data.get("rate", "+0%")
    pitch = data.get("pitch", "+0Hz")

    if not text:
        return jsonify({"error": "Texte requis"}), 400
    if not voice:
        return jsonify({"error": "Voix requise"}), 400

    out_name = f"{uuid.uuid4().hex}.mp3"
    out_path = AUDIO_DIR / out_name

    try:
        async def run():
            import edge_tts
            communicate = edge_tts.Communicate(
                text=text, voice=voice, rate=rate, pitch=pitch,
            )
            await communicate.save(str(out_path))

        asyncio.run(run())
        return jsonify({"url": f"/static/audio/{out_name}", "engine": "edge-tts"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/static/audio/<filename>")
def serve_audio(filename):
    return send_from_directory(AUDIO_DIR, filename)

if __name__ == "__main__":
    try:
        import edge_tts
        print("✅ edge-tts OK")
    except ImportError:
        print("⚠️  Installer : pip install edge-tts")
        sys.exit(1)
    print("🎙️  VoiceForge — http://127.0.0.1:5000")
    app.run(debug=True, port=5000)