import os
import logging
import threading
import time
from pathlib import Path

APP_NAME = "DJE Finder TJRR"
APP_VERSION = "1.0.0"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

class TokenBucket:
    def __init__(self, rate_limit_mb):
        self.rate = rate_limit_mb * 1024 * 1024 if rate_limit_mb > 0 else float('inf')
        self.capacity = max(self.rate, 1024 * 128) if rate_limit_mb > 0 else 1024 * 1024 * 100
        self.tokens = self.capacity
        self.last_update = time.time()
        self.lock = threading.Lock()

    def consume(self, amount):
        if self.rate == float('inf'):
            return
        
        while True:
            with self.lock:
                now = time.time()
                elapsed = now - self.last_update
                self.tokens = min(self.capacity, self.tokens + (elapsed * self.rate))
                self.last_update = now
                
                if self.tokens >= amount:
                    self.tokens -= amount
                    return
            time.sleep(0.05)

class Config:
    BASE_DIR = Path(os.getenv("DJE_FINDER_DATA_DIR", Path.home() / "Documents" / "PDF-Dje"))
    INDEX_FILE = BASE_DIR / "indice.json"
    STATE_FILE = BASE_DIR / "estado.json"
    DB_FILE = BASE_DIR / "dje_finder.db"
    START_DATE = os.getenv("DJE_FINDER_START_DATE", "20030103")
    BASE_URL = os.getenv(
        "DJE_FINDER_BASE_URL",
        "https://diario.tjrr.jus.br/dpj/dpj-{}.pdf",
    )
    REQUEST_TIMEOUT = (10, 60)
    USER_AGENT = f"{APP_NAME}/{APP_VERSION}"
    BACKUP_GAP_DAYS = 31
    LOCAL_SCAN_WORKERS = min(32, max(4, (os.cpu_count() or 4) * 2))

thread_local = threading.local()
