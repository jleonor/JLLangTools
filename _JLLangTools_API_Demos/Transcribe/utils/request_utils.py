import os
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
from datetime import datetime
from filelock import FileLock

# Keys for lifecycle task timestamps
TASK_KEYS = [
    'converterCompleted',
    'chunkerCompleted',
    'transcriberCompleted',
    'assemblerCompleted',
    'cleanerCompleted',
]

def load_request(subfolder: str) -> dict:
    """
    Load the batch’s request.json under a lock.
    """
    path = os.path.join(subfolder, 'request.json')
    lock = FileLock(path + '.lock')
    with lock:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

def save_request(subfolder: str, data: dict) -> None:
    """
    Overwrite request.json (keeping indentation) under lock.
    """
    path = os.path.join(subfolder, 'request.json')
    lock = FileLock(path + '.lock')
    with lock:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

def update_task_timestamp(subfolder: str,
                          task_name: str,
                          timestamp: str | None = None) -> None:
    """
    Set data['tasks'][task_name] = timestamp (ISO), default now().
    """
    if timestamp is None:
        timestamp = datetime.utcnow().isoformat()
    data = load_request(subfolder)
    tasks = data.setdefault('tasks', {})
    tasks[task_name] = timestamp
    save_request(subfolder, data)

def create_transcription_request(subfolder: str,
                                 audio_filename: str,
                                 lang_key: str,
                                 segments: list[dict]) -> None:
    """
    Initialize request.json for an audio transcription job (file or YouTube).
    Sets sent_time to now and resets all task timestamps to None.
    """
    now_iso = datetime.utcnow().isoformat()
    payload = {
        'audio_filename': audio_filename,
        'lang_key':       lang_key,
        'segments':       segments,
        'sent_time':      now_iso,
        'tasks':          {key: None for key in TASK_KEYS}
    }
    save_request(subfolder, payload)
