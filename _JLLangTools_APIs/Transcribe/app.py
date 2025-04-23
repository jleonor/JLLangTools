from flask import Flask, request, jsonify
import os
import io
import contextlib
import librosa
import torch
from transformers import WhisperProcessor, WhisperForConditionalGeneration
import psutil  # Optional, for logging memory usage

app = Flask(__name__)

# Mapping from language keys to model directories
MODEL_MAPPING = {
    "en": "Whisper/openai_whisper-medium.en",
    "fr": "Whisper/bofenghuang_whisper-medium-french",
    "es": "Whisper/zuazo_whisper-medium-es",
    "xx-large": "Whisper/openai_whisper-large-v2",
    "xx-medium": "Whisper/openai_whisper-medium",
}


def suppress_stderr(func, *args, **kwargs):
    """Helper to run a function while suppressing stderr output."""
    with open(os.devnull, 'w') as devnull, contextlib.redirect_stderr(devnull):
        return func(*args, **kwargs)

def transcribe_audio(audio_file, lang_key):
    """
    Transcribe an audio file using the specified Whisper model.
    Expects a file-like object and a language key.
    """
    # Read the uploaded file into a BytesIO stream
    audio_bytes = audio_file.read()
    audio_file_obj = io.BytesIO(audio_bytes)

    # Load audio using librosa (forcing a sample rate of 16000 Hz)
    audio, sr = suppress_stderr(librosa.load, audio_file_obj, sr=16000)

    # Determine the model directory from the mapping
    model_dir = MODEL_MAPPING.get(lang_key)
    if model_dir is None:
        raise ValueError(f"No model mapping found for language key: {lang_key}")

    # For supported languages, force language in the processor call
    force_language = lang_key if lang_key in ("en", "fr", "es") else None

    # Load the processor and model from the specified model directory
    processor = WhisperProcessor.from_pretrained(model_dir)
    model = WhisperForConditionalGeneration.from_pretrained(model_dir)

    # Move model to GPU if available
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    # Optional: log memory usage if psutil is available
    if psutil:
        process = psutil.Process()
        print(f"Starting transcription. Memory usage: {process.memory_info().rss / (1024*1024):.2f} MB")

    # Process the audio and generate transcription
    if force_language:
        inputs = processor(audio, sampling_rate=16000, return_tensors="pt", language=force_language)
        # Move input features to the same device as the model
        inputs.input_features = inputs.input_features.to(device)
        forced_decoder_ids = processor.get_decoder_prompt_ids(language=force_language, task="transcribe")
        if forced_decoder_ids and len(forced_decoder_ids) > 0:
            generated_ids = model.generate(inputs.input_features, forced_decoder_ids=forced_decoder_ids)
        else:
            generated_ids = model.generate(inputs.input_features)
    else:
        inputs = processor(audio, sampling_rate=16000, return_tensors="pt")
        inputs.input_features = inputs.input_features.to(device)
        generated_ids = model.generate(inputs.input_features)

    transcription = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
    return transcription

@app.route('/transcribe', methods=['POST'])
def transcribe():
    """
    API endpoint that transcribes an uploaded audio file.
    Expects form-data with:
      - "audio": the audio file
      - "lang_key": optional language key (defaults to "en")
    """
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
    """
    Endpoint to check whether GPU is available.
    """
    device = "GPU" if torch.cuda.is_available() else "CPU"
    return jsonify({"device": device})

@app.route('/test', methods=['GET'])
def test():
    return jsonify({"message": "Test endpoint works!"})


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')



