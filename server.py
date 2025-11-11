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

class RDPServer:
    def __init__(self):
        self.clients = {}
        self.controllers = {}
        self.client_to_controller = {}
        self.screenshot_tasks = {}
        self.storage_path = "/root/rdp/storages"
        os.makedirs(self.storage_path, exist_ok=True)
        
    async def register_client(self, websocket, client_id):
        self.clients[client_id] = websocket
        logger.info(f"Client {client_id} connected")
        
        await self.broadcast_to_controllers({
            'type': 'client_connected',
            'client_id': client_id,
            'timestamp': datetime.now().isoformat()
        })
        
    async def register_controller(self, websocket, controller_id):
        self.controllers[controller_id] = websocket
        logger.info(f"Controller {controller_id} connected")
        
        await websocket.send(json.dumps({
            'type': 'client_list',
            'clients': list(self.clients.keys())
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
                                        'timestamp': data['timestamp']
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
                                        'command': data['command']
                                    }))
                                )
                        if tasks:
                            await asyncio.gather(*tasks, return_exceptions=True)
                            
                elif data['type'] == 'request_file':
                    filename = data['filename']
                    filepath = os.path.join(self.storage_path, filename)
                    
                    if os.path.exists(filepath) and os.path.isfile(filepath):
                        try:
                            with open(filepath, 'rb') as f:
                                file_data = base64.b64encode(f.read()).decode()
                            
                            await websocket.send(json.dumps({
                                'type': 'file_data',
                                'filename': filename,
                                'data': file_data,
                                'success': True
                            }))
                            logger.info(f"Sent file {filename} to client {client_id}")
                        except Exception as e:
                            await websocket.send(json.dumps({
                                'type': 'file_data',
                                'filename': filename,
                                'error': str(e),
                                'success': False
                            }))
                    else:
                        await websocket.send(json.dumps({
                            'type': 'file_data',
                            'filename': filename,
                            'error': 'File not found',
                            'success': False
                        }))
                                
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Client {client_id} disconnected")
        finally:
            if client_id:
                if client_id in self.clients:
                    del self.clients[client_id]
                if client_id in self.client_to_controller:
                    del self.client_to_controller[client_id]
                await self.broadcast_to_controllers({
                    'type': 'client_disconnected',
                    'client_id': client_id
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
                
                if data['type'] == 'connect_to_client':
                    client_id = data['client_id']
                    if client_id not in self.client_to_controller:
                        self.client_to_controller[client_id] = []
                    if controller_id not in self.client_to_controller[client_id]:
                        self.client_to_controller[client_id].append(controller_id)
                    
                    if client_id in self.clients:
                        await self.clients[client_id].send(json.dumps({
                            'type': 'start_screenshot'
                        }))
                    
                    logger.info(f"Controller {controller_id} connected to Client {client_id}")
                    
                elif data['type'] == 'disconnect_from_client':
                    client_id = data['client_id']
                    if client_id in self.client_to_controller:
                        if controller_id in self.client_to_controller[client_id]:
                            self.client_to_controller[client_id].remove(controller_id)
                            
                        if not self.client_to_controller[client_id]:
                            del self.client_to_controller[client_id]
                            if client_id in self.clients:
                                await self.clients[client_id].send(json.dumps({
                                    'type': 'stop_screenshot'
                                }))
                            
                elif data['type'] == 'command':
                    target_clients = data.get('target_clients', [])
                    
                    if target_clients == ['all']:
                        tasks = []
                        for cid, ws in self.clients.items():
                            tasks.append(
                                ws.send(json.dumps({
                                    'type': 'command',
                                    'command': data['command']
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
                                        'command': data['command']
                                    }))
                                )
                        if tasks:
                            await asyncio.gather(*tasks, return_exceptions=True)
                                
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Controller {controller_id} disconnected")
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
                                await self.clients[client_id].send(json.dumps({
                                    'type': 'stop_screenshot'
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
        
        logger.info(f"Server started:")
        logger.info(f"  - Client port: {client_port}")
        logger.info(f"  - Controller port: {controller_port}")
        
        await asyncio.gather(
            client_server.wait_closed(),
            controller_server.wait_closed()
        )

if __name__ == '__main__':
    server = RDPServer()
    asyncio.run(server.start_server())