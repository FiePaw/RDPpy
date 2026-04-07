# CHANGELOG - RDPyV2

## Version 2.1.0 - April 7, 2026

### 🎯 Major Update: Input Injection System Upgrade (PostMessage → SendInput API)

#### Overview
Migrated from Windows PostMessage API to SendInput API for more reliable and accurate system-level input injection. This eliminates window focus requirements and provides better compatibility across different applications.

---

### 📝 Changes by File

#### **client.py**
- **Removed PostMessage-based input injection:**
  - Deleted `_Post_MessageW`, `_WindowFromPoint`, `_ChildWindowFromPointEx`, `_GetSystemMetrics` references
  - Removed `WM_*` message constants (WM_MOUSEMOVE, WM_LBUTTONDOWN, etc.)
  - Removed `_make_lparam()`, `_get_hwnd_at()`, `_post_mouse()`, `_post_key()`, `_post_char()` functions
  - Removed old `_get_focused_hwnd()` complex GUITHREADINFO logic

- **Added SendInput API structures and constants:**
  - New constants: `INPUT_MOUSE`, `INPUT_KEYBOARD`, `MOUSEEVENTF_*`, `KEYEVENTF_*`
  - New ctypes structures: `MOUSEINPUT`, `KEYBDINPUT`, `INPUT`, `INPUTSTRUCT`
  - Added `_SendInput` API reference for system-level input injection

- **Added helper functions:**
  - `_get_screen_dimensions()` - Retrieves primary monitor resolution (fallback to GetSystemMetrics)
  - `_normalize_coords(x, y)` - Converts pixel coordinates to SendInput normalized range (0-65535)
  - `_send_input_mouse(action, x, y, data)` - Injects mouse events via SendInput API with coordinate normalization
  - `_send_input_keyboard(vk, is_down)` - Injects keyboard events via SendInput API
  - `_send_input_char(ch)` - Injects Unicode characters via SendInput API with KEYEVENTF_UNICODE flag

- **Updated `handle_mouse_event()` method:**
  - Now uses `_send_input_mouse()` instead of `_post_mouse()`
  - Removed window handle detection overhead
  - System-level injection works regardless of window focus or foreground state
  - Supports: move, mousedown, mouseup, click, double_click, scroll

- **Updated `handle_keyboard_event()` method:**
  - Now uses `_send_input_keyboard()` and `_send_input_char()` instead of `_post_key()` and `_post_char()`
  - Simplified hotkey handling with proper modifier key sequencing
  - Unicode text input via `_send_input_char()` for better character support
  - Removed window focus requirement

- **Simplified `_get_focused_hwnd()` method:**
  - Now only returns `_GetForegroundWindow()` since SendInput doesn't require complex focus detection
  - Kept for future compatibility but no longer used in main input injection

- **Fixed ULONG_PTR compatibility issue:**
  - Replaced `wintypes.ULONG_PTR` (not available in all Python versions) with `ctypes.c_ulonglong`
  - Ensures compatibility across Python versions and Windows configurations

---

### ✅ Benefits of SendInput API

| Aspect | PostMessage | SendInput |
|--------|------------|----------|
| **Injection Level** | Window-level (requires HWND) | System-level (global) |
| **Window Focus Required** | Often required | ❌ Not required |
| **Reliability** | Inconsistent | ✅ Consistent |
| **Application Compatibility** | Limited | ✅ Works with most apps |
| **Cursor Detection** | More detectable | ✅ Harder to detect |
| **Coordinate Precision** | Limited | ✅ 0-65535 range (highly precise) |

---

### 🔧 Technical Details

#### Coordinate Normalization
SendInput uses virtual desktop coordinates (0-65535) instead of pixel coordinates:
```python
norm_x = (pixel_x / screen_width) * 65535
norm_y = (pixel_y / screen_height) * 65535
```

#### Mouse Event Types
- `MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE` - Move with absolute positioning (normalized coords)
- `MOUSEEVENTF_LEFTDOWN/UP`, `MOUSEEVENTF_RIGHTDOWN/UP` - Button events
- `MOUSEEVENTF_WHEEL` - Scroll wheel with mouseData delta

#### Keyboard Event Types
- `KEYEVENTF_KEYDOWN/KEYUP` - Virtual key events
- `KEYEVENTF_UNICODE` - Unicode character input (typewrite)

---

## Version 2.0.0 - April 6, 2026

### 🎯 Major Feature: Mouse & Keyboard Control Synchronization

#### Overview
Implemented accurate mouse and keyboard control with proper coordinate synchronization between the controller (ctrl.py) and client (client.py). Fixed coordinate mapping issues caused by double-scaling of screenshots.

---

### 📝 Changes by File

#### **client.py**
- **Modified `capture_screenshot()` method:**
  - Now returns a dictionary containing `{'image': ..., 'actual_width': W, 'actual_height': H}` instead of just the image string
  - Captures and stores the ACTUAL client screen resolution (before thumbnail)
  - Enables accurate coordinate mapping on the controller side

- **Modified `send_screenshot_loop()` method:**
  - Updated to handle new dict format from `capture_screenshot()`
  - Now sends `actual_width` and `actual_height` metadata alongside screenshot
  - Format: `{'type': 'screenshot', 'image': ..., 'actual_width': W, 'actual_height': H}`

- **Enhanced `handle_mouse_event()` method:**
  - Added input validation: rejects negative coordinates (x < 0 or y < 0)
  - Added coordinate clamping: ensures x, y don't exceed screen bounds before normalization
  - Improved precision: uses floating-point math (65535.0) instead of integer division
  - Better error handling with bounds checking

#### **server.py**
- **Modified `handle_client()` screenshot forwarding:**
  - Now extracts and forwards `actual_width` and `actual_height` from client message
  - Updated message format includes metadata: `{'type': 'screenshot', 'client_id': ..., 'image': ..., 'actual_width': W, 'actual_height': H}`
  - Maintains backward compatibility

#### **ctrl.py**
- **Modified `__init__()` method:**
  - Added `_actual_client_size = (1, 1)` - stores ACTUAL client screen resolution (initialized to 1x1 to prevent division by zero)
  - Added `_screenshot_received = False` - flag to track if actual resolution metadata has been received
  - Changed `_last_img_offset` initialization from float tuple to int tuple for consistency

- **Modified `_canvas_to_client_coords()` method:**
  - Added early return check: verifies `_screenshot_received` flag before performing coordinate transformation
  - Uses `_actual_client_size` (actual screen resolution) instead of `_last_client_size` (scaled image size)
  - Improved validation: returns (0, 0) if screenshot not received or invalid dimensions
  - Better clamping: ensures result coordinates are within valid screen bounds

- **Enhanced `update_screenshot()` method:**
  - Now accepts additional parameters: `actual_width` and `actual_height`
  - Sets `_screenshot_received = True` when actual resolution metadata is received
  - Fallback behavior: uses decoded image size if metadata is unavailable
  - Explicit canvas readiness check: skips frame rendering if canvas dimensions <= 1
  - More robust error handling for image processing

- **Modified `handle_messages()` method:**
  - Updated screenshot handler to extract `actual_width` and `actual_height` from server message
  - Passes metadata to `update_screenshot()` method

---

### 🔄 Coordinate Transformation Pipeline

**Previous (Broken) Flow:**
```
Canvas Coords → Canvas Offset → Scaled Image Coords → Scaled Size Mapping → Wrong Client Coords
```

**Current (Fixed) Flow:**
```
Canvas (event.x, event.y)
  ↓ Subtract canvas offset (x_off, y_off)
Displayed Image coords
  ↓ Scale from displayed size to actual client size
  ↓ Using ratio: (actual_w / img_w, actual_h / img_h)
Actual Client Screen Coords (0 to actual_w-1, 0 to actual_h-1)
  ↓ Clamp to bounds
Final Coordinates → Client SendInput (normalized to 0-65535)
```

---

### 🐛 Bug Fixes

1. **Double-Scaling Issue**
   - Client scaled screenshot to 1280x720 for transmission
   - Controller then scaled it again to fit canvas
   - Coordinate mapping was using wrong scale ratios → FIXED
   - Now uses actual screen resolution for accurate mapping

2. **Race Condition**
   - Mouse events were processed before screenshot received
   - Added `_screenshot_received` flag to ensure events are only processed when actual resolution is known → FIXED

3. **Precision Loss**
   - Integer division caused coordinate precision loss
   - Switched to floating-point normalization (65535.0) → FIXED

4. **Coordinate Validation**
   - Negative or out-of-bounds coordinates weren't handled
   - Added comprehensive input validation and bounds checking → FIXED

---

### ✨ Implementation Details

#### Metadata Flow
```
Client captures screenshot (1920x1080) → Scale thumbnail (1280x720)
→ Send with metadata: actual_width=1920, actual_height=1080
↓
Server forwards metadata unchanged
↓
Controller receives metadata
→ Stores actual_width=1920, actual_height=1080 in _actual_client_size
→ Uses for all coordinate transformations
```

#### Key Variables
- `_actual_client_size`: (actual_width, actual_height) from client ← CRITICAL
- `_last_img_offset`: (x_offset, y_offset, display_width, display_height) from canvas centering
- `_screenshot_received`: Flag to block events before setup complete
- `_last_client_size`: (decoded_image_width, decoded_image_height) for reference only

---

### 🧹 Cleanup

- **Removed debug logging:**
  - Removed `[DEBUG] Canvas() → Client()` logs from ctrl.py
  - Removed console output from client.py mouse event handling
  - Cleaned up timestamp logging on invalid coordinates
  - Console is now clean and maintenance-friendly

---

### 📋 Testing Checklist

- [x] Screenshot transmission includes metadata
- [x] Controller receives and stores actual resolution
- [x] Mouse move events map correctly
- [x] Mouse click events register at correct positions
- [x] Scroll operations function properly
- [x] Keyboard input works (unchanged but verified)
- [x] No coordinate overflow/underflow
- [x] Race condition handled with flag check
- [x] Canvas resizing handled gracefully

---

### 📦 Backward Compatibility

- ✅ All changes are backward compatible
- ✅ Server properly forwards metadata without breaking
- ✅ Fallback in `update_screenshot()` if metadata missing
- ✅ No breaking changes to API or message format

---

### 🚀 Future Improvements

- [ ] Add performance metrics for coordinate transformation latency
- [ ] Implement adaptive scaling for very high-resolution displays
- [ ] Add mouse acceleration/smoothing options
- [ ] Profile coordinate transformation on various screen sizes
- [ ] Consider prediction algorithm for mouse movement latency

---

### 📞 Maintenance Notes

**For maintaining this feature:**
1. Key synchronization point is `_actual_client_size` - must be set BEFORE any mouse events
2. `_screenshot_received` flag **must** be checked in `_canvas_to_client_coords()`
3. Never mix scale ratios - always use actual screen resolution, not image size
4. Canvas offset calculation **must** account for centering on canvas
5. Coordinate clamping is critical to prevent SendInput errors

**Debugging coordinates:**
If events misalign:
1. Check server logs for `actual_width`, `actual_height` in screenshots
2. Verify `_screenshot_received` is True in ctrl.py
3. Verify `_actual_client_size` matches client screen resolution
4. Check canvas dimensions vs displayed image dimensions
5. Verify offset calculation: `(canvas_size - image_size) // 2`

