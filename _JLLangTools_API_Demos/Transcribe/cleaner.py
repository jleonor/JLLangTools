import os
import time
import shutil
import logging
from logging import LoggerAdapter

from utils.log_utils import setup_logger
from utils.atomic_queue import AtomicQueue
from utils.request_utils import update_task_timestamp

# ── Configuration ────────────────────────────────────────────────────────────
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DATA_DIR      = os.path.join(BASE_DIR, 'data')
POLL_INTERVAL = 10  # seconds between scans

SCRIPT_NAME   = os.path.splitext(os.path.basename(__file__))[0]  # "cleaner"
QUEUE_PATH    = os.path.join(DATA_DIR, f"{SCRIPT_NAME}.queue")

# Ensure queue file exists
open(QUEUE_PATH, 'a').close()

# Global system queue & logger
queue       = AtomicQueue(QUEUE_PATH)
root_logger = setup_logger(
    f"{SCRIPT_NAME}_root",
    os.path.join(DATA_DIR, f"{SCRIPT_NAME}.log"),
    level=logging.INFO
)


def process_batch(batch_name: str):
    subfolder     = os.path.join(DATA_DIR, batch_name)
    batch_log     = os.path.join(subfolder, f"{batch_name}.log")
    batch_logger  = setup_logger(batch_name, batch_log, level=logging.DEBUG)
    adapter       = LoggerAdapter(batch_logger, {'batch': batch_name})

    adapter.debug("=== Cleaner log initialized ===")
    adapter.info("Starting cleanup for batch: %s", batch_name)

    removed_count = 0
    # 1) Remove audio_chunks and text_chunks under each segment
    for entry in os.listdir(subfolder):
        seg_dir = os.path.join(subfolder, entry)
        if not os.path.isdir(seg_dir) or not entry.startswith('segment_'):
            continue
        for dname in ('audio_chunks', 'text_chunks'):
            dir_path = os.path.join(seg_dir, dname)
            if os.path.isdir(dir_path):
                try:
                    shutil.rmtree(dir_path)
                    removed_count += 1
                    adapter.info("Deleted directory: %s", dir_path)
                except Exception as e:
                    adapter.error("Failed to delete directory %s: %s", dir_path, e, exc_info=True)

    # 2) Recursively delete any files not ending with .txt, .srt, .json, or .log
    for root_dir, _, files in os.walk(subfolder):
        for fname in files:
            if not fname.lower().endswith(('.txt', '.srt', '.json', '.log')):
                file_path = os.path.join(root_dir, fname)
                try:
                    os.remove(file_path)
                    removed_count += 1
                    adapter.info("Deleted file: %s", file_path)
                except Exception as e:
                    adapter.error("Failed to delete file %s: %s", file_path, e, exc_info=True)

    # 3) Stamp completion
    update_task_timestamp(subfolder, 'cleanerCompleted')
    adapter.info("Cleanup complete: removed %d items; stamped cleanerCompleted", removed_count)
    root_logger.info("Batch '%s' cleaned successfully", batch_name)


def scan_and_process():
    batches = queue.pop_all()
    if not batches:
        root_logger.debug("No batches in cleaner.queue")
        return

    failures = []
    for batch in batches:
        try:
            process_batch(batch)
        except Exception as e:
            root_logger.error("Error cleaning batch %s: %s", batch, e, exc_info=True)
            failures.append(batch)

    if failures:
        queue.replace(failures)


def main():
    root_logger.info(f"Cleaner starting, polling every {POLL_INTERVAL}s")
    while True:
        scan_and_process()
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
