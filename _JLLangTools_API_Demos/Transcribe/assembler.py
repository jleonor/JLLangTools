import os
import time
import json
import logging
from logging import LoggerAdapter

from utils.log_utils import setup_logger
from utils.atomic_queue import AtomicQueue
from utils.request_utils import load_request, update_task_timestamp

# ── Configuration ────────────────────────────────────────────────────────────
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DATA_DIR      = os.path.join(BASE_DIR, 'data')
POLL_INTERVAL = 10  # seconds between scans

SCRIPT_NAME    = os.path.splitext(os.path.basename(__file__))[0]  # "assembler"
QUEUE_PATH     = os.path.join(DATA_DIR, f"{SCRIPT_NAME}.queue")
CLEANER_QUEUE  = AtomicQueue(os.path.join(DATA_DIR, 'cleaner.queue'))

# Ensure queue files exist
open(QUEUE_PATH, 'a').close()
open(CLEANER_QUEUE.path, 'a').close()

queue       = AtomicQueue(QUEUE_PATH)
root_logger = setup_logger(
    f"{SCRIPT_NAME}_root",
    os.path.join(DATA_DIR, f"{SCRIPT_NAME}.log"),
    level=logging.INFO
)


def format_hms(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_srt_timestamp(ms: int) -> str:
    total_sec, ms_rem = divmod(ms, 1000)
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms_rem:03d}"


def process_folder(batch_name: str):
    subfolder = os.path.join(DATA_DIR, batch_name)
    batch_log = os.path.join(subfolder, f"{batch_name}.log")
    batch_logger = setup_logger(batch_name, batch_log, level=logging.DEBUG)
    adapter = LoggerAdapter(batch_logger, {'batch': batch_name, 'seg': 0})

    root_logger.info("Starting assembly for batch '%s'", batch_name)
    adapter.debug("=== Assembler log initialized ===")

    # Load metadata
    data = load_request(subfolder)
    segments_info = data.get('segments', [])

    # Find and sort segment directories
    seg_dirs = [
        d for d in os.listdir(subfolder)
        if os.path.isdir(os.path.join(subfolder, d)) and d.startswith('segment_')
    ]
    seg_dirs.sort(key=lambda x: int(x.split('_')[1]))
    adapter.info("Found segments: %s", seg_dirs)

    for seg in seg_dirs:
        idx = int(seg.split('_')[1])
        adapter.extra['seg'] = idx
        subseg = os.path.join(subfolder, seg)
        adapter.info("Processing segment %d", idx)

        # Determine base timestamp
        raw_start = ''
        if idx - 1 < len(segments_info):
            raw_start = segments_info[idx - 1].get('start', '').strip()
        start_ts = raw_start or '00:00:00'
        h, m, s = map(int, start_ts.split(':'))
        base_ms = (h * 3600 + m * 60 + s) * 1000
        adapter.info("Base timestamp for segment %d: %s (%d ms)", idx, start_ts, base_ms)

        # Load mappings
        chunks_map_path = os.path.join(subseg, 'chunks_mapping.json')
        text_map_path   = os.path.join(subseg, 'text_mapping.json')
        with open(chunks_map_path, 'r', encoding='utf-8') as cf:
            chunks_map = json.load(cf)
        with open(text_map_path, 'r', encoding='utf-8') as tf:
            text_map = json.load(tf)

        text_lookup = {os.path.normpath(e['audio_file']): e['text_file'] for e in text_map}

        # Prepare output
        out_dir = os.path.join(subseg, 'assembled_result')
        os.makedirs(out_dir, exist_ok=True)

        transcript = []
        srt_entries = []
        counter = 1

        for entry in sorted(chunks_map, key=lambda x: x.get('start_ms', 0)):
            audio_key = os.path.normpath(entry['chunk_file'])
            start_abs = base_ms + entry.get('start_ms', 0)
            end_abs   = base_ms + entry.get('end_ms', 0)

            txt_rel = text_lookup.get(audio_key)
            if not txt_rel:
                adapter.warning("No text mapping for %s, skipping", audio_key)
                continue

            txt_path = os.path.join(subfolder, txt_rel)
            with open(txt_path, 'r', encoding='utf-8') as tf:
                raw_text = tf.read()
                text = raw_text.strip()
            adapter.info("Loaded text %s (%d chars)", os.path.basename(txt_path), len(text))

            time_label = format_hms(start_abs // 1000)
            transcript.append(f"{text}")
            srt_entries.append({
                'idx': counter,
                'start': format_srt_timestamp(start_abs),
                'end': format_srt_timestamp(end_abs),
                'text': text
            })
            adapter.debug("Appended SRT entry %d: %s --> %s", counter, srt_entries[-1]['start'], srt_entries[-1]['end'])
            counter += 1

        # Write transcript .txt
        txt_out = os.path.join(out_dir, f"{batch_name}_{idx}.txt")
        with open(txt_out, 'w', encoding='utf-8') as tf:
            tf.write("\n".join(transcript))
        adapter.info("Wrote assembled transcript (%d lines) to %s", len(transcript), txt_out)

        # Write .srt
        srt_out = os.path.join(out_dir, f"{batch_name}_{idx}.srt")
        with open(srt_out, 'w', encoding='utf-8') as sf:
            for item in srt_entries:
                sf.write(f"{item['idx']}\n")
                sf.write(f"{item['start']} --> {item['end']}\n")
                sf.write(f"{item['text']}\n\n")
        adapter.info("Wrote SRT (%d entries) to %s", len(srt_entries), srt_out)

    # Stamp completion and enqueue cleaning
    update_task_timestamp(subfolder, 'assemblerCompleted')
    CLEANER_QUEUE.enqueue(batch_name)
    root_logger.info("Stamped assemblerCompleted and enqueued batch '%s' for cleaning", batch_name)


def scan_and_process():
    batches = queue.pop_all()
    if not batches:
        root_logger.debug("No batches in assembler.queue")
        return

    failures = []
    for batch in batches:
        try:
            process_folder(batch)
        except Exception as e:
            root_logger.error("Error assembling %s: %s", batch, e, exc_info=True)
            failures.append(batch)

    if failures:
        queue.replace(failures)


def main():
    root_logger.info(f"Assembler starting, polling every {POLL_INTERVAL}s")
    while True:
        scan_and_process()
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
