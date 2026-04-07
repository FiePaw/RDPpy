#!/usr/bin/env python3
import asyncio
import websockets
import json
import logging
import base64
import os
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CHUNK_SIZE = 65536  # 64KB per chunk

class RDPServer:
    def __init__(self):
        self.clients = {}
        self.controllers = {}
        self.client_to_controller = {}
        self.screenshot_tasks = {}
        self.storage_path = "/root/rdp/storages"
        self.file_cache = {}  # Cache opened files
        os.makedirs(self.storage_path, exist_ok=True)
    
    def get_formatted_time(self):
        """Return formatted time as 'DayName:HH:MM:SS'"""
        now = datetime.now()
        day_name = now.strftime('%A')  # Full day name (Monday, Tuesday, etc.)
        time_str = now.strftime('%H:%M:%S')
        return f"{day_name}:{time_str}"
    
    async def handle_file_request(self, websocket, client_id, filename):
        """Handle file request by sending file metadata and chunks"""
        filepath = os.path.join(self.storage_path, filename)
        timestamp = self.get_formatted_time()
        
        if not os.path.exists(filepath) or not os.path.isfile(filepath):
            await websocket.send(json.dumps({
                'type': 'file_metadata',
                'filename': filename,
                'success': False,
                'error': 'File not found',
                'timestamp': timestamp
            }))
            return
        
        try:
            file_size = os.path.getsize(filepath)
            total_chunks = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE
            
            # Send file metadata
            await websocket.send(json.dumps({
                'type': 'file_metadata',
                'filename': filename,
                'file_size': file_size,
                'total_chunks': total_chunks,
                'chunk_size': CHUNK_SIZE,
                'success': True,
                'timestamp': timestamp
            }))
            
            # Cache file handle for chunk requests
            self.file_cache[f"{client_id}_{filename}"] = {
                'filepath': filepath,
                'file_size': file_size,
                'total_chunks': total_chunks
            }
            
            logger.info(f"[{timestamp}] File metadata sent to {client_id}: {filename} ({file_size} bytes, {total_chunks} chunks)")
            
        except Exception as e:
            await websocket.send(json.dumps({
                'type': 'file_metadata',
                'filename': filename,
                'success': False,
                'error': str(e),
                'timestamp': timestamp
            }))
    
    async def handle_chunk_request(self, websocket, client_id, filename, chunk_index):
        """Send specific chunk of file"""
        cache_key = f"{client_id}_{filename}"
        timestamp = self.get_formatted_time()
        
        if cache_key not in self.file_cache:
            await websocket.send(json.dumps({
                'type': 'file_chunk',
                'filename': filename,
                'chunk_index': chunk_index,
                'success': False,
                'error': 'File not requested first',
                'timestamp': timestamp
            }))
            return
        
        try:
            file_info = self.file_cache[cache_key]
            filepath = file_info['filepath']
            
            with open(filepath, 'rb') as f:
                f.seek(chunk_index * CHUNK_SIZE)
                chunk_data = f.read(CHUNK_SIZE)
                chunk_data_b64 = base64.b64encode(chunk_data).decode()
            
            await websocket.send(json.dumps({
                'type': 'file_chunk',
                'filename': filename,
                'chunk_index': chunk_index,
                'total_chunks': file_info['total_chunks'],
                'data': chunk_data_b64,
                'success': True,
                'timestamp': timestamp
            }))
            
        except Exception as e:
            await websocket.send(json.dumps({
                'type': 'file_chunk',
                'filename': filename,
                'chunk_index': chunk_index,
                'success': False,
                'error': str(e),
                'timestamp': timestamp
            }))
        
    async def register_client(self, websocket, client_id):
        self.clients[client_id] = websocket
        timestamp = self.get_formatted_time()
        logger.info(f"[{timestamp}] Client {client_id} connected")
        
        await self.broadcast_to_controllers({
            'type': 'client_connected',
            'client_id': client_id,
            'timestamp': timestamp
        })
        
    async def register_controller(self, websocket, controller_id):
        self.controllers[controller_id] = websocket
        timestamp = self.get_formatted_time()
        logger.info(f"[{timestamp}] Controller {controller_id} connected")
        
        await websocket.send(json.dumps({
            'type': 'client_list',
            'clients': list(self.clients.keys()),
            'timestamp': timestamp
        }))
        
    async def handle_client(self, websocket):
        client_id = None
        try:
            msg = await websocket.recv()
            data = json.loads(msg)
            
            if data['type'] == 'register':
                client_id = data['client_id']
                await self.register_client(websocket, client_id)
                
            async for message in websocket:
                data = json.loads(message)
                timestamp = self.get_formatted_time()
                
                if data['type'] == 'screenshot':
                    if client_id in self.client_to_controller:
                        tasks = []
                        for ctrl_id in self.client_to_controller[client_id]:
                            if ctrl_id in self.controllers:
                                tasks.append(
                                    self.controllers[ctrl_id].send(json.dumps({
                                        'type': 'screenshot',
                                        'client_id': client_id,
                                        'image': data['image'],
                                        'screen_w': data.get('screen_w', 0),
                                        'screen_h': data.get('screen_h', 0),
                                        'timestamp': timestamp
                                    }))
                                )
                        if tasks:
                            await asyncio.gather(*tasks, return_exceptions=True)
                                
                elif data['type'] == 'command_output':
                    if client_id in self.client_to_controller:
                        tasks = []
                        for ctrl_id in self.client_to_controller[client_id]:
                            if ctrl_id in self.controllers:
                                tasks.append(
                                    self.controllers[ctrl_id].send(json.dumps({
                                        'type': 'command_output',
                                        'client_id': client_id,
                                        'output': data['output'],
                                        'command': data['command'],
                                        'timestamp': timestamp
                                    }))
                                )
                        if tasks:
                            await asyncio.gather(*tasks, return_exceptions=True)
                            
                elif data['type'] == 'request_file':
                    filename = data['filename']
                    await self.handle_file_request(websocket, client_id, filename)
                    
                elif data['type'] == 'get_chunk':
                    filename = data['filename']
                    chunk_index = data['chunk_index']
                    await self.handle_chunk_request(websocket, client_id, filename, chunk_index)
                                
        except websockets.exceptions.ConnectionClosed:
            timestamp = self.get_formatted_time()
            logger.info(f"[{timestamp}] Client {client_id} disconnected")
        finally:
            if client_id:
                if client_id in self.clients:
                    del self.clients[client_id]
                if client_id in self.client_to_controller:
                    del self.client_to_controller[client_id]
                timestamp = self.get_formatted_time()
                await self.broadcast_to_controllers({
                    'type': 'client_disconnected',
                    'client_id': client_id,
                    'timestamp': timestamp
                })
                
    async def handle_controller(self, websocket):
        controller_id = None
        try:
            msg = await websocket.recv()
            data = json.loads(msg)
            
            if data['type'] == 'register':
                controller_id = data['controller_id']
                await self.register_controller(websocket, controller_id)
                
            async for message in websocket:
                data = json.loads(message)
                timestamp = self.get_formatted_time()
                
                if data['type'] == 'connect_to_client':
                    client_id = data['client_id']
                    if client_id not in self.client_to_controller:
                        self.client_to_controller[client_id] = []
                    if controller_id not in self.client_to_controller[client_id]:
                        self.client_to_controller[client_id].append(controller_id)
                    
                    if client_id in self.clients:
                        await self.clients[client_id].send(json.dumps({
                            'type': 'start_screenshot',
                            'timestamp': timestamp
                        }))
                    
                    logger.info(f"[{timestamp}] Controller {controller_id} connected to Client {client_id}")
                    
                elif data['type'] == 'disconnect_from_client':
                    client_id = data['client_id']
                    if client_id in self.client_to_controller:
                        if controller_id in self.client_to_controller[client_id]:
                            self.client_to_controller[client_id].remove(controller_id)
                            
                        if not self.client_to_controller[client_id]:
                            del self.client_to_controller[client_id]
                            if client_id in self.clients:
                                await self.clients[client_id].send(json.dumps({
                                    'type': 'stop_screenshot',
                                    'timestamp': timestamp
                                }))
                            
                elif data['type'] == 'mouse_event':
                    client_id = data.get('client_id')
                    if client_id and client_id in self.clients:
                        await self.clients[client_id].send(json.dumps(data))

                elif data['type'] == 'keyboard_event':
                    client_id = data.get('client_id')
                    if client_id and client_id in self.clients:
                        await self.clients[client_id].send(json.dumps(data))

                elif data['type'] == 'command':
                    target_clients = data.get('target_clients', [])
                    
                    if target_clients == ['all']:
                        tasks = []
                        for cid, ws in self.clients.items():
                            tasks.append(
                                ws.send(json.dumps({
                                    'type': 'command',
                                    'command': data['command'],
                                    'timestamp': timestamp
                                }))
                            )
                        if tasks:
                            await asyncio.gather(*tasks, return_exceptions=True)
                    else:
                        tasks = []
                        for cid in target_clients:
                            if cid in self.clients:
                                tasks.append(
                                    self.clients[cid].send(json.dumps({
                                        'type': 'command',
                                        'command': data['command'],
                                        'timestamp': timestamp
                                    }))
                                )
                        if tasks:
                            await asyncio.gather(*tasks, return_exceptions=True)
                                
        except websockets.exceptions.ConnectionClosed:
            timestamp = self.get_formatted_time()
            logger.info(f"[{timestamp}] Controller {controller_id} disconnected")
        finally:
            if controller_id:
                if controller_id in self.controllers:
                    del self.controllers[controller_id]
                
                for client_id in list(self.client_to_controller.keys()):
                    if controller_id in self.client_to_controller[client_id]:
                        self.client_to_controller[client_id].remove(controller_id)
                        if not self.client_to_controller[client_id]:
                            del self.client_to_controller[client_id]
                            if client_id in self.clients:
                                timestamp = self.get_formatted_time()
                                await self.clients[client_id].send(json.dumps({
                                    'type': 'stop_screenshot',
                                    'timestamp': timestamp
                                }))
                
    async def broadcast_to_controllers(self, message):
        if self.controllers:
            tasks = [ws.send(json.dumps(message)) for ws in self.controllers.values()]
            await asyncio.gather(*tasks, return_exceptions=True)
            
    async def start_server(self, host='0.0.0.0', client_port=3500, controller_port=3200):
        client_server = await websockets.serve(
            self.handle_client, host, client_port
        )
        controller_server = await websockets.serve(
            self.handle_controller, host, controller_port
        )
        
        timestamp = self.get_formatted_time()
        logger.info(f"[{timestamp}] Server started:")
        logger.info(f"[{timestamp}]   - Client port: {client_port}")
        logger.info(f"[{timestamp}]   - Controller port: {controller_port}")
        
        await asyncio.gather(
            client_server.wait_closed(),
            controller_server.wait_closed()
        )

if __name__ == '__main__':
    server = RDPServer()
    asyncio.run(server.start_server())
