import os
import time
import json
import logging
import requests
from datetime import datetime
from logging import LoggerAdapter

from utils.log_utils import setup_logger
from utils.atomic_queue import AtomicQueue
from utils.request_utils import load_request, update_task_timestamp

# ── Configuration ────────────────────────────────────────────────────────────
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DATA_DIR      = os.path.join(BASE_DIR, 'data')
POLL_INTERVAL = 10  # seconds between scans

# Load external API URL
PROJECT_ROOT  = os.path.abspath(os.path.join(BASE_DIR, '..', '..'))
SETTINGS_PATH = os.path.join(PROJECT_ROOT, 'appsettings.json')
with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
    settings = json.load(f)
API_URL       = settings['transcribe']['api_url']

# Queue setup
SCRIPT_NAME      = os.path.splitext(os.path.basename(__file__))[0]  # "transcriber"
QUEUE_PATH       = os.path.join(DATA_DIR, f"{SCRIPT_NAME}.queue")
ASSEMBLER_QUEUE  = AtomicQueue(os.path.join(DATA_DIR, 'assembler.queue'))

# Ensure queue files exist
open(QUEUE_PATH, 'a').close()
open(ASSEMBLER_QUEUE.path, 'a').close()

queue       = AtomicQueue(QUEUE_PATH)
root_logger = setup_logger(
    f"{SCRIPT_NAME}_root",
    os.path.join(DATA_DIR, f"{SCRIPT_NAME}.log"),
    level=logging.INFO
)


def process_folder(batch_name: str):
    subfolder   = os.path.join(DATA_DIR, batch_name)
    # Per-batch logger
    batch_log   = os.path.join(subfolder, f"{batch_name}.log")
    batch_logger= setup_logger(batch_name, batch_log, level=logging.DEBUG)
    adapter     = LoggerAdapter(batch_logger, {'batch': batch_name, 'seg': 0, 'chunk': 0})

    root_logger.info("Processing transcription batch: %s", batch_name)
    adapter.debug("=== Transcriber log initialized ===")
    adapter.info("Starting transcription processing")

    data = load_request(subfolder)
    lang = data.get('lang_key', 'en')

    mapping = []
    # Iterate over each segment directory
    for entry in sorted(os.listdir(subfolder)):
        if not entry.startswith('segment_'):
            continue
        seg_idx       = int(entry.split('_')[1])
        adapter.extra['seg'] = seg_idx
        adapter.extra['chunk'] = 0
        adapter.info("Processing segment %d", seg_idx)

        seg_dir       = os.path.join(subfolder, entry)
        audio_dir     = os.path.join(seg_dir, 'audio_chunks')
        text_dir      = os.path.join(seg_dir, 'text_chunks')
        os.makedirs(text_dir, exist_ok=True)

        for fname in sorted(os.listdir(audio_dir)):
            if not fname.lower().endswith('.wav'):
                continue
            chunk_id = int(os.path.splitext(fname)[0].split('_')[-1])
            adapter.extra['chunk'] = chunk_id
            chunk_path = os.path.join(audio_dir, fname)

            adapter.info("Sending chunk for transcription: %s", fname)
            try:
                with open(chunk_path, 'rb') as af:
                    adapter.debug("POST → %s/transcribe", API_URL)
                    resp = requests.post(
                        f"{API_URL}/transcribe",
                        files={'audio': af},
                        data={'lang_key': lang}
                    )
                    resp.raise_for_status()
                    result = resp.json()
                    text = result.get('transcription', '')
                adapter.info("Received transcription for %s (%d chars)", fname, len(text))
            except Exception as e:
                adapter.error("Failed to transcribe %s: %s", fname, e, exc_info=True)
                continue

            # Write out .txt
            txt_fname = os.path.splitext(fname)[0] + '.txt'
            txt_path  = os.path.join(text_dir, txt_fname)
            with open(txt_path, 'w', encoding='utf-8') as tf:
                tf.write(text)
            adapter.info("Wrote transcription to %s", txt_path)

            mapping.append({
                'audio_file': os.path.relpath(chunk_path, subfolder),
                'text_file' : os.path.relpath(txt_path, subfolder)
            })

    # Write a text_mapping.json for each segment
    for entry in sorted(os.listdir(subfolder)):
        if not entry.startswith('segment_'):
            continue
        seg_dir  = os.path.join(subfolder, entry)
        map_path = os.path.join(seg_dir, 'text_mapping.json')
        with open(map_path, 'w', encoding='utf-8') as mf:
            json.dump(mapping, mf, indent=2, ensure_ascii=False)
        adapter.info("Wrote text_mapping.json for %s", seg_dir)

    # Stamp completion and hand off
    update_task_timestamp(subfolder, 'transcriberCompleted')
    ASSEMBLER_QUEUE.enqueue(batch_name)
    adapter.info("Stamped transcriberCompleted and enqueued for assembling")


def scan_and_process():
    batches = queue.pop_all()
    if not batches:
        root_logger.debug("No batches in transcriber.queue")
        return

    failures = []
    for batch in batches:
        try:
            process_folder(batch)
        except Exception as e:
            root_logger.error("Processing failed for %s: %s", batch, e, exc_info=True)
            failures.append(batch)

    if failures:
        queue.replace(failures)


def main():
    root_logger.info(f"Transcriber starting, polling every {POLL_INTERVAL}s")
    while True:
        scan_and_process()
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
