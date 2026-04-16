#!/usr/bin/env python3
"""
RDPpy Client Watchdog - Auto-restart mechanism
Monitors client.exe process and restarts if it's terminated
"""

import subprocess
import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path

# -------- CONFIGURATION --------
CLIENT_FILENAME = "client.exe"
WATCH_INTERVAL = 2  # Check every 2 seconds
GRACEFUL_SHUTDOWN_TIMEOUT = 5  # Timeout untuk graceful shutdown
MAX_RESTART_ATTEMPTS = 5  # Max restart attempts dalam 60 detik
RESTART_WINDOW = 60  # Time window untuk mendeteksi restart attempts
# --------------------------------

# Setup logging
log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(log_dir, exist_ok=True)

log_file = os.path.join(log_dir, "watchdog.log")
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def get_base_dir():
    import sys, os
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

class ClientWatchdog:
    def __init__(self, client_filename=CLIENT_FILENAME):
        self.base_dir = get_base_dir()
        self.client_path = os.path.join(self.base_dir, client_filename)
        self.process = None
        self.restart_times = []  # Track restart times untuk backoff
        self.running = True
        self.graceful_shutdown = False
        
    def get_formatted_time(self):
        """Return formatted time as 'DayName:HH:MM:SS'"""
        now = datetime.now()
        day_name = now.strftime('%A')
        time_str = now.strftime('%H:%M:%S')
        return f"{day_name}:{time_str}"
    def check_client_exists(self):
        """Verify client.exe exists"""
        if not os.path.exists(self.client_path):
            logger.error(f"[{self.get_formatted_time()}] client.exe not found at {self.client_path}")
            return False
        return True
    
    def cleanup_restart_history(self):
        """Remove old restart times (older than RESTART_WINDOW)"""
        current_time = time.time()
        self.restart_times = [t for t in self.restart_times if current_time - t < RESTART_WINDOW]
    
    def should_restart(self):
        """Check if restart should be allowed (prevent restart loops)"""
        self.cleanup_restart_history()
        
        if len(self.restart_times) >= MAX_RESTART_ATTEMPTS:
            logger.warning(f"[{self.get_formatted_time()}] Too many restarts ({MAX_RESTART_ATTEMPTS}) in {RESTART_WINDOW}s - backing off")
            return False
        return True
    
    def launch_client(self):
        """Launch client.exe as subprocess"""
        try:
            logger.info(f"[{self.get_formatted_time()}] Launching client.exe...")
            
            if os.name == "nt":  # Windows
                # CREATE_NEW_PROCESS_GROUP = parent process can't directly kill child
                # DETACHED_PROCESS = separate console
                self.process = subprocess.Popen(
                    [self.client_path],
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL
                )
            else:  # Linux/Unix
                self.process = subprocess.Popen(
                    [self.client_path],
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL
                )
            
            self.restart_times.append(time.time())
            logger.info(f"[{self.get_formatted_time()}] client.exe started (PID: {self.process.pid})")
            return True
            
        except Exception as e:
            logger.error(f"[{self.get_formatted_time()}] Failed to launch client.exe: {e}")
            return False
    
    def is_process_running(self):
        """Check if client process is still running"""
        if self.process is None:
            return False
        
        return self.process.poll() is None  # None = still running, other = exit code
    
    def handle_process_termination(self, exit_code):
        """Handle when client.exe terminates"""
        if exit_code is None:
            return  # Still running
        
        timestamp = self.get_formatted_time()
        
        if exit_code == 0:
            logger.info(f"[{timestamp}] client.exe exited gracefully (exit code: 0)")
            self.graceful_shutdown = True
        else:
            logger.warning(f"[{timestamp}] client.exe terminated with exit code: {exit_code}")
    
    def watch(self):
        """Main watchdog loop"""
        logger.info("=" * 60)
        logger.info(f"[{self.get_formatted_time()}] RDPpy Client Watchdog Started")
        logger.info("=" * 60)
        logger.info(f"[{self.get_formatted_time()}] Client path: {self.client_path}")
        logger.info(f"[{self.get_formatted_time()}] Watch interval: {WATCH_INTERVAL}s")
        logger.info(f"[{self.get_formatted_time()}] Max restarts: {MAX_RESTART_ATTEMPTS} per {RESTART_WINDOW}s")
        
        if not self.check_client_exists():
            logger.error(f"[{self.get_formatted_time()}] Cannot start watchdog - client.exe missing")
            return
        
        # Initial launch
        if not self.launch_client():
            logger.error(f"[{self.get_formatted_time()}] Failed to launch client initially")
            return
        
        # Main monitoring loop
        try:
            while self.running:
                time.sleep(WATCH_INTERVAL)
                
                # Check if process is still running
                if not self.is_process_running():
                    exit_code = self.process.returncode
                    self.handle_process_termination(exit_code)
                    
                    # Check if we should attempt restart
                    if self.graceful_shutdown:
                        logger.info(f"[{self.get_formatted_time()}] Graceful shutdown detected - exiting watchdog")
                        self.running = False
                        break
                    
                    if self.should_restart():
                        logger.warning(f"[{self.get_formatted_time()}] Process terminated! Attempting restart...")
                        time.sleep(2)  # Brief delay before restart
                        if not self.launch_client():
                            logger.error(f"[{self.get_formatted_time()}] Restart failed")
                            time.sleep(5)
                    else:
                        logger.error(f"[{self.get_formatted_time()}] Too many restart attempts - giving up")
                        self.running = False
                        break
        
        except KeyboardInterrupt:
            logger.info(f"[{self.get_formatted_time()}] Watchdog interrupted by user")
            self.stop()
        except Exception as e:
            logger.error(f"[{self.get_formatted_time()}] Unexpected error in watchdog: {e}")
            self.stop()
    
    def stop(self):
        """Stop watchdog and terminate client"""
        self.running = False
        timestamp = self.get_formatted_time()
        
        if self.process and self.is_process_running():
            logger.info(f"[{timestamp}] Terminating client process (PID: {self.process.pid})")
            try:
                if os.name == "nt":
                    # Windows: kill process group
                    os.system(f'taskkill /PID {self.process.pid} /T /F')
                else:
                    # Unix: kill process group
                    import signal
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                    self.process.wait(timeout=GRACEFUL_SHUTDOWN_TIMEOUT)
            except Exception as e:
                logger.error(f"[{timestamp}] Error terminating process: {e}")
        
        logger.info(f"[{timestamp}] Watchdog stopped")


def main():
    watchdog = ClientWatchdog(CLIENT_FILENAME)
    try:
        watchdog.watch()
    except Exception as e:
        logger.error(f"[{watchdog.get_formatted_time()}] Fatal error: {e}")
        watchdog.stop()


if __name__ == "__main__":
    main()
