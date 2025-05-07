from flask import Flask, request, jsonify
import os
import io
import contextlib
import librosa
import torch
from collections import OrderedDict
from transformers import WhisperProcessor, WhisperForConditionalGeneration

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

app = Flask(__name__)

# Mapping from language keys to model directories
MODEL_MAPPING = {
    "en": "Whisper/openai_whisper-medium.en",
    "fr": "Whisper/bofenghuang_whisper-medium-french",
    "es": "Whisper/zuazo_whisper-medium-es",
    "xx-large": "Whisper/openai_whisper-large-v2",
    "xx-medium": "Whisper/openai_whisper-medium",
}

# LRU model cache
class ModelManager:
    def __init__(self, max_models=2):
        self.cache = OrderedDict()
        self.max_models = max_models

    def get_model(self, lang_key):
        model_dir = MODEL_MAPPING.get(lang_key)
        if not model_dir:
            raise ValueError(f"No model mapping found for language key: {lang_key}")

        if lang_key in self.cache:
            self.cache.move_to_end(lang_key)
            return self.cache[lang_key]

        # Load model and processor
        processor = WhisperProcessor.from_pretrained(model_dir)
        model = WhisperForConditionalGeneration.from_pretrained(model_dir)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model.to(device)

        # Evict LRU if needed
        if len(self.cache) >= self.max_models:
            evicted_key, _ = self.cache.popitem(last=False)
            print(f"Evicted model: {evicted_key}")

        self.cache[lang_key] = {"processor": processor, "model": model, "device": device}
        return self.cache[lang_key]

# Instantiate model manager
model_manager = ModelManager(max_models=2)

def suppress_stderr(func, *args, **kwargs):
    with open(os.devnull, 'w') as devnull, contextlib.redirect_stderr(devnull):
        return func(*args, **kwargs)

def transcribe_audio(audio_file, lang_key):
    # Load audio
    audio_bytes = audio_file.read()
    audio_file_obj = io.BytesIO(audio_bytes)
    audio, sr = suppress_stderr(librosa.load, audio_file_obj, sr=16000)

    # Load model and processor from manager
    model_data = model_manager.get_model(lang_key)
    processor = model_data["processor"]
    model = model_data["model"]
    device = model_data["device"]

    if PSUTIL_AVAILABLE:
        process = psutil.Process()
        print(f"Using model '{lang_key}'. Memory usage: {process.memory_info().rss / (1024*1024):.2f} MB")

    # Prepare input and transcribe
    force_language = lang_key if lang_key in ("en", "fr", "es") else None
    if force_language:
        inputs = processor(audio, sampling_rate=16000, return_tensors="pt", language=force_language)
        inputs.input_features = inputs.input_features.to(device)
        forced_decoder_ids = processor.get_decoder_prompt_ids(language=force_language, task="transcribe")
        generated_ids = model.generate(inputs.input_features, forced_decoder_ids=forced_decoder_ids) if forced_decoder_ids else model.generate(inputs.input_features)
    else:
        inputs = processor(audio, sampling_rate=16000, return_tensors="pt")
        inputs.input_features = inputs.input_features.to(device)
        generated_ids = model.generate(inputs.input_features)

    transcription = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
    return transcription

@app.route('/transcribe', methods=['POST'])
def transcribe():
    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file provided'}), 400

    audio_file = request.files['audio']
    lang_key = request.form.get('lang_key', 'en').lower()

    try:
        transcription = transcribe_audio(audio_file, lang_key)
        return jsonify({'transcription': transcription})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/device', methods=['GET'])
def get_device():
    device = "GPU" if torch.cuda.is_available() else "CPU"
    return jsonify({"device": device})

@app.route('/languages', methods=['GET'])
def get_languages():
    return jsonify({"languages": list(MODEL_MAPPING.keys())})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
