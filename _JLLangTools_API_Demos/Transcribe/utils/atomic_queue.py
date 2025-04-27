# utils/atomic_queue.py

from filelock import FileLock

class AtomicQueue:
    """
    A simple line-based queue stored in a file.
    enqueue(): append a new item
    pop_all(): atomically read & clear the file
    replace(): atomically overwrite with a given list
    """
    def __init__(self, path: str):
        self.path = path
        self.lock = FileLock(path + '.lock')

    def enqueue(self, item: str) -> None:
        with self.lock:
            with open(self.path, 'a', encoding='utf-8') as f:
                f.write(item.strip() + '\n')

    def pop_all(self) -> list[str]:
        with self.lock:
            try:
                with open(self.path, 'r', encoding='utf-8') as f:
                    lines = [l.strip() for l in f if l.strip()]
            except FileNotFoundError:
                lines = []
            # clear the queue
            with open(self.path, 'w', encoding='utf-8'):
                pass
        return lines

    def replace(self, items: list[str]) -> None:
        with self.lock:
            with open(self.path, 'w', encoding='utf-8') as f:
                for i in items:
                    f.write(i.strip() + '\n')
