import os
import time
import json
import random
import string
import logging
from datetime import datetime, timedelta
from logging import LoggerAdapter

import pandas as pd
from pydub import AudioSegment
from pydub.silence import detect_silence

from utils.log_utils import setup_logger
from utils.atomic_queue import AtomicQueue
from utils.request_utils import load_request, update_task_timestamp

# ── Configuration ────────────────────────────────────────────────────────────
BASE_DIR          = os.path.dirname(os.path.abspath(__file__))
DATA_DIR          = os.path.join(BASE_DIR, 'data')
POLL_INTERVAL     = 10  # seconds between scans

SCRIPT_NAME       = os.path.splitext(os.path.basename(__file__))[0]  # "chunker"
QUEUE_PATH        = os.path.join(DATA_DIR, f"{SCRIPT_NAME}.queue")
NEXT_QUEUE_PATH   = os.path.join(DATA_DIR, 'transcriber.queue')

# Ensure queue files exist
enqueue_paths = [QUEUE_PATH, NEXT_QUEUE_PATH]
for path in enqueue_paths:
    open(path, 'a').close()

queue       = AtomicQueue(QUEUE_PATH)
next_queue  = AtomicQueue(NEXT_QUEUE_PATH)
root_logger = setup_logger(f"{SCRIPT_NAME}_root", os.path.join(DATA_DIR, f"{SCRIPT_NAME}.log"), level=logging.INFO)

# Chunking parameters
MAX_SEGMENT_LENGTH = 10_000    # 30 seconds in ms
INITIAL_SILENCE    = 500       # 0.9 seconds
SILENCE_THRESH     = -40       # dBFS threshold
MIN_SILENCE_LIMIT  = 100       # 0.1 seconds
TIME_FORMAT        = '%H:%M:%S'

def seconds_to_hms(seconds: float, base_time: str) -> str:
    base = datetime.strptime(base_time, TIME_FORMAT)
    return (base + timedelta(seconds=seconds)).strftime(TIME_FORMAT)


def timestamps_to_ms(timestamp: str) -> int:
    h, m, s = map(int, timestamp.split(':'))
    return (h * 3600 + m * 60 + s) * 1000


def find_last_silence(
    chunk: AudioSegment,
    min_silence_len=INITIAL_SILENCE,
    silence_thresh=SILENCE_THRESH,
    min_limit=MIN_SILENCE_LIMIT,
    adapter: LoggerAdapter = None
) -> int:
    adapter.debug(f"Starting silence search: start_len={min_silence_len}ms, thresh={silence_thresh}dBFS")
    while min_silence_len >= min_limit:
        adapter.debug(f"Trying silence_len={min_silence_len}ms")
        silences = detect_silence(chunk, min_silence_len=min_silence_len, silence_thresh=silence_thresh)
        if silences:
            point = silences[-1][1]
            adapter.info(f"Silence found at {seconds_to_hms(point/1000, '00:00:00')} → cutting here")
            return point
        min_silence_len -= 100
    adapter.warning("No silence found → using full segment")
    return 0


def split_audio_by_silence(sound: AudioSegment, adapter: LoggerAdapter):
    adapter.info(f"Splitting audio of length {len(sound)} ms")
    chunks, times = [], []
    start = 0
    total_len = len(sound)

    while start < total_len:
        end = min(start + MAX_SEGMENT_LENGTH, total_len)
        segment = sound[start:end]
        silence_pos = find_last_silence(segment, adapter=adapter)

        if silence_pos == 0 or end == total_len:
            adapter.debug("No intermediate silence or reached end → full chunk used")
            silence_pos = len(segment)

        actual_end = start + silence_pos
        adapter.info(
            f"Creating chunk from {seconds_to_hms(start/1000, adapter.extra.get('video_start', '00:00:00'))}"
            f" to {seconds_to_hms(actual_end/1000, adapter.extra.get('video_start', '00:00:00'))}"
        )
        chunks.append(sound[start:actual_end])
        times.append((start, actual_end))
        start = actual_end

    adapter.info(f"Total chunks created: {len(chunks)}")
    return chunks, times


def run_chunking_for_sound(sound: AudioSegment, subfolder: str, logger: logging.Logger, video_start: str, segment_tag: int) -> pd.DataFrame:
    batch_name = os.path.basename(subfolder)
    adapter = LoggerAdapter(logger, {'batch': batch_name, 'seg': segment_tag, 'chunk': 0, 'video_start': video_start})
    batch_id = ''.join(random.choices(string.ascii_letters + string.digits, k=12))

    adapter.info(f"Batch {batch_id}: starting chunking for segment {segment_tag}")
    chunks, times = split_audio_by_silence(sound, adapter)

    # Build DataFrame
    rows = []
    current_time = video_start
    for start_ms, end_ms in times:
        real_start = start_ms / 1000.0
        real_end   = end_ms / 1000.0
        video_end  = seconds_to_hms(real_end - real_start, current_time)
        rows.append({
            'Batch ID': batch_id,
            'Segment': segment_tag,
            'Real Start (s)': real_start,
            'Real End (s)':   real_end,
            'Video Time Start': current_time,
            'Video Time End':   video_end
        })
        current_time = video_end

    df = pd.DataFrame(rows)

    # Export chunks
    segment_dir = os.path.join(subfolder, f'segment_{segment_tag}')
    audio_dir   = os.path.join(segment_dir, 'audio_chunks')
    os.makedirs(audio_dir, exist_ok=True)
    for i, chunk in enumerate(chunks, start=1):
        adapter.extra['chunk'] = i
        out_path = os.path.join(audio_dir, f'chunk_{i}.wav')
        chunk.export(out_path, format='wav')
        adapter.info(
            f"Exported chunk_{i}.wav ["
            f"{seconds_to_hms(times[i-1][0]/1000, video_start)}–{seconds_to_hms(times[i-1][1]/1000, video_start)}]"
        )

    # Write mapping
    mapping = [
        {'chunk_file': f'segment_{segment_tag}/audio_chunks/chunk_{i}.wav', 'start_ms': s, 'end_ms': e}
        for i, (s, e) in enumerate(times, start=1)
    ]
    map_path = os.path.join(segment_dir, 'chunks_mapping.json')
    with open(map_path, 'w', encoding='utf-8') as mf:
        json.dump(mapping, mf, indent=2)
    adapter.info(f"Wrote chunks_mapping.json for segment {segment_tag} with {len(mapping)} entries")

    return df


def process_wav(wav_path: str):
    subfolder  = os.path.dirname(wav_path)
    batch_name = os.path.basename(subfolder)
    batch_log  = os.path.join(subfolder, f"{batch_name}.log")
    logger     = setup_logger(batch_name, batch_log, level=logging.DEBUG)
    adapter    = LoggerAdapter(logger, {'batch': batch_name, 'seg': 0, 'chunk': 0, 'video_start': '00:00:00'})
    adapter.info(f"Processing new batch: {batch_name}")

    data     = load_request(subfolder)
    segments = data.get('segments', [])
    sound    = AudioSegment.from_file(wav_path, format='wav')

    if segments:
        for idx, seg in enumerate(segments, start=1):
            start_ts = seg.get('start', '').strip() or '00:00:00'
            end_ts   = seg.get('end', '').strip() or None
            adapter.extra['seg'] = idx
            adapter.info(f"User segment {idx}: {start_ts} to {end_ts or 'end'}")
            start_ms = timestamps_to_ms(start_ts)
            end_ms   = timestamps_to_ms(end_ts) if end_ts else len(sound)
            segment_sound = sound[start_ms:end_ms]
            run_chunking_for_sound(segment_sound, subfolder, logger, start_ts, idx)
    else:
        run_chunking_for_sound(sound, subfolder, logger, '00:00:00', 0)

    update_task_timestamp(subfolder, 'chunkerCompleted')
    next_queue.enqueue(batch_name)
    adapter.info("Stamped chunkerCompleted and enqueued to transcriber")


def scan_and_process():
    batches = queue.pop_all()
    if not batches:
        root_logger.debug("No batches in chunker.queue")
        return

    failures = []
    for batch in batches:
        try:
            data     = load_request(os.path.join(DATA_DIR, batch))
            original_file = data['audio_filename']
            wav_file = os.path.splitext(original_file)[0] + '.wav'
            wav_path = os.path.join(DATA_DIR, batch, wav_file)
            process_wav(wav_path)
        except Exception as e:
            root_logger.error(f"Error chunking {batch}: {e}", exc_info=True)
            failures.append(batch)

    if failures:
        queue.replace(failures)


def main():
    root_logger.info(f"Chunker starting, polling every {POLL_INTERVAL}s")
    while True:
        scan_and_process()
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
