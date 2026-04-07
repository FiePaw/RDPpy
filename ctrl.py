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
import time
from datetime import datetime

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

        # Input control state
        self.input_control_enabled = False
        self._coord_lock = threading.Lock()
        self._last_img_offset = (0, 0, 1, 1)    # x_off, y_off, disp_w, disp_h (canvas space)
        self._last_client_size = (1920, 1080)    # True screen resolution of client
        
        # Connection resilience
        self.connection_attempts = 0
        self.max_reconnect_delay = 60
        self.heartbeat_interval = 30
        self.heartbeat_timeout = 10
        self.last_heartbeat_response = time.time()
        self.connection_lost = False
        self.server_connected = False
        
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
        
        # Wait for initial connection attempt
        time.sleep(2)
        
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
                self.running = False
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
        
        ttk.Button(left_frame, text="Connect to Client", command=self.connect_to_client).pack(fill=tk.X, pady=(0, 5))

        # Input control toggle
        self.input_control_var = tk.BooleanVar(value=False)
        self.input_toggle_btn = ttk.Checkbutton(
            left_frame,
            text="🖱 Enable Mouse & Keyboard Control",
            variable=self.input_control_var,
            command=self.toggle_input_control
        )
        self.input_toggle_btn.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(left_frame, text="Command:", font=('Arial', 10, 'bold')).pack(pady=(0, 5))
        
        self.command_entry = ttk.Entry(left_frame)
        self.command_entry.pack(fill=tk.X, pady=(0, 5))
        self.command_entry.bind('<Return>', lambda e: self.send_command())
        
        button_frame = ttk.Frame(left_frame)
        button_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Button(button_frame, text="Send", command=self.send_command).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        ttk.Button(button_frame, text="Send to All", command=self.send_command_to_all).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))
        
        ttk.Label(left_frame, text="Download File:", font=('Arial', 10, 'bold')).pack(pady=(10, 5))
        
        file_frame = ttk.Frame(left_frame)
        file_frame.pack(fill=tk.X, pady=(0, 5))
        
        self.filename_entry = ttk.Entry(file_frame)
        self.filename_entry.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Button(file_frame, text="Download from Client", command=self.download_from_client).pack(fill=tk.X)
        
        ttk.Label(left_frame, text="Command Output:", font=('Arial', 10, 'bold')).pack(pady=(10, 5))
        
        self.output_text = scrolledtext.ScrolledText(left_frame, height=15, width=35)
        self.output_text.pack(fill=tk.BOTH, expand=True)
        
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        ttk.Label(right_frame, text="Client Screen:", font=('Arial', 12, 'bold')).pack(pady=(0, 5))
        
        self.canvas = tk.Canvas(right_frame, bg='black')
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Mouse bindings — use add='+' agar tidak saling override
        self.canvas.bind('<Motion>',          self._on_mouse_move)
        self.canvas.bind('<ButtonPress-1>',   self._on_btn1_press)
        self.canvas.bind('<ButtonRelease-1>', self._on_btn1_release)
        self.canvas.bind('<ButtonPress-3>',   lambda e: self._on_mouse_button(e, 'mousedown', 'right'))
        self.canvas.bind('<ButtonRelease-3>', lambda e: self._on_mouse_button(e, 'mouseup',   'right'))
        self.canvas.bind('<Button-4>',        lambda e: self._on_scroll(e, 'up'))
        self.canvas.bind('<Button-5>',        lambda e: self._on_scroll(e, 'down'))
        self.canvas.bind('<MouseWheel>',      self._on_mousewheel)

        # Keyboard — canvas harus punya fokus
        self.canvas.bind('<KeyPress>',   self._on_key_press)
        self.canvas.bind('<KeyRelease>', self._on_key_release)
        # Auto-fokus saat kursor masuk canvas
        self.canvas.bind('<Enter>', lambda e: self.canvas.focus_set(), add='+')
        self.canvas.config(takefocus=True)

        # Timing untuk deteksi double-click
        self._last_click_time = 0.0
        self._DCLICK_MS = 400  # threshold double-click (ms)
        
        self.status_label = ttk.Label(self.root, text="Status: Connecting...", relief=tk.SUNKEN)
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
        
    def download_from_client(self):
        if not self.selected_client:
            self.log_output("Please select and connect to a client first")
            return
            
        filename = self.filename_entry.get().strip()
        if not filename:
            self.log_output("Please enter a filename to download")
            return
        
        # Send download command to client
        download_command = f"/download {filename}"
        
        asyncio.run_coroutine_threadsafe(
            self.send_message({
                'type': 'command',
                'command': download_command,
                'target_clients': [self.selected_client]
            }),
            self.loop
        )
        
        self.log_output(f"\n[DOWNLOAD] Requesting file: {filename}")
        self.log_output(f"File will be saved to client's local directory")
        self.filename_entry.delete(0, tk.END)
    
    def toggle_input_control(self):
        """Toggle mouse/keyboard control on or off"""
        self.input_control_enabled = self.input_control_var.get()
        state = "ENABLED" if self.input_control_enabled else "DISABLED"
        self.log_output(f"[INPUT] Mouse & Keyboard control {state}")
        if self.input_control_enabled:
            self.canvas.config(cursor="crosshair")
        else:
            self.canvas.config(cursor="")

    def _canvas_to_client_coords(self, cx, cy):
        """Convert canvas pixel coords → true client screen coords."""
        with self._coord_lock:
            x_off, y_off, disp_w, disp_h = self._last_img_offset
            client_w, client_h = self._last_client_size

        # coords relative to the displayed image origin
        rel_x = cx - x_off
        rel_y = cy - y_off

        if disp_w <= 0 or disp_h <= 0:
            return 0, 0

        # Scale displayed-image pixels → real client screen pixels
        real_x = int(rel_x * client_w / disp_w)
        real_y = int(rel_y * client_h / disp_h)

        # Clamp
        real_x = max(0, min(real_x, client_w - 1))
        real_y = max(0, min(real_y, client_h - 1))
        return real_x, real_y

    def _send_mouse(self, data):
        if not self.input_control_enabled or not self.selected_client:
            return
        data['client_id'] = self.selected_client
        asyncio.run_coroutine_threadsafe(
            self.send_message(data), self.loop
        )

    def _send_keyboard(self, data):
        if not self.input_control_enabled or not self.selected_client:
            return
        data['client_id'] = self.selected_client
        asyncio.run_coroutine_threadsafe(
            self.send_message(data), self.loop
        )

    def _on_mouse_move(self, event):
        if not self.input_control_enabled:
            return
        x, y = self._canvas_to_client_coords(event.x, event.y)
        self._send_mouse({'type': 'mouse_event', 'action': 'move', 'x': x, 'y': y})

    def _on_btn1_press(self, event):
        """Handle left button press — juga set fokus canvas."""
        self.canvas.focus_set()
        if not self.input_control_enabled or not self.selected_client:
            return
        now = time.time() * 1000
        dt  = now - self._last_click_time
        self._last_click_time = now

        x, y = self._canvas_to_client_coords(event.x, event.y)
        if dt < self._DCLICK_MS:
            # Double-click: kirim 2x down+up sekaligus
            self._send_mouse({'type': 'mouse_event', 'action': 'double_click', 'x': x, 'y': y, 'button': 'left'})
        else:
            self._send_mouse({'type': 'mouse_event', 'action': 'mousedown', 'x': x, 'y': y, 'button': 'left'})

    def _on_btn1_release(self, event):
        if not self.input_control_enabled or not self.selected_client:
            return
        x, y = self._canvas_to_client_coords(event.x, event.y)
        self._send_mouse({'type': 'mouse_event', 'action': 'mouseup', 'x': x, 'y': y, 'button': 'left'})

    def _on_mouse_button(self, event, action, button):
        if not self.input_control_enabled or not self.selected_client:
            return
        x, y = self._canvas_to_client_coords(event.x, event.y)
        self._send_mouse({'type': 'mouse_event', 'action': action, 'x': x, 'y': y, 'button': button})

    def _on_scroll(self, event, direction):
        if not self.input_control_enabled or not self.selected_client:
            return
        x, y = self._canvas_to_client_coords(event.x, event.y)
        self._send_mouse({'type': 'mouse_event', 'action': 'scroll', 'x': x, 'y': y, 'direction': direction, 'clicks': 3})

    def _on_mousewheel(self, event):
        if not self.input_control_enabled or not self.selected_client:
            return
        direction = 'up' if event.delta > 0 else 'down'
        x, y = self._canvas_to_client_coords(event.x, event.y)
        self._send_mouse({'type': 'mouse_event', 'action': 'scroll', 'x': x, 'y': y, 'direction': direction, 'clicks': 3})

    # Tkinter keysym → nama key yang dikenali _VK_MAP di client
    _TK_TO_KEY = {
        'Return': 'enter', 'BackSpace': 'backspace', 'Delete': 'delete',
        'Escape': 'escape', 'Tab': 'tab', 'space': 'space',
        'Up': 'up', 'Down': 'down', 'Left': 'left', 'Right': 'right',
        'Home': 'home', 'End': 'end', 'Prior': 'pageup', 'Next': 'pagedown',
        'Insert': 'insert', 'F1': 'f1', 'F2': 'f2', 'F3': 'f3', 'F4': 'f4',
        'F5': 'f5', 'F6': 'f6', 'F7': 'f7', 'F8': 'f8', 'F9': 'f9',
        'F10': 'f10', 'F11': 'f11', 'F12': 'f12',
        'Control_L': 'ctrlleft', 'Control_R': 'ctrlright',
        'Alt_L': 'altleft',      'Alt_R': 'altright',
        'Shift_L': 'shiftleft',  'Shift_R': 'shiftright',
        'Win_L': 'winleft',      'Win_R': 'winright',
        'caps_lock': 'capslock', 'Caps_Lock': 'capslock',
    }
    _MODIFIER_SYMS = {'Control_L', 'Control_R', 'Alt_L', 'Alt_R',
                      'Shift_L', 'Shift_R', 'Win_L', 'Win_R'}

    def _resolve_key(self, event) -> str:
        """
        Kembalikan nama key yang bisa dikenali _VK_MAP di client.
        Selalu pakai keysym (bukan event.char) supaya VK lookup konsisten.
        """
        keysym = event.keysym
        if keysym in self._TK_TO_KEY:
            return self._TK_TO_KEY[keysym]
        # Single char: pakai keysym lowercase (misal 'A' → 'a', 'question' → tetap)
        if len(keysym) == 1:
            return keysym.lower()
        # Multi-char yang tidak dikenal (misal 'exclam', 'at', dll) — fallback ke char
        if event.char and len(event.char) == 1:
            return event.char
        return keysym.lower()

    def _on_key_press(self, event):
        if not self.input_control_enabled:
            return

        keysym = event.keysym
        state  = event.state
        ctrl   = bool(state & 0x4)
        alt    = bool(state & 0x8)  # Mod1
        shift  = bool(state & 0x1)

        # Modifier key press saja → kirim keydown supaya client bisa "hold"
        if keysym in self._MODIFIER_SYMS:
            self._send_keyboard({
                'type': 'keyboard_event', 'action': 'keydown',
                'key': self._TK_TO_KEY[keysym]
            })
            return

        key = self._resolve_key(event)

        # Ctrl+key atau Alt+key → hotkey
        if ctrl or alt:
            combo = []
            if ctrl:  combo.append('ctrl')
            if alt:   combo.append('alt')
            if shift: combo.append('shift')
            combo.append(key)
            self._send_keyboard({'type': 'keyboard_event', 'action': 'hotkey', 'keys': combo})
            return

        # Shift+printable → typewrite agar WM_CHAR hasilkan karakter kapital/simbol yang benar
        if shift and event.char and event.char.isprintable() and len(event.char) == 1:
            self._send_keyboard({'type': 'keyboard_event', 'action': 'typewrite', 'text': event.char})
            return

        # Tombol normal
        self._send_keyboard({'type': 'keyboard_event', 'action': 'keydown', 'key': key})

    def _on_key_release(self, event):
        if not self.input_control_enabled:
            return

        keysym = event.keysym
        state  = event.state
        shift  = bool(state & 0x1)

        # Modifier release
        if keysym in self._MODIFIER_SYMS:
            self._send_keyboard({
                'type': 'keyboard_event', 'action': 'keyup',
                'key': self._TK_TO_KEY[keysym]
            })
            return

        # Shift+printable sudah ditangani typewrite saat press — skip keyup-nya
        if shift and event.char and event.char.isprintable() and len(event.char) == 1:
            return

        key = self._resolve_key(event)
        self._send_keyboard({'type': 'keyboard_event', 'action': 'keyup', 'key': key})

    def get_reconnect_delay(self):
        """Calculate exponential backoff delay"""
        delay = min(2 ** self.connection_attempts, self.max_reconnect_delay)
        jitter = delay * 0.1  # Add 10% jitter
        return delay + (jitter * (time.time() % 1))
    
    def update_status(self, message, is_error=False):
        """Update status label with color indication"""
        if self.gui_mode and hasattr(self, 'status_label'):
            self.status_label.config(text=message)
            if is_error:
                self.status_label.config(foreground="red")
            else:
                self.status_label.config(foreground="green" if self.server_connected else "orange")
        
    def log_output(self, text):
        if hasattr(self, 'output_text'):
            self.output_text.insert(tk.END, text + "\n")
            self.output_text.see(tk.END)
        
    def update_screenshot(self, image_data, screen_w=0, screen_h=0):
        if not self.gui_mode or not hasattr(self, 'canvas'):
            return
        # Schedule render di main thread tkinter agar tidak blocking
        self.root.after(0, self._render_frame, image_data, screen_w, screen_h)

    def _render_frame(self, image_data, screen_w, screen_h):
        """Render frame screenshot ke canvas — dipanggil di main thread via after()."""
        try:
            img_data = base64.b64decode(image_data)
            img = Image.open(BytesIO(img_data))

            canvas_width  = self.canvas.winfo_width()
            canvas_height = self.canvas.winfo_height()

            if canvas_width <= 1 or canvas_height <= 1:
                return

            img.thumbnail((canvas_width, canvas_height), Image.Resampling.LANCZOS)

            disp_w, disp_h = img.size
            x_off = (canvas_width  - disp_w) // 2
            y_off = (canvas_height - disp_h) // 2

            real_w = screen_w if screen_w > 0 else disp_w
            real_h = screen_h if screen_h > 0 else disp_h

            with self._coord_lock:
                self._last_img_offset  = (x_off, y_off, disp_w, disp_h)
                self._last_client_size = (real_w, real_h)

            photo = ImageTk.PhotoImage(img)
            self.canvas.delete("all")
            self.canvas.create_image(
                canvas_width  // 2,
                canvas_height // 2,
                image=photo,
                anchor=tk.CENTER
            )
            self.canvas.image = photo  # cegah garbage collection

        except Exception as e:
            print(f"Error rendering frame: {e}")
            
    async def send_message(self, message):
        if self.websocket:
            await self.websocket.send(json.dumps(message))
    
    async def heartbeat_loop(self):
        """Send periodic heartbeat to detect dead connections"""
        while self.running:
            try:
                if self.websocket and self.server_connected:
                    await self.websocket.send(json.dumps({
                        'type': 'heartbeat',
                        'timestamp': datetime.now().isoformat()
                    }))
                    self.last_heartbeat_response = time.time()
                
                await asyncio.sleep(self.heartbeat_interval)
            except Exception as e:
                print(f"Heartbeat error: {e}")
                self.connection_lost = True
                break
            
    async def handle_messages(self):
        try:
            async for message in self.websocket:
                data = json.loads(message)
                
                if data['type'] == 'heartbeat':
                    # Server responding to heartbeat
                    self.last_heartbeat_response = time.time()
                    
                elif data['type'] == 'client_list':
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
                        self.update_screenshot(data['image'], data.get('screen_w', 0), data.get('screen_h', 0))
                        
                elif data['type'] == 'command_output':
                    if self.gui_mode and data['client_id'] == self.selected_client:
                        self.log_output(data['output'])
                        
        except websockets.exceptions.ConnectionClosed:
            print("Connection closed by server")
            self.connection_lost = True
            self.server_connected = False
            self.running = False
            if self.gui_mode:
                self.update_status("Status: Disconnected from server", is_error=True)
        except Exception as e:
            print(f"Error in handle_messages: {e}")
            self.connection_lost = True
            self.server_connected = False
            self.running = False
            if self.gui_mode:
                self.update_status(f"Status: Error - {type(e).__name__}", is_error=True)
            
    async def connect(self):
        try:
            print(f"[CONNECT] Attempting connection to {self.server_url}")
            print(f"[CONNECT] Attempt {self.connection_attempts + 1}")
            
            if self.gui_mode:
                self.update_status(f"Status: Connecting... (Attempt {self.connection_attempts + 1})")
            
            async with websockets.connect(
                self.server_url,
                ping_interval=self.heartbeat_interval,
                ping_timeout=self.heartbeat_timeout
            ) as websocket:
                self.websocket = websocket
                self.running = True
                self.server_connected = True
                self.connection_lost = False
                self.connection_attempts = 0
                
                print(f"✓ Connected to server")
                
                await websocket.send(json.dumps({
                    'type': 'register',
                    'controller_id': self.controller_id
                }))
                
                print(f"Connected as {self.controller_id}")
                
                if self.gui_mode:
                    self.update_status("Status: Connected to server")
                    if hasattr(self, 'output_text'):
                        self.log_output("[INFO] Connected to server")
                
                await asyncio.gather(
                    self.handle_messages(),
                    self.heartbeat_loop(),
                    return_exceptions=True
                )
                
        except asyncio.TimeoutError:
            print(f"✗ Connection timeout to {self.server_url}")
            if self.gui_mode:
                self.update_status("Status: Connection timeout", is_error=True)
            self.running = False
        except websockets.exceptions.InvalidStatusException as e:
            print(f"✗ Server rejected connection: {e}")
            if self.gui_mode:
                self.update_status("Status: Server rejected connection", is_error=True)
            self.running = False
        except websockets.exceptions.WebSocketException as e:
            print(f"✗ WebSocket error: {e}")
            if self.gui_mode:
                self.update_status(f"Status: WebSocket error", is_error=True)
            self.running = False
        except ConnectionRefusedError:
            print(f"✗ Connection refused - server may be offline")
            if self.gui_mode:
                self.update_status("Status: Connection refused (server offline?)", is_error=True)
            self.running = False
        except Exception as e:
            print(f"✗ Connection error: {type(e).__name__}: {e}")
            if self.gui_mode:
                self.update_status(f"Status: {type(e).__name__}", is_error=True)
            self.running = False
            
    def start_connection(self):
        """Run the async event loop in a separate thread"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        # Run the main connection loop
        try:
            self.loop.run_until_complete(self._connection_loop())
        except KeyboardInterrupt:
            print("\n[SHUTDOWN] Controller connection terminated by user")
        finally:
            self.loop.close()
    
    async def _connection_loop(self):
        """Main connection loop with automatic reconnection"""
        while True:
            try:
                await self.connect()
            except Exception as e:
                print(f"[ERROR] Unexpected error: {e}")
            
            if not self.running:
                delay = self.get_reconnect_delay()
                self.connection_attempts += 1
                
                print(f"\n[RECONNECT] Reconnecting in {delay:.1f} seconds...")
                print(f"[INFO] Attempt {self.connection_attempts} of unlimited")
                
                if self.gui_mode:
                    self.update_status(f"Status: Reconnecting in {delay:.1f}s (Attempt {self.connection_attempts})")
                
                try:
                    await asyncio.sleep(delay)
                except Exception:
                    break
        
    def start(self):
        self.cli_mode()

if __name__ == '__main__':
    SERVER_URL = "ws://108.137.15.61:3200"
    
    controller = RDPController(SERVER_URL)
    controller.start()
