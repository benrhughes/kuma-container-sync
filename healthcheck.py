import os
import sys
import time

PATH = "/tmp/last_sync.ok"

try:
    mtime = os.path.getmtime(PATH)
except FileNotFoundError:
    sys.exit(1)

now = time.time()
sync_interval = int(os.getenv("SYNC_INTERVAL", "300"))
limit = sync_interval * 2 + 60

if now - mtime > limit:
    sys.exit(1)

sys.exit(0)
