"""Dev-only clean state: COPILOT_FRESH=1 deletes the event database and the uploaded-PDF folder when the backend starts,
then recreates them (the database is recreated by store.py, the folder here). OFF by default; nothing else sets it.

The same switch gives the process a boot id, returned by GET /config, so the frontend can tell that the backend it stored
a reviewer id and a paper id for is gone and forget them. Without the switch there is no boot id (None): an ordinary
restart keeps everything, as before.
"""
import os
import shutil
import uuid


def new_boot_id():
    return uuid.uuid4().hex


BOOT_ID = None   # set by apply() when the switch is on


def enabled(env=None):
    return (os.environ if env is None else env).get("COPILOT_FRESH") == "1"


def _unsafe(data_dir):
    """A folder that must never be wiped: empty, the working directory itself, a filesystem root, the home folder."""
    if not data_dir.strip():
        return True
    p = os.path.realpath(data_dir)
    return p in (os.path.realpath(os.getcwd()), os.path.realpath(os.path.expanduser("~"))) or p == os.path.dirname(p)


def apply(env=None):
    """Wipe and recreate the database and the data folder if the switch is on. Returns whether it did."""
    global BOOT_ID
    env = os.environ if env is None else env
    if not enabled(env):
        return False
    db, data = env.get("COPILOT_DB", "copilot.db"), env.get("COPILOT_DATA_DIR", "data")
    if _unsafe(data):
        raise RuntimeError(f"COPILOT_FRESH=1 refuses to wipe {data!r}: point COPILOT_DATA_DIR at its own folder")
    for path in (db, db + "-journal", db + "-wal", db + "-shm"):
        if os.path.exists(path):
            os.remove(path)
    shutil.rmtree(data, ignore_errors=True)
    os.makedirs(data, exist_ok=True)
    BOOT_ID = new_boot_id()
    return True
