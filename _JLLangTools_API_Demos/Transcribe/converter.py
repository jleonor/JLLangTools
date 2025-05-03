import os
import time
import logging
from logging import LoggerAdapter
from pydub import AudioSegment

from utils.log_utils import setup_logger
from utils.atomic_queue import AtomicQueue
from utils.request_utils import load_request, update_task_timestamp

# ── Configuration ────────────────────────────────────────────────────────────
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DATA_DIR      = os.path.join(BASE_DIR, 'data')
POLL_INTERVAL = 10  # seconds between polls

# Determine this script’s name to derive queue/log filenames
SCRIPT_NAME   = os.path.splitext(os.path.basename(__file__))[0]  # "converter"
QUEUE_PATH    = os.path.join(DATA_DIR, f"{SCRIPT_NAME}.queue")
CHUNKER_QUEUE = AtomicQueue(os.path.join(DATA_DIR, 'chunker.queue'))

# Initialize our queue and root logger
queue       = AtomicQueue(QUEUE_PATH)
LOG_PATH    = os.path.join(DATA_DIR, f"{SCRIPT_NAME}.log")
root_logger = setup_logger(f"{SCRIPT_NAME}_root", LOG_PATH, level=logging.INFO)


def convert_folder(batch_name: str) -> bool:
    """
    Convert the original audio file in `batch_name` subfolder to WAV,
    update request.json, and stamp converterCompleted.
    """
    subfolder = os.path.join(DATA_DIR, batch_name)
    # Attach batch context to logs
    adapter = LoggerAdapter(root_logger, {'batch': batch_name, 'seg': 0, 'chunk': 0})
    adapter.info("Starting conversion")

    try:
        # 1) Load the existing request.json
        data = load_request(subfolder)
        orig = data.get('audio_filename')
        if not orig:
            adapter.warning("audio_filename missing in request.json, skipping conversion")
            raise ValueError("audio_filename missing in request.json")

        # 2) Paths
        orig_path = os.path.join(subfolder, orig)
        if not os.path.exists(orig_path):
            adapter.error("Original file %s not found", orig_path)
            raise FileNotFoundError(f"{orig_path} not found")

        adapter.debug("Loading original audio file: %s", orig_path)

        # 3) Convert to WAV
        base, _  = os.path.splitext(orig)
        wav_name = f"{base}.wav"
        wav_path = os.path.join(subfolder, wav_name)

        adapter.info("Converting to WAV format")
        audio = AudioSegment.from_file(orig_path)
        adapter.debug("AudioSegment loaded, exporting to WAV: %s", wav_path)
        audio.export(wav_path, format='wav')

        # 5) Stamp completion
        update_task_timestamp(subfolder, 'converterCompleted')
        adapter.info("Exported WAV to %s and stamped converterCompleted", wav_path)

        return True

    except Exception as e:
        adapter.error("Conversion failed: %s", e, exc_info=True)
        return False


def scan_and_process():
    """
    Atomically grab all queued batches, process them, re-queue failures.
    """
    batches = queue.pop_all()
    if not batches:
        root_logger.debug("No batches in converter.queue at this time")
        return

    failures = []
    for batch in batches:
        success = convert_folder(batch)
        if success:
            CHUNKER_QUEUE.enqueue(batch)
            root_logger.info("Enqueued batch '%s' for chunking", batch)
        else:
            failures.append(batch)

    if failures:
        queue.replace(failures)


def main():
    root_logger.info(f"{SCRIPT_NAME.capitalize()} starting, polling every {POLL_INTERVAL}s")
    while True:
        scan_and_process()
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
