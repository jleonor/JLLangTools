import os
import json
import pathlib
import urllib.parse
import re
from datetime import datetime, timezone
from markupsafe import Markup
from flask import Flask, render_template, request, jsonify, send_file, abort
import requests
from werkzeug.utils import secure_filename
from yt_dlp import YoutubeDL

from analytics.dashboard import init_dashboard
from utils.atomic_queue import AtomicQueue
from utils.request_utils import create_transcription_request

# ─── Setup paths ───────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)

# Ensure each queue file exists
for q in ('converter.queue', 'chunker.queue', 'transcriber.queue', 'assembler.queue', 'cleaner.queue'):
    open(os.path.join(DATA_DIR, q), 'a').close()

# ─── Load settings ─────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, '..', '..'))
with open(os.path.join(PROJECT_ROOT, 'appsettings.json'), 'r', encoding='utf-8') as f:
    settings = json.load(f)
API_URL = settings['transcribe']['api_url']

# ─── Flask app + Dashboard + Converter Queue ──────────────────────────────────
app = Flask(__name__)
converter_q = AtomicQueue(os.path.join(DATA_DIR, 'converter.queue'))
dash_app   = init_dashboard(app, api_url=API_URL)

# ─── Template filter: duration formatting ─────────────────────────────────────
@app.template_filter('format_duration')
def format_duration(ms):
    seconds = ms // 1000
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02}:{m:02}:{s:02}"

# ─── Regex for parsing log lines ───────────────────────────────────────────────
LOG_RE = re.compile(
    r'^(?P<date>\d{4}-\d{2}-\d{2})\s+'
    r'(?P<time>\d{2}:\d{2}:\d{2})\s+'
    r'(?P<level>\w+):\s+'
    r'(?P<msg>.*)$'
)

# ─── Helpers ──────────────────────────────────────────────────────────────────
def get_device_and_languages():
    try:
        device = requests.get(f"{API_URL}/device", timeout=2).json().get('device', 'Unknown')
    except:
        device = 'Unknown'
    try:
        langs = requests.get(f"{API_URL}/languages", timeout=2).json().get('languages', [])
    except:
        langs = []
    return device, langs

# ─── Routes ───────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    device, languages = get_device_and_languages()
    return render_template('index.html', device=device, languages=languages)


@app.route('/transcribe', methods=['POST'])
def transcribe():
    """
    Unified endpoint: handles either
     - a dropped/entered YouTube URL (youtube_url in form)
     - one or more uploaded audio files
    Returns JSON: {'status':'queued', 'items':[...]}
    """
    queued = []

    # ─── Parse optional segments JSON (works for both modes) ───────────────────
    try:
        seg_list = json.loads(request.form.get('segments', '[]'))
    except ValueError:
        seg_list = []

    # ─── YouTube mode ─────────────────────────────────────────────────────────
    yt_url = request.form.get('youtube_url', '').strip()
    if yt_url:
        meta_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True
        }
        # 1) Fetch metadata (playlist or single)
        try:
            with YoutubeDL({**meta_opts, 'download': False}) as ydl:
                info = ydl.extract_info(yt_url, download=False)
        except Exception as e:
            return jsonify({'error': f'yt-dlp metadata failed: {e}'}), 400

        entries = info.get('entries') if info.get('_type') == 'playlist' else [info]
        for entry in filter(None, entries):
            video_url  = entry.get('webpage_url')
            title      = entry.get('title') or entry.get('id')
            safe_title = secure_filename(title)
            ts         = datetime.now(timezone.utc).strftime('%Y_%m_%d__%H_%M_%S')
            lang       = request.form.get('lang_key') or 'unknown'
            subfolder  = f"{ts}_{lang}_{safe_title}"
            subpath    = os.path.join(DATA_DIR, subfolder)
            os.makedirs(subpath, exist_ok=True)

            # 2) Download audio
            dl_opts = {
                **meta_opts,
                'outtmpl': os.path.join(subpath, f"{safe_title}.%(ext)s")
            }
            try:
                with YoutubeDL(dl_opts) as ydl2:
                    downloaded = ydl2.extract_info(video_url, download=True)
                    filename   = ydl2.prepare_filename(downloaded)
            except Exception as e:
                app.logger.warning(f"Skipping {video_url} due to download error: {e}")
                continue

            # 3) Create request.json + enqueue, with one blank segment if none given
            create_transcription_request(
                subpath,
                os.path.basename(filename),
                lang,
                seg_list if seg_list else [{'start': '', 'end': ''}]
            )
            converter_q.enqueue(subfolder)
            queued.append({'folder': subfolder, 'title': title})

        return jsonify({'status': 'queued', 'items': queued})

    # ─── File‐upload mode ───────────────────────────────────────────────────────
    files = request.files.getlist('audio')
    if not files:
        return jsonify({'error': 'No file(s) uploaded'}), 400

    lang = request.form.get('lang_key') or 'unknown'
    for audio in files:
        filename = secure_filename(audio.filename)
        basename, _ = os.path.splitext(filename)
        ts = datetime.now(timezone.utc).strftime('%Y_%m_%d__%H_%M_%S')
        subfolder = f"{ts}_{lang}_{basename}"
        subpath   = os.path.join(DATA_DIR, subfolder)
        os.makedirs(subpath, exist_ok=True)

        # Save the incoming file
        audio.save(os.path.join(subpath, filename))

        # Create request.json + enqueue, with one blank segment if none given
        create_transcription_request(
            subpath,
            filename,
            lang,
            seg_list if seg_list else [{'start': '', 'end': ''}]
        )
        converter_q.enqueue(subfolder)
        queued.append({'folder': subfolder, 'filename': filename})

    return jsonify({'status': 'queued', 'items': queued})


@app.route('/files')
def files_index():
    device, _ = get_device_and_languages()
    batches = []
    for name in sorted(os.listdir(DATA_DIR), reverse=True):
        sub = os.path.join(DATA_DIR, name)
        rq  = os.path.join(sub, 'request.json')
        if not (os.path.isdir(sub) and os.path.exists(rq)):
            continue
        info = json.load(open(rq, 'r', encoding='utf-8'))
        info['folder']      = name
        info['sent_time_dt']= datetime.fromisoformat(info['sent_time'])
        info['completed']   = all(info.get('tasks', {}).values())
        info['segments']    = len([f for f in os.listdir(sub) if f.startswith('segment_')])
        batches.append(info)
    return render_template('files.html', batches=batches, device=device)


@app.route('/files/preview')
def preview_file():
    raw = urllib.parse.unquote(request.args.get('path', ''))
    safe = pathlib.Path(DATA_DIR) / pathlib.Path(raw)
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
    if full.name.endswith('chunks_mapping.json'):
        return preview_chunks_mapping(full)
    if full.name.endswith('text_mappings.json'):
        return preview_text_mappings(full)
    if ext == '.srt':
        return preview_srt(full)
    if ext == '.log':
        return preview_log(full)
    return Markup(f"<pre>{full.read_text('utf-8')}</pre>")


# ─── Preview helpers ─────────────────────────────────────────────────────────
def preview_request(path):
    data = json.load(open(path, 'r', encoding='utf-8'))
    html = '<ul class="batch-meta">'
    html += f"<li>Audio Filename: {data.get('audio_filename')}</li>"
    html += f"<li>Language: {data.get('lang_key')}</li>"
    html += f"<li>Sent Time: {data.get('sent_time')}</li>"
    html += '</ul><table class="batch-table"><tr><th>Stage</th><th>Status</th><th>Timestamp</th></tr>'
    for key, label in {
        'converterCompleted': 'Conversion',
        'chunkerCompleted':   'Chunking',
        'transcriberCompleted':'Transcription',
        'assemblerCompleted':  'Assembling',
        'cleanerCompleted':    'Cleaning'
    }.items():
        ts    = data.get('tasks', {}).get(key)
        emoji = '✅' if ts else '⌛'
        disp  = ts or 'Pending'
        html += f"<tr><td>{label}</td><td>{emoji}</td><td>{disp}</td></tr>"
    html += '</table>'
    return Markup(html)

def preview_chunks_mapping(path):
    chunks = json.load(open(path, 'r', encoding='utf-8'))
    rows   = chunks if isinstance(chunks, list) else chunks.get('chunks', [])
    # Attempt to merge text_mapping.json
    tm_path = path.parent / 'text_mapping.json'
    text_map = {}
    if tm_path.exists():
        tms = json.load(open(tm_path, 'r', encoding='utf-8'))
        for m in (tms if isinstance(tms, list) else tms.get('mappings', [])):
            key = m.get('audio_file','').replace('\\','/')
            text_map[key] = m.get('text_file','')
    html = '<table class="mapping-table"><tr><th>Start</th><th>End</th><th>Chunk File</th><th>Text File</th></tr>'
    for c in rows:
        s = c.get('start_ms') if c.get('start_ms') is not None else c.get('start')
        e = c.get('end_ms')   if c.get('end_ms')   is not None else c.get('end')
        start_fmt = format_duration(s) if s is not None else ''
        end_fmt   = format_duration(e) if e is not None else ''
        cf = c.get('chunk_file','')
        tf = text_map.get(cf.replace('\\','/'), '')
        html += (
            '<tr>'
            f'<td>{start_fmt}</td>'
            f'<td>{end_fmt}</td>'
            f'<td>{Markup.escape(cf)}</td>'
            f'<td>{Markup.escape(tf)}</td>'
            '</tr>'
        )
    html += '</table>'
    return Markup(html)

def preview_text_mappings(path):
    mappings = json.load(open(path, 'r', encoding='utf-8'))
    rows     = mappings if isinstance(mappings, list) else mappings.get('mappings', [])
    html = '<table class="mapping-table"><tr><th>Audio File</th><th>Text File</th></tr>'
    for m in rows:
        af = m.get('audio_file','')
        tf = m.get('text_file','')
        html += (
            '<tr>'
            f'<td>{Markup.escape(af)}</td>'
            f'<td>{Markup.escape(tf)}</td>'
            '</tr>'
        )
    html += '</table>'
    return Markup(html)

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
            end   = raw_end.strip().split(',')[0]
            content = ' '.join(lines[2:]).strip()
            html += (
                '<tr>'
                f'<td>{idx}</td>'
                f'<td>{start}</td>'
                f'<td>{end}</td>'
                f'<td>{Markup.escape(content)}</td>'
                '</tr>'
            )
    html += '</table>'
    return Markup(html)

def preview_log(path):
    lines = path.read_text('utf-8').splitlines()
    html = '<table class="mapping-table"><tr><th>Date</th><th>Time</th><th>Level</th><th>Message</th></tr>'
    for line in lines:
        m = LOG_RE.match(line)
        if m:
            html += (
                '<tr>'
                f'<td>{m.group("date")}</td>'
                f'<td>{m.group("time")}</td>'
                f'<td>{m.group("level")}</td>'
                f'<td>{Markup.escape(m.group("msg"))}</td>'
                '</tr>'
            )
        else:
            html += f'<tr><td colspan=4>{Markup.escape(line)}</td></tr>'
    html += '</table>'
    return Markup(html)

# ─── Download endpoint ────────────────────────────────────────────────────────
@app.route('/download/<path:subpath>')
def download_file(subpath):
    safe = pathlib.Path(DATA_DIR) / pathlib.Path(subpath)
    try:
        safe = safe.resolve().relative_to(DATA_DIR)
    except Exception:
        abort(404)
    full = pathlib.Path(DATA_DIR) / safe

    # Only allow download once all tasks are complete
    req = json.load(open(full.parent / 'request.json', 'r', encoding='utf-8'))
    if not all(req.get('tasks', {}).values()):
        abort(403)

    if not full.is_file():
        abort(404)

    return send_file(str(full), as_attachment=True)

# ─── Run server ──────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(debug=True, port=6001)
