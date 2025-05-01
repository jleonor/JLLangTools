import os
import glob
import json
import pandas as pd
import logging

# Configure logging for debug
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def process_request(request_path):
    """
    Process a single request.json and collect per-segment metrics.
    """
    logging.info(f"Loading request metadata from: {request_path}")
    try:
        with open(request_path, 'r', encoding='utf-8') as f:
            request = json.load(f)
    except Exception as e:
        logging.error(f"Failed to load {request_path}: {e}")
        return []

    # Normalize request-level fields
    file_name = request.get('audio_filename') or request.get('file')
    lang_key = request.get('lang_key') or request.get('langKey')
    sent_time = request.get('sent_time') or request.get('sentTime')
    tasks_dict = request.get('tasks') or {}

    base_dir = os.path.dirname(request_path)
    # Search exactly one level deeper for chunks_mapping.json files (segments live in subfolders)
    mapping_pattern = os.path.join(base_dir, '*', 'chunks_mapping.json')
    mapping_files = glob.glob(mapping_pattern)
    logging.info(f"Found {len(mapping_files)} mapping files in subfolders of {base_dir}")

    rows = []
    for mapping_file in mapping_files:
        segment_dir = os.path.dirname(mapping_file)
        segment_name = os.path.basename(segment_dir)

        logging.info(f"Processing segment '{segment_name}' mapping: {mapping_file}")
        try:
            with open(mapping_file, 'r', encoding='utf-8') as mf:
                mapping = json.load(mf)
        except Exception as e:
            logging.warning(f"Error reading mapping {mapping_file}: {e}")
            continue

        # mapping may be a list of chunks or nested under a key
        if isinstance(mapping, list):
            chunks = mapping
        else:
            chunks = mapping.get('chunks') or mapping.get('mappings') or []

        if not chunks:
            logging.warning(f"No chunks found in {mapping_file}")
            continue

        # Extract start/end values (ms)
        starts = []
        ends = []
        for c in chunks:
            # handle different key names
            start = c.get('start_ms') or c.get('start')
            end = c.get('end_ms') or c.get('end')
            if start is None or end is None:
                logging.warning(f"Chunk missing start/end in {mapping_file}: {c}")
                continue
            starts.append(start)
            ends.append(end)

        if not starts or not ends:
            logging.warning(f"No valid start/end pairs in {mapping_file}")
            continue

        # Compute audio length and chunk stats
        audio_length = ends[-1] - starts[0]
        num_chunks = len(starts)
        avg_chunk_length = sum(e - s for s, e in zip(starts, ends)) / num_chunks

        # Find transcript text file one level deeper relative to mapping file
        text_files = glob.glob(os.path.join(segment_dir, '*', '*.txt'))
        text_length = 0
        if text_files:
            try:
                with open(text_files[0], 'r', encoding='utf-8') as tf:
                    text = tf.read()
                text_length = len(text.split())
            except Exception as e:
                logging.warning(f"Could not read text file {text_files[0]}: {e}")

        # Build row starting with request-level fields
        row = {
            'file': file_name,
            'langKey': lang_key,
            'sentTime': sent_time,
            'segment': segment_name,
            'audio_length_ms': audio_length,
            'num_chunks': num_chunks,
            'avg_chunk_length_ms': avg_chunk_length,
            'text_length_words': text_length
        }

        # Include all task completion values (dict of name->timestamp)
        for name, comp_time in tasks_dict.items():
            row[name] = comp_time

        rows.append(row)

    return rows


if __name__ == '__main__':
    # Determine project root (one level above analytics folder)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, '..'))
    logging.info(f"Project root detected at: {project_root}")

    # Locate all request.json files
    pattern = os.path.join(project_root, '**', 'request.json')
    request_files = glob.glob(pattern, recursive=True)
    logging.info(f"Found {len(request_files)} request.json files")

    if not request_files:
        logging.error("No request.json files found. Check your directory structure.")
        exit(1)

    all_rows = []
    for req in request_files:
        all_rows.extend(process_request(req))

    if not all_rows:
        logging.error("No segment data collected. Please verify mapping files and request.json contents.")
        exit(1)

    df = pd.DataFrame(all_rows)
    # Drop any rows containing null/NaN values
    df.dropna(inplace=True)
    out_path = os.path.join(script_dir, 'aggregated_data.json')
    try:
        df.to_json(out_path, orient='records', force_ascii=False, indent=2)
        logging.info(f"Aggregated {len(df)} segment rows into {out_path}")
    except Exception as e:
        logging.error(f"Failed to write JSON to {out_path}: {e}")
        exit(1)
