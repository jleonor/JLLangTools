# utils/request_utils.py

import os
import json
from datetime import datetime
from filelock import FileLock

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
