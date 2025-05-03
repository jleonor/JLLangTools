import os
import json
import pathlib
import urllib.parse
import re
from datetime import datetime
from markupsafe import Markup
from flask import Flask, render_template, request, jsonify, send_file, abort
import requests
from werkzeug.utils import secure_filename

from analytics.dashboard import init_dashboard
from utils.atomic_queue import AtomicQueue
from utils.request_utils import save_request

# Setup paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)

for fname in ('converter.queue', 'chunker.queue', 'transcriber.queue', 'assembler.queue', 'cleaner.queue'):
    open(os.path.join(DATA_DIR, fname), 'a').close()

# Load settings
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, '..', '..'))
with open(os.path.join(PROJECT_ROOT, 'appsettings.json'), 'r', encoding='utf-8') as f:
    settings = json.load(f)
API_URL = settings['transcribe']['api_url']

# Flask app
app = Flask(__name__)
a_converter = AtomicQueue(os.path.join(DATA_DIR, 'converter.queue'))
dash_app = init_dashboard(app, api_url=API_URL)

# Filters
app.template_filter('format_duration')
def format_duration(ms):
    seconds = ms // 1000
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02}:{m:02}:{s:02}"

# Regex for log preview
LOG_RE = re.compile(
    r'^(?P<date>\d{4}-\d{2}-\d{2})\s+'
    r'(?P<time>\d{2}:\d{2}:\d{2})\s+'
    r'(?P<level>\w+):\s+'
    r'(?P<msg>.*)$'
)

@app.route('/')
def index():
    device, languages = get_device_and_languages()
    return render_template('index.html', device=device, languages=languages)


def get_device_and_languages():
    try:
        device = requests.get(f"{API_URL}/device").json().get('device', 'Unknown')
    except:
        device = 'Unknown'
    try:
        langs = requests.get(f"{API_URL}/languages").json().get('languages', [])
    except:
        langs = []
    return device, langs

@app.route('/transcribe', methods=['POST'])
def transcribe():
    audio = request.files.get('audio')
    if not audio:
        return jsonify({'error': 'No file uploaded'}), 400

    filename = secure_filename(audio.filename)
    basename, ext = os.path.splitext(filename)
    now = datetime.now()
    clean_ts = now.strftime('%Y_%m_%d__%H_%M_%S')
    lang = request.form.get('lang_key') or 'unknown'
    subfolder_name = f"{clean_ts}_{lang}_{basename}"
    subfolder_path = os.path.join(DATA_DIR, subfolder_name)
    os.makedirs(subfolder_path, exist_ok=True)
    audio.save(os.path.join(subfolder_path, filename))

    try:
        seg_list = json.loads(request.form.get('segments', '[]'))
    except ValueError:
        seg_list = []

    sent_time = datetime.utcnow().isoformat()
    req_info = {
        'audio_filename': filename,
        'lang_key': lang,
        'segments': seg_list,
        'sent_time': sent_time,
        'tasks': {k: None for k in (
            'converterCompleted', 'chunkerCompleted', 'transcriberCompleted',
            'assemblerCompleted', 'cleanerCompleted')}
    }
    save_request(subfolder_path, req_info)
    a_converter.enqueue(subfolder_name)

    return jsonify({'status': 'queued', 'folder': subfolder_name})

@app.route('/files')
def files_index():
    device, _ = get_device_and_languages()
    batches = []
    for name in sorted(os.listdir(DATA_DIR), reverse=True):
        sub = os.path.join(DATA_DIR, name)
        rq_path = os.path.join(sub, 'request.json')
        if not (os.path.isdir(sub) and os.path.exists(rq_path)):
            continue
        with open(rq_path, 'r', encoding='utf-8') as f:
            info = json.load(f)
        info['folder'] = name
        info['sent_time_dt'] = datetime.fromisoformat(info['sent_time'])
        info['completed'] = all(v for v in info.get('tasks', {}).values())
        info['segments'] = get_segment_count(sub)
        batches.append(info)
    return render_template('files.html', batches=batches, device=device)


def get_segment_count(folder):
    return len([f for f in os.listdir(folder) if f.startswith('segment_')])

@app.route('/files/preview')
def preview_file():
    raw_path = urllib.parse.unquote(request.args.get('path', ''))
    safe = pathlib.Path(DATA_DIR) / pathlib.Path(raw_path)
    try:
        safe = safe.resolve().relative_to(DATA_DIR)
    except Exception:
        abort(404)
    full = pathlib.Path(DATA_DIR) / safe
    if not full.is_file():
        abort(404)

    ext = full.suffix.lower()
    if full.name == 'request.json':
        return preview_request(full)
    elif full.name.endswith('chunks_mapping.json'):
        return preview_chunks_mapping(full)
    elif full.name.endswith('text_mappings.json'):
        return preview_text_mappings(full)
    elif ext == '.srt':
        return preview_srt(full)
    elif ext == '.log':
        return preview_log(full)
    else:
        return Markup(f"<pre>{full.read_text('utf-8')}</pre>")

# Request preview (unchanged)
def preview_request(path):
    data = json.load(open(path, 'r', encoding='utf-8'))
    html = '<ul class="batch-meta">'
    html += f"<li>Audio Filename: {data.get('audio_filename')}</li>"
    html += f"<li>Language: {data.get('lang_key')}</li>"
    html += f"<li>Sent Time: {data.get('sent_time')}</li>"
    html += '</ul><table class="batch-table"><tr><th>Task</th><th>Status</th><th>Timestamp</th></tr>'
    for key, label in {
        'converterCompleted': 'Conversion',
        'chunkerCompleted': 'Chunking',
        'transcriberCompleted': 'Transcription',
        'assemblerCompleted': 'Assembling',
        'cleanerCompleted': 'Cleaning'
    }.items():
        ts = data.get('tasks', {}).get(key)
        emoji = '✅' if ts else '⌛'
        ts_disp = ts if ts else 'Pending'
        html += f"<tr><td>{label}</td><td>{emoji}</td><td>{ts_disp}</td></tr>"
    html += '</table>'
    return Markup(html)

# Updated chunks mapping preview with text-mappings merge
def preview_chunks_mapping(path):
    # Load chunk mappings
    chunks = json.load(open(path, 'r', encoding='utf-8'))
    rows = chunks if isinstance(chunks, list) else chunks.get('chunks', [])
    # Attempt to load text mappings from same directory
    tm_path = path.parent / 'text_mapping.json'
    text_map = {}
    if tm_path.exists():
        tms = json.load(open(tm_path, 'r', encoding='utf-8'))
        tm_rows = tms if isinstance(tms, list) else tms.get('mappings', [])
        for m in tm_rows:
            # normalize separators
            key = m.get('audio_file', '').replace('\\', '/')
            text_map[key] = m.get('text_file', '')
    # Build table
    html = ('<table class="mapping-table">'
            '<tr><th>Start</th><th>End</th><th>Chunk File</th><th>Text File</th></tr>')
    for c in rows:
        # timings
        start_ms = c.get('start_ms') if c.get('start_ms') is not None else c.get('start')
        end_ms = c.get('end_ms') if c.get('end_ms') is not None else c.get('end')
        if start_ms is None or end_ms is None:
            start_fmt = end_fmt = ''
        else:
            start_fmt = format_duration(start_ms)
            end_fmt = format_duration(end_ms)
        # chunk and text file
        chunk_file = c.get('chunk_file', '')
        norm_chunk = chunk_file.replace('\\', '/')
        text_file = text_map.get(norm_chunk, '')
        html += ('<tr>'
                 f'<td>{start_fmt}</td>'
                 f'<td>{end_fmt}</td>'
                 f'<td>{Markup.escape(chunk_file)}</td>'
                 f'<td>{Markup.escape(text_file)}</td>'
                 '</tr>')
    html += '</table>'
    return Markup(html)

# Text mappings preview (unchanged)
def preview_text_mappings(path):
    mappings = json.load(open(path, 'r', encoding='utf-8'))
    rows = mappings if isinstance(mappings, list) else mappings.get('mappings', [])
    html = '<table class="mapping-table"><tr><th>Audio File</th><th>Text File</th></tr>'
    for m in rows:
        html += ('<tr>'
                 f'<td>{Markup.escape(m.get('audio_file', ''))}</td>'
                 f'<td>{Markup.escape(m.get('text_file', ''))}</td>'
                 '</tr>')
    html += '</table>'
    return Markup(html)

# SRT preview (unchanged)
def preview_srt(path):
    text = path.read_text('utf-8')
    blocks = text.strip().split('\n\n')
    html = '<table class="mapping-table"><tr><th>#</th><th>Start</th><th>End</th><th>Text</th></tr>'
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) >= 2:
            idx, times = lines[0], lines[1]
            raw_start, raw_end = times.split('-->')
            start = raw_start.strip().split(',')[0]
            end = raw_end.strip().split(',')[0]
            content = ' '.join(lines[2:]).strip()
            html += ('<tr>'
                     f'<td>{idx}</td>'
                     f'<td>{start}</td>'
                     f'<td>{end}</td>'
                     f'<td>{Markup.escape(content)}</td>'
                     '</tr>')
    html += '</table>'
    return Markup(html)

# Log preview (unchanged)
def preview_log(path):
    lines = path.read_text('utf-8').splitlines()
    html = '<table class="mapping-table"><tr><th>Date</th><th>Time</th><th>Level</th><th>Message</th></tr>'
    for line in lines:
        m = LOG_RE.match(line)
        if m:
            html += ('<tr>'
                     f'<td>{m.group('date')}</td>'
                     f'<td>{m.group('time')}</td>'
                     f'<td>{m.group('level')}</td>'
                     f'<td>{Markup.escape(m.group('msg'))}</td>'
                     '</tr>')
        else:
            html += f"<tr><td colspan=4>{Markup.escape(line)}</td></tr>"
    html += '</table>'
    return Markup(html)

@app.route('/download/<path:subpath>')
def download_file(subpath):
    safe = pathlib.Path(DATA_DIR) / pathlib.Path(subpath)
    try:
        safe = safe.resolve().relative_to(DATA_DIR)
    except Exception:
        abort(404)
    full_path = pathlib.Path(DATA_DIR) / safe

    folder = full_path.parent
    request_path = folder / 'request.json'
    if request_path.exists():
        req = json.load(open(request_path, 'r', encoding='utf-8'))
        if not all(req.get('tasks', {}).values()):
            abort(403)

    if not full_path.is_file():
        abort(404)

    return send_file(str(full_path), as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True, port=6001)