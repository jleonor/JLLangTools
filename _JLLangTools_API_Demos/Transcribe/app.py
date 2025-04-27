import os
import json
import pathlib
import urllib.parse
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory, abort, send_file
import pathlib
import requests
from werkzeug.utils import secure_filename

# Helpers
from utils.atomic_queue import AtomicQueue
from utils.request_utils import save_request

# ── Setup directories ────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)

# ensure each pipeline queue file exists
for fname in (
    'converter.queue',
    'chunker.queue',
    'transcriber.queue',
    'assembler.queue',
    'cleaner.queue'
):
    open(os.path.join(DATA_DIR, fname), 'a').close()

# initialize the converter queue
a_converter = AtomicQueue(os.path.join(DATA_DIR, 'converter.queue'))

# load API settings
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, '..', '..'))
SETTINGS_PATH = os.path.join(PROJECT_ROOT, 'appsettings.json')
with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
    settings = json.load(f)
API_URL = settings['transcribe']['api_url']

# ── Flask app ──────────────────────────────────────────────────────────────────
app = Flask(__name__)

@app.route('/')
def index():
    try:
        r = requests.get(f"{API_URL}/device")
        device = r.json().get('device', 'Unknown')
    except Exception:
        device = 'Unknown'
    return render_template('index.html', device=device)

@app.route('/languages')
def get_languages():
    r = requests.get(f"{API_URL}/languages")
    return jsonify(r.json())

@app.route('/transcribe', methods=['POST'])
def transcribe():
    # 1) Validate file
    audio = request.files.get('audio')
    if not audio:
        return jsonify({'error': 'No file uploaded'}), 400

    # 2) Secure filename
    filename = secure_filename(audio.filename)
    basename, ext = os.path.splitext(filename)

    # 3) Timestamp folder
    now = datetime.now()
    date_part = now.strftime('%Y_%m_%d')
    time_part = now.strftime('%H_%M_%S')
    clean_ts = f"{date_part}__{time_part}"

    # 4) Make subfolder
    lang = request.form.get('lang_key') or 'unknown'
    subfolder_name = f"{clean_ts}_{lang}_{basename}"
    subfolder_path = os.path.join(DATA_DIR, subfolder_name)
    os.makedirs(subfolder_path, exist_ok=True)

    # 5) Save original audio
    saved_path = os.path.join(subfolder_path, filename)
    audio.save(saved_path)

    # 6) Collect segments
    raw_segments = request.form.get('segments', '[]')
    try:
        seg_list = json.loads(raw_segments)
    except ValueError:
        seg_list = []

    # 7) Build req_info + default tasks
    sent_time = datetime.utcnow().isoformat()
    req_info = {
        'audio_filename': filename,
        'lang_key':       lang,
        'segments':       seg_list,
        'sent_time':      sent_time,
        'tasks': {
            'converterCompleted':   None,
            'chunkerCompleted':     None,
            'transcriberCompleted': None,
            'assemblerCompleted':   None,
            'cleanerCompleted':     None
        }
    }

    # 8) Atomically write request.json
    save_request(subfolder_path, req_info)

    # 9) Enqueue for conversion
    a_converter.enqueue(subfolder_name)

    # 10) Forward to external API (passthrough)
    files = {'audio': open(saved_path, 'rb')}
    data  = {'lang_key': lang}
    for seg in seg_list:
        start = seg.get('start', '').strip()
        end   = seg.get('end', '').strip()
        if start and end:
            data.setdefault('segments', []).append(f"{start}-{end}")

    try:
        resp = requests.post(f"{API_URL}/transcribe", files=files, data=data)
        resp.raise_for_status()
        return jsonify(resp.json()), resp.status_code
    except requests.RequestException as e:
        text = e.response.text if e.response is not None else str(e)
        code = e.response.status_code if e.response is not None else 500
        return text, code

# ── New: Files Browser ──────────────────────────────────────────────────────────
@app.route('/files')
def files_index():
    # fetch device for navbar
    try:
        r = requests.get(f"{API_URL}/device")
        device = r.json().get('device', 'Unknown')
    except Exception:
        device = 'Unknown'

    batches = []
    for name in os.listdir(DATA_DIR):
        sub = os.path.join(DATA_DIR, name)
        rq = os.path.join(sub, 'request.json')
        if os.path.isdir(sub) and os.path.exists(rq):
            info = json.load(open(rq, 'r', encoding='utf-8'))
            info['folder'] = name
            info['sent_time_dt'] = datetime.fromisoformat(info['sent_time'])
            batches.append(info)
    # sort descending by sent_time
    batches.sort(key=lambda b: b['sent_time_dt'], reverse=True)

    return render_template('files.html', batches=batches, device=device)

@app.route('/download/<path:subpath>')
def download_file(subpath):
    # Build the secure path
    safe = pathlib.Path(DATA_DIR) / pathlib.Path(subpath)
    try:
        safe = safe.resolve().relative_to(DATA_DIR)
    except Exception:
        abort(404)

    full_path = pathlib.Path(DATA_DIR) / safe
    if not full_path.is_file():
        abort(404)

    # send_file takes the filesystem path directly and sets Content-Disposition for you
    return send_file(str(full_path), as_attachment=True)


@app.route('/files/content')
def file_content():
    raw = urllib.parse.unquote(request.args.get('path', ''))
    safe = pathlib.Path(DATA_DIR) / pathlib.Path(raw)
    try:
        safe.relative_to(DATA_DIR)
    except ValueError:
        return ('', 404)
    if not safe.exists() or not safe.is_file():
        return ('', 404)

    text = safe.read_text(encoding='utf-8')
    if safe.suffix.lower() == '.json':
        return text, 200, {'Content-Type': 'application/json; charset=utf-8'}
    else:
        return text, 200, {'Content-Type': 'text/plain; charset=utf-8'}

if __name__ == '__main__':
    app.run(debug=True, port=6001)
