# RDPpy - CHANGELOG

## [2.1.0] - 2026-04-06

### 🎯 Major Update: Client Watchdog System

#### ✨ New Features

**1. Watchdog.py - Auto-Restart Mechanism**
- **Auto-Detection**: Mendeteksi terminasi client.py melalui Task Manager atau taskkill
- **Smart Restart**: Otomatis me-restart client.py jika process terminated
- **Process Monitoring**: Monitor berkelanjutan dengan interval 2 detik
- **Graceful Shutdown**: Membedakan antara graceful exit vs force termination
- **Restart Protection**: Smart backoff mechanism untuk prevent infinite restart loops
  - Max 5 restart attempts dalam 60 detik
  - Jika exceed limit, watchdog akan berhenti untuk prevent resource waste
- **Comprehensive Logging**: Full logging ke file `/logs/watchdog.log`

**2. Isolated Command Execution - Client Command Processing**
- **Process Isolation**: Setiap command berjalan di separate process group (Windows) atau session (Linux)
- **Concurrent Execution**: Multiple commands dapat berjalan paralel tanpa blocking client process
- **PID Tracking**: Setiap command di-track dengan PID untuk monitoring & cleanup
- **Status Tracking**: Return status dict dengan: `status`, `output`, `pid`, `exit_code`, `command`
- **Timeout Protection**: 30-second timeout per command dengan auto-termination
- **Comprehensive Logging**: Full lifecycle logging dengan format `[DayName:HH:MM:SS] [SECTION] Message`
- **Graceful Cleanup**: Active commands di-cleanup saat client disconnect

#### 🔧 Technical Details

**Watchdog Architecture:**
```
watchdog.py
├── Process Management
│   ├── Launch client.py as subprocess
│   ├── Monitor process status setiap 2 detik
│   └── Handle termination & restart
├── Restart Logic
│   ├── Detect unintended termination
│   ├── Check restart backoff limits
│   └── Auto-restart dengan delay 2detik
└── Logging System
    ├── Log ke file: /logs/watchdog.log
    ├── Format: [DayName:HH:MM:SS] [LEVEL] message
    └── Track: launch, restart, errors, termination
```

**Key Features:**

1. **Process Isolation (Windows & Linux)**
   - Windows: `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`
   - Linux: `start_new_session=True`
   - Memastikan watchdog bisa monitor child process

2. **Restart Prevention Logic**
   ```
   - Track restart times dalam 60 detik window
   - Prevent > 5 restarts dalam window tersebut
   - Automatic cleanup old restart history
   - Graceful backoff when limit exceeded
   ```

3. **Exit Code Handling**
   ```
   - Exit 0 → Graceful shutdown (stop watchdog)
   - Exit != 0 → Unexpected termination (restart)
   - No exit code → Still running (normal)
   ```

4. **Signal Handling**
   - Graceful interruption via KeyboardInterrupt
   - Proper cleanup on shutdown
   - Safe termination of child processes

#### 📝 Configuration Parameters

```python
WATCH_INTERVAL = 2              # Check every 2 seconds
GRACEFUL_SHUTDOWN_TIMEOUT = 5   # Timeout untuk graceful shutdown
MAX_RESTART_ATTEMPTS = 5        # Max restart dalam 60 detik
RESTART_WINDOW = 60             # Time window monitoring (detik)
```

#### 🚀 Usage

**Manual Launch:**
```bash
python watchdog.py
```

**Via TaskScheduler (Recommended for Production):**
1. Open Task Scheduler
2. Create Basic Task
   - Name: "RDPpy Watchdog"
   - Trigger: "At Startup" atau "On logon"
3. Set Action:
   ```
   Program: C:\Python311\python.exe
   Arguments: C:\Users\SPIN\Desktop\RDPy\watchdog.py
   Start in: C:\Users\SPIN\Desktop\RDPy\
   ```
4. Enable: Run with highest privileges

#### 📊 Monitoring Scenarios

| Scenario | Watchdog Action |
|----------|--------|
| Client running normally | Continue monitoring |
| User kills via Task Manager | Auto-restart in 2s |
| taskkill command executed | Auto-restart in 2s |
| Client crashes (exit != 0) | Auto-restart in 2s |
| Graceful exit (exit 0) | Stop watchdog |
| 5+ restarts in 60s | Stop (prevent loop) |
| Process resource monitoring | Check every 2s |

#### 📋 Log Output Example

```
[Monday:14:32:15] [INFO] RDPpy Client Watchdog Started
============================================================
[Monday:14:32:15] [INFO] Client path: C:\Users\SPIN\Desktop\RDPy\client.py
[Monday:14:32:15] [INFO] Watch interval: 2s
[Monday:14:32:15] [INFO] Max restarts: 5 per 60s
[Monday:14:32:16] [INFO] ✓ client.py started (PID: 5432)
[Monday:14:35:22] [WARNING] Process terminated! Attempting restart...
[Monday:14:35:24] [INFO] ✓ client.py started (PID: 5891)
[Monday:14:40:15] [INFO] client.py exited gracefully (exit code: 0)
[Monday:14:40:15] [INFO] Graceful shutdown detected - exiting watchdog
```

#### 🔐 Security Considerations

- Process runs with same privileges as watchdog
- Subprocess communication via stdin/stdout redirection to DEVNULL
- Isolated process group prevents watchdog crash affecting client
- File logging for audit trail

#### 🛠️ Integration Architecture

```
TaskScheduler (Startup)
        ↓
   watchdog.py (Monitor)
        ↓
   client.py (RDP Client)
        ↓
   Server.py (RDP Server via WebSocket)
        ↓
   Controllers (Connect & Control)
```

**Updated Workflow:**
```
1. System Startup
   ↓
2. TaskScheduler triggers watchdog.py
   ↓
3. Watchdog launches client.py
   ↓
4. Watchdog monitors client.py continuously
   ├─ Process running normally → Continue monitoring
   ├─ Process terminated unexpectedly → Auto-restart
   └─ Process graceful exit → Stop watchdog
   ↓
5. Client.py maintains connection to server.py
   ↓
6. Controller commands relayed via server.py
```

#### 🎬 Isolated Command Execution Architecture

**Command Lifecycle:**
```
Controller (ctrl.py)
    |
    | Send command via WebSocket
    v
Server (server.py)
    |
    | Route to Client
    v
RDPClient (client.py)
    |
    +--[handle_commands]
    |   ├─ Receive command message
    |   ├─ Log command reception
    |   └─ Queue command
    |
    +--[command_processor]
    |   ├─ Extract from queue
    |   ├─ Call execute_command()
    |   └─ Send result to controller
    |
    +--[execute_command_isolated]
         ├─ Windows: spawn cmd.exe (CREATE_NEW_PROCESS_GROUP)
         ├─ Linux: spawn /bin/bash (start_new_session=True)
         ├─ Track PID in active_commands dict
         ├─ Capture stdout/stderr (30s timeout)
         └─ Return status dict (success/failed/timeout/error)
    |
    v
Result formatting with metadata
    |
    v
Send to Controller [Status/PID/ExitCode]
```

**Key Implementation Details:**

1. **Process Spawning - Windows**
   ```python
   subprocess.Popen(
       ['cmd.exe', '/c', command],
       creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
       stdout=PIPE, stderr=PIPE,
       stdin=DEVNULL, text=True
   )
   ```
   - Isolated process group (cannot be killed by client)
   - Silent execution (no window popup)
   - Text mode output (string, not bytes)

2. **Process Spawning - Linux**
   ```python
   subprocess.Popen(
       ['/bin/bash', '-c', command],
       start_new_session=True,
       stdout=PIPE, stderr=PIPE,
       stdin=DEVNULL, text=True
   )
   ```
   - New session (equivalent to Windows process group)
   - Complete isolation from parent
   - Standard output capture

3. **Status Tracking**
   ```python
   return {
       'status': 'success|failed|timeout|error',
       'output': command_output_string,
       'pid': process_id,
       'exit_code': exit_code_or_none,
       'command': original_command
   }
   ```
   - Comprehensive result metadata
   - PID for tracking
   - Exit code for status
   - Full output capture

4. **Timeout & Cleanup**
   - 30-second timeout per command
   - Automatic process termination on timeout
   - Graceful process group killing (taskkill /T /F on Windows)
   - Active commands cleaned on client disconnect

**New Methods Added to client.py:**
- `get_formatted_time()` - Consistent logging timestamp format
- `execute_command_isolated(command)` - Core isolated execution logic

**Updated Methods in client.py:**
- `execute_command()` - Wrapper with thread executor
- `command_processor()` - Enhanced with status extraction & formatting
- `handle_commands()` - Enhanced logging for command reception
- `connect()` - Added cleanup of active commands on disconnect

#### 📊 Command Execution Scenarios

| Scenario | Behavior |
|----------|----------|
| Normal command | Spawn subprocess, wait, return success/output |
| Multiple commands | Execute concurrently, return results separately |
| Long-running command | Timeout at 30s, kill process, return timeout status |
| Invalid command | Capture error, return failed status with error message |
| Command crash | Capture exit code, return failed status |
| Client disconnect | Kill all active commands, cleanup |

#### 📋 Logging Format

**Consistent timestamp format:**
```
[DayName:HH:MM:SS] [SECTION] Message
```

**Logging sections:**
- `[HANDLER]` - Command message reception
- `[PROCESSOR]` - Command queue processing
- `[COMMAND]` - Command execution & subprocess management
- `[CLIENT]` - Connection events

**Example output:**
```
[Monday:14:32:20] [HANDLER] Received command: ipconfig
[Monday:14:32:20] [HANDLER] Command queued for processing
[Monday:14:32:20] [PROCESSOR] Processing command: ipconfig
[Monday:14:32:20] [COMMAND] Launching: ipconfig
[Monday:14:32:20] [COMMAND] Process spawned (PID: 5432)
[Monday:14:32:21] [COMMAND] PID 5432 completed (exit code: 0)
[Monday:14:32:21] [PROCESSOR] Command completed (Status: success, PID: 5432)
```

#### 🔐 Security & Isolation

- **Process Group Isolation** - Commands cannot affect client process
- **Failure Isolation** - Command crash doesn't crash client
- **Resource Isolation** - Commands can't block client operations
- **Timeout Protection** - Runaway commands killed at 30s
- **Output Isolation** - No context mixing between commands
- **Cleanup on Disconnect** - No orphaned processes left behind

#### 📄 Documentation

- `COMMAND_EXECUTION.md` - Complete technical documentation for isolated command execution
  - Architecture details
  - Implementation breakdown
  - Configuration options
  - Testing procedures
  - Troubleshooting guide

---



### ✨ Core Features

**1. RDP Client (client.py)**
- WebSocket connection to RDP server
- Screenshot capture & transmission (quality 40, JPEG)
- Command execution (Windows & Linux support)
- File download with chunked transfer (64KB chunks)
- Auto-reconnection with exponential backoff
- Screenshot interval: 200ms

**2. RDP Server (server.py)**
- Dual-port WebSocket server
  - Port 3500: Client connections
  - Port 3200: Controller connections
- Client-to-controller routing
- File request handling with caching
- Concurrent client/controller management
- Timestamp logging (DayName:HH:MM:SS format)

**3. RDP Controller (ctrl.py)**
- CLI Mode: Menu-based interface
- GUI Mode: Tkinter-based visualization
  - Client listbox selection
  - Real-time screenshot display
  - Command execution with output
  - File download feature
- Heartbeat mechanism (30s interval, 10s timeout)
- Connection resilience with exponential backoff
- Dual mode operation (CLI ↔ GUI)

**4. Auto-Updater (updater.py)**
- Multi-source fallback mechanism
  - CDN fallback: jsdelivr → GitHub → GitCDN
  - Automatic retry (2x per URL)
- SHA256 hash validation
- Atomic file replacement
- Fallback to local client if download fails
- Background process launch
- Network timeout: 15 seconds

### 📊 System Specifications

**Communication:**
- Protocol: WebSocket (ws://)
- Encoding: JSON
- Screenshot Format: Base64-encoded JPEG
- File Transfer: Base64-encoded chunks

**Resource Management:**
- Screenshot quality: 40 (JPEG)
- Chunk size: 65KB
- Heartbeat interval: 30 seconds
- Command timeout: 30 seconds
- Reconnect jitter: 10%

**Reconnection Strategy:**
- Base delay: 2^n seconds (exponential)
- Max delay: 60 seconds
- Jitter: ±10%
- Indefinite retry until connection restored

**Screenshot Streaming:**
- Interval: 200ms (5 FPS)
- Resolution: Up to 1280x720
- Format: JPEG with quality 40
- Optimization: Enabled

---

## [1.0.0] - 2026-04-01

### Initial Release

**Base Architecture:**
- WebSocket-based RDP system
- Client-server-controller model
- Real-time screenshot streaming
- Command execution capability
- Basic file transfer support

---

## 📌 Version Roadmap

### Planned for v2.2.0
- [ ] Database logging for session history
- [ ] Multi-factor authentication
- [ ] Encrypted WebSocket (WSS://)
- [ ] Advanced file manager
- [ ] System metrics monitoring

### Planned for v2.3.0
- [ ] Web-based controller interface
- [ ] Session recording capability
- [ ] Performance optimization
- [ ] Detailed audit logging

---

## 🔄 Compatibility

| Component | OS Support | Status | Notes |
|-----------|-----------|--------|-------|
| client.py | Windows, Linux | ✅ Stable | Isolated command execution |
| server.py | Windows, Linux | ✅ Stable | - |
| ctrl.py | Windows, Linux | ✅ Stable | - |
| updater.py | Windows, Linux | ✅ Stable | - |
| watchdog.py | Windows, Linux | ✅ New | Auto-restart mechanism |

---

## 📚 File Structure

```
RDPy/
├── client.py              # RDP Client with isolated command execution [UPDATED]
├── server.py              # RDP Server
├── ctrl.py                # RDP Controller (CLI/GUI)
├── updater.py             # Auto-updater with fallback
├── watchdog.py            # Process watchdog [NEW]
├── logs/                  # Logging directory
│   └── watchdog.log       # Watchdog monitoring log [NEW]
├── CHANGELOG.md           # This file [NEW]
└── COMMAND_EXECUTION.md   # Command execution documentation [NEW]
```

---

## 🎓 Notes

- All components designed for auto-recovery and resilience
- Comprehensive logging for debugging and audit trails
- Modular design for easy extension
- Production-ready with error handling
- Graceful degradation on failures
- Commands execute in isolated processes (separate from client)
- Multiple concurrent command execution supported
- Cross-platform process management (Windows & Linux)

---

**Last Updated:** 2026-04-06
**Version:** 2.1.0
**Status:** Stable with Watchdog Integration + Isolated Command Execution ✅
