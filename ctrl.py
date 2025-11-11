#!/usr/bin/env python3
import asyncio
import websockets
import json
import base64
import tkinter as tk
from tkinter import ttk, scrolledtext
from PIL import Image, ImageTk
from io import BytesIO
import platform
import threading

class RDPController:
    def __init__(self, server_url):
        self.server_url = server_url
        self.controller_id = f"{platform.node()}_ctrl"
        self.websocket = None
        self.connected_clients = []
        self.selected_client = None
        self.running = False
        self.gui_mode = False
        self.loop = None
        
    def show_menu(self):
        print("\n" + "="*50)
        print("RDP Controller - Main Menu")
        print("="*50)
        print(f"Controller ID: {self.controller_id}")
        print("\n1. Show GUI Controller")
        print("2. List Connected Clients")
        print("3. Send Command (Single Client)")
        print("4. Send Command (All Clients)")
        print("5. Exit")
        print("="*50)
        
    def cli_mode(self):
        print(f"\nStarting Controller CLI Mode...")
        print(f"Connecting to server: {self.server_url}")
        
        conn_thread = threading.Thread(target=self.start_connection, daemon=True)
        conn_thread.start()
        
        asyncio.sleep(2)
        
        while True:
            self.show_menu()
            choice = input("\nSelect option: ").strip()
            
            if choice == '1':
                self.launch_gui()
                break
            elif choice == '2':
                self.list_clients()
            elif choice == '3':
                self.send_single_command()
            elif choice == '4':
                self.send_broadcast_command()
            elif choice == '5':
                print("Exiting...")
                break
            else:
                print("Invalid option!")
                
    def list_clients(self):
        print("\n" + "-"*50)
        print("Connected Clients:")
        print("-"*50)
        if self.connected_clients:
            for i, client in enumerate(self.connected_clients, 1):
                print(f"{i}. {client}")
        else:
            print("No clients connected")
        print("-"*50)
        input("\nPress Enter to continue...")
        
    def send_single_command(self):
        if not self.connected_clients:
            print("\nNo clients available!")
            input("Press Enter to continue...")
            return
            
        print("\n" + "-"*50)
        print("Available Clients:")
        for i, client in enumerate(self.connected_clients, 1):
            print(f"{i}. {client}")
        print("-"*50)
        
        try:
            choice = int(input("\nSelect client number: "))
            if 1 <= choice <= len(self.connected_clients):
                client_id = self.connected_clients[choice - 1]
                command = input("Enter command: ").strip()
                
                if command:
                    asyncio.run_coroutine_threadsafe(
                        self.send_message({
                            'type': 'command',
                            'command': command,
                            'target_clients': [client_id]
                        }),
                        self.loop
                    )
                    print(f"\nCommand sent to {client_id}")
                    print("Check server logs for output")
            else:
                print("Invalid selection!")
        except ValueError:
            print("Invalid input!")
        
        input("\nPress Enter to continue...")
        
    def send_broadcast_command(self):
        if not self.connected_clients:
            print("\nNo clients available!")
            input("Press Enter to continue...")
            return
            
        command = input("\nEnter command to broadcast: ").strip()
        
        if command:
            asyncio.run_coroutine_threadsafe(
                self.send_message({
                    'type': 'command',
                    'command': command,
                    'target_clients': ['all']
                }),
                self.loop
            )
            print(f"\nCommand broadcasted to all clients")
            print("Check server logs for output")
        
        input("\nPress Enter to continue...")
        
    def launch_gui(self):
        self.gui_mode = True
        print("\nLaunching GUI...")
        
        self.root = tk.Tk()
        self.root.title(f"RDP Controller - {self.controller_id}")
        self.root.geometry("1400x800")
        
        self.setup_gui()
        self.root.mainloop()
        
    def setup_gui(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        left_frame = ttk.Frame(main_frame, width=300)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 5))
        
        ttk.Label(left_frame, text="Available Clients:", font=('Arial', 10, 'bold')).pack(pady=(0, 5))
        
        self.client_listbox = tk.Listbox(left_frame, height=10)
        self.client_listbox.pack(fill=tk.BOTH, expand=False, pady=(0, 5))
        self.client_listbox.bind('<<ListboxSelect>>', self.on_client_select)
        
        for client in self.connected_clients:
            self.client_listbox.insert(tk.END, client)
        
        ttk.Button(left_frame, text="Connect to Client", command=self.connect_to_client).pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(left_frame, text="Command:", font=('Arial', 10, 'bold')).pack(pady=(0, 5))
        
        self.command_entry = ttk.Entry(left_frame)
        self.command_entry.pack(fill=tk.X, pady=(0, 5))
        self.command_entry.bind('<Return>', lambda e: self.send_command())
        
        button_frame = ttk.Frame(left_frame)
        button_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Button(button_frame, text="Send", command=self.send_command).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        ttk.Button(button_frame, text="Send to All", command=self.send_command_to_all).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))
        
        ttk.Label(left_frame, text="Command Output:", font=('Arial', 10, 'bold')).pack(pady=(10, 5))
        
        self.output_text = scrolledtext.ScrolledText(left_frame, height=15, width=35)
        self.output_text.pack(fill=tk.BOTH, expand=True)
        
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        ttk.Label(right_frame, text="Client Screen:", font=('Arial', 12, 'bold')).pack(pady=(0, 5))
        
        self.canvas = tk.Canvas(right_frame, bg='black')
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        self.status_label = ttk.Label(self.root, text="Status: Connected to server", relief=tk.SUNKEN)
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)
        
    def on_client_select(self, event):
        selection = self.client_listbox.curselection()
        if selection:
            self.selected_client = self.client_listbox.get(selection[0])
            
    def connect_to_client(self):
        if not self.selected_client:
            self.log_output("Please select a client first")
            return
            
        asyncio.run_coroutine_threadsafe(
            self.send_message({
                'type': 'connect_to_client',
                'client_id': self.selected_client
            }),
            self.loop
        )
        self.log_output(f"Connected to {self.selected_client}")
        self.status_label.config(text=f"Status: Connected to {self.selected_client}")
        
    def send_command(self):
        if not self.selected_client:
            self.log_output("Please select and connect to a client first")
            return
            
        command = self.command_entry.get().strip()
        if not command:
            return
            
        asyncio.run_coroutine_threadsafe(
            self.send_message({
                'type': 'command',
                'command': command,
                'target_clients': [self.selected_client]
            }),
            self.loop
        )
        
        self.log_output(f"\n> {command}")
        self.command_entry.delete(0, tk.END)
        
    def send_command_to_all(self):
        command = self.command_entry.get().strip()
        if not command:
            return
            
        asyncio.run_coroutine_threadsafe(
            self.send_message({
                'type': 'command',
                'command': command,
                'target_clients': ['all']
            }),
            self.loop
        )
        
        self.log_output(f"\n[BROADCAST] > {command}")
        self.command_entry.delete(0, tk.END)
        
    def log_output(self, text):
        if hasattr(self, 'output_text'):
            self.output_text.insert(tk.END, text + "\n")
            self.output_text.see(tk.END)
        
    def update_screenshot(self, image_data):
        if not self.gui_mode or not hasattr(self, 'canvas'):
            return
            
        try:
            img_data = base64.b64decode(image_data)
            img = Image.open(BytesIO(img_data))
            
            canvas_width = self.canvas.winfo_width()
            canvas_height = self.canvas.winfo_height()
            
            if canvas_width > 1 and canvas_height > 1:
                img.thumbnail((canvas_width, canvas_height), Image.Resampling.LANCZOS)
                
            photo = ImageTk.PhotoImage(img)
            
            self.canvas.delete("all")
            self.canvas.create_image(
                canvas_width // 2,
                canvas_height // 2,
                image=photo,
                anchor=tk.CENTER
            )
            self.canvas.image = photo
            
        except Exception as e:
            print(f"Error updating screenshot: {e}")
            
    async def send_message(self, message):
        if self.websocket:
            await self.websocket.send(json.dumps(message))
            
    async def handle_messages(self):
        try:
            async for message in self.websocket:
                data = json.loads(message)
                
                if data['type'] == 'client_list':
                    self.connected_clients = data['clients']
                    if self.gui_mode and hasattr(self, 'client_listbox'):
                        self.client_listbox.delete(0, tk.END)
                        for client_id in data['clients']:
                            self.client_listbox.insert(tk.END, client_id)
                        
                elif data['type'] == 'client_connected':
                    self.connected_clients.append(data['client_id'])
                    if self.gui_mode and hasattr(self, 'client_listbox'):
                        self.client_listbox.insert(tk.END, data['client_id'])
                        self.log_output(f"[INFO] Client connected: {data['client_id']}")
                    
                elif data['type'] == 'client_disconnected':
                    if data['client_id'] in self.connected_clients:
                        self.connected_clients.remove(data['client_id'])
                    if self.gui_mode and hasattr(self, 'client_listbox'):
                        for i in range(self.client_listbox.size()):
                            if self.client_listbox.get(i) == data['client_id']:
                                self.client_listbox.delete(i)
                                break
                        self.log_output(f"[INFO] Client disconnected: {data['client_id']}")
                    
                elif data['type'] == 'screenshot':
                    if data['client_id'] == self.selected_client:
                        self.update_screenshot(data['image'])
                        
                elif data['type'] == 'command_output':
                    if self.gui_mode and data['client_id'] == self.selected_client:
                        self.log_output(data['output'])
                        
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
                    'controller_id': self.controller_id
                }))
                
                print(f"Connected as {self.controller_id}")
                
                await self.handle_messages()
                
        except Exception as e:
            print(f"Connection error: {e}")
            self.running = False
            
    def start_connection(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.connect())
        
    def start(self):
        self.cli_mode()

if __name__ == '__main__':
    SERVER_URL = "ws://YOUR_IP:3200"
    
    controller = RDPController(SERVER_URL)
    controller.start()