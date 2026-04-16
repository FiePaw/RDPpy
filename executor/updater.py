#!/usr/bin/env python3
"""
RDPpy Updater with GitHub Release Download
- Updates client.exe from GitHub releases
- Launches & monitors watchdog.exe
- Uses process isolation similar to watchdog mechanism
"""

import hashlib
import os
import sys
import tempfile
import time
import logging
import urllib.request
import urllib.error
import subprocess
from datetime import datetime
from typing import Optional, Tuple

# -------- CONFIGURATION --------
REMOTE_URL = "https://github.com/FiePaw/RDPpy/releases/latest/download/client.exe"
CLIENT_FILENAME = "client.exe"
WATCHDOG_FILENAME = "watchdog.exe"
NETWORK_TIMEOUT = 30
DOWNLOAD_RETRIES = 3
RETRY_DELAY = 3
# --------------------------------

# Get base directory (works for both script and exe)
if getattr(sys, 'frozen', False):
    # Running as compiled exe
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Running as script
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Setup logging
log_dir = os.path.join(BASE_DIR, "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "updater.log")

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file)
    ],
    datefmt='%A:%H:%M:%S'
)
logger = logging.getLogger(__name__)


def get_formatted_time():
    """Return formatted time as 'DayName:HH:MM:SS'"""
    now = datetime.now()
    day_name = now.strftime('%A')
    time_str = now.strftime('%H:%M:%S')
    return f"{day_name}:{time_str}"


def sha256_of_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def sha256_of_file(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            h = hashlib.sha256()
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
            return h.hexdigest()
    except FileNotFoundError:
        return None
    except Exception:
        return None


def fetch_remote_bytes(url: str, timeout: int) -> bytes:
    """Fetch a URL and return bytes. Raises urllib.error.URLError on failure."""
    req = urllib.request.Request(url, headers={"User-Agent": "RDPpy-Updater/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def download_with_retry(url: str, timeout: int, retries: int, retry_delay: int) -> Optional[bytes]:
    """
    Try downloading from URL with retries.
    Returns data or None if all failed.
    """
    logger.info(f"Downloading from: {url}")
    
    for attempt in range(1, retries + 1):
        try:
            logger.info(f"Attempt {attempt}/{retries}...")
            data = fetch_remote_bytes(url, timeout)
            logger.info(f"Download successful ({len(data)} bytes)")
            return data
        except urllib.error.HTTPError as e:
            logger.warning(f"HTTP Error {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            logger.warning(f"Network error: {e.reason}")
        except Exception as e:
            logger.warning(f"Unexpected error: {e}")
        
        if attempt < retries:
            logger.info(f"Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)
    
    logger.error("All download attempts failed.")
    return None


def atomic_replace_file(target_path: str, data: bytes) -> bool:
    """Write data to a temporary file in same dir then atomically replace target_path."""
    dirpath = os.path.dirname(os.path.abspath(target_path)) or "."
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=".updater_tmp_", dir=dirpath)
        try:
            with os.fdopen(fd, "wb") as tmpf:
                tmpf.write(data)
            os.replace(tmp_path, target_path)
            return True
        except Exception as e:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            logger.error(f"Failed to replace file: {e}")
            return False
    except Exception as e:
        logger.error(f"Failed to create temp file: {e}")
        return False


def launch_watchdog(watchdog_path: str) -> subprocess.Popen:
    """
    Launch watchdog.exe using isolated process
    Returns Popen object with tracking.
    """
    logger.info(f"Launching watchdog.exe: {watchdog_path}")
    try:
        if os.name == "nt":
            # Windows: CREATE_NEW_PROCESS_GROUP for isolation
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            p = subprocess.Popen(
                [watchdog_path],
                creationflags=creationflags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL
            )
        else:
            # Linux: start_new_session for isolation
            p = subprocess.Popen(
                [watchdog_path],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL
            )
        logger.info(f"watchdog.exe started (PID: {p.pid})")
        return p
    except Exception as e:
        logger.error(f"Failed to launch watchdog.exe: {e}")
        raise


def main():
    client_path = os.path.join(BASE_DIR, CLIENT_FILENAME)
    watchdog_path = os.path.join(BASE_DIR, WATCHDOG_FILENAME)
    
    # Log startup
    logger.info("=" * 60)
    logger.info("Starting RDPpy GitHub Release Updater")
    logger.info("=" * 60)
    logger.info(f"Base directory: {BASE_DIR}")
    logger.info(f"Release URL: {REMOTE_URL}")
    logger.info(f"Client path: {client_path}")
    logger.info(f"Watchdog path: {watchdog_path}")
    
    # Check local client hash
    local_hash = sha256_of_file(client_path)
    if local_hash:
        logger.info(f"Local client hash: {local_hash}")
    else:
        logger.info("Local client not found or unreadable (will download)")
    
    # Download from GitHub release
    remote_bytes = download_with_retry(REMOTE_URL, NETWORK_TIMEOUT, DOWNLOAD_RETRIES, RETRY_DELAY)
    
    # Handle download failure
    if remote_bytes is None:
        logger.error("Could not fetch remote file from GitHub release.")
        logger.warning("Will try to launch watchdog with existing client...")
        if os.path.exists(watchdog_path):
            try:
                launch_watchdog(watchdog_path)
                return
            except Exception:
                logger.error("Launch watchdog failed. Exiting.")
        else:
            logger.error("No watchdog.exe available. Exiting.")
        return
    
    # Handle successful download
    remote_hash = sha256_of_bytes(remote_bytes)
    logger.info(f"Remote client hash: {remote_hash}")
    
    # Check if update needed
    if local_hash == remote_hash and os.path.exists(client_path):
        logger.info("No update needed. Client is up to date.")
    else:
        # Update detected
        logger.info("Update detected (hash mismatch or missing file).")
        logger.info("Updating client...")
        ok = atomic_replace_file(client_path, remote_bytes)
        if not ok:
            logger.error("Update failed (could not write file). Aborting launch.")
            return
        
        logger.info("Update applied successfully.")
        try:
            if os.name != "nt":
                os.chmod(client_path, 0o755)
        except Exception:
            pass
    
    # Launch watchdog
    logger.info("Launching watchdog to monitor client...")
    try:
        launch_watchdog(watchdog_path)
        logger.info("Watchdog launched successfully. Exiting updater...")
    except Exception:
        logger.error("Failed to launch watchdog. Exiting.")


if __name__ == "__main__":
    main()
