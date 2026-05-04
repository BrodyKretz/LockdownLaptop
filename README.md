# LockdownLaptop

A macOS utility that locks your screen while keeping programs running — so you can step away from a long-running task without closing your laptop.

## The Problem

You need to leave your computer running (a training job, a download, a render) but don't want anyone walking by to see or touch your screen. Closing the lid stops the process. The built-in lock screen still lets someone keyboard-mash past the screensaver or wake the display. LockdownLaptop freezes the session entirely until you unlock it.

## Features

- **System-wide keyboard suppression** — all keys blocked during lock; printable characters, backspace, and Enter are manually re-routed to the password field
- **Mouse confinement** — cursor is clamped to the unlock card; clicks outside the card are suppressed at the OS level
- **Touch ID / system password unlock** — uses macOS `LocalAuthentication` framework so you never need to create a separate password
- **Custom password mode** — set your own password instead
- **Countdown timer** — auto-unlocks when time expires
- **Clear screen mode** — captures a screenshot of your desktop before locking; you can see what was on screen but can't interact with it
- **Blur / blackout mode** — solid dark overlay; nothing is visible
- **Snitch Cam** — optionally snaps a webcam photo on each failed password attempt and shows you a gallery when you unlock

## How It Works

### Keyboard Lock — Quartz CGEventTap

Rather than using `pynput` (which crashes on macOS 15 due to `TSMGetInputSourceProperty` being called off the main thread), LockdownLaptop uses a raw `CGEventTap` via PyObjC:

```python
self._tap = Quartz.CGEventTapCreate(
    Quartz.kCGSessionEventTap,
    Quartz.kCGHeadInsertEventTap,
    Quartz.kCGEventTapOptionDefault,   # active tap — can suppress/modify
    mask,
    callback,
    None,
)
```

The tap runs in a background thread with its own `CFRunLoop`. The callback intercepts every `kCGEventKeyDown`, extracts the keycode and modifier flags, and either suppresses the event (Cmd/Ctrl combos, function keys) or manually routes printable characters to the password field via `tkinter.after(0, ...)`.

### Mouse Confinement — Second CGEventTap

A separate tap handles mouse events. For `kCGEventMouseMoved` and drag events, the cursor position is clamped to the card boundary:

```python
nx = max(x1, min(x2, pos.x))
ny = max(y1, min(y2, pos.y))
Quartz.CGEventSetLocation(event, Quartz.CGPoint(nx, ny))
Quartz.CGWarpMouseCursorPosition(Quartz.CGPoint(nx, ny))
```

Click and scroll events that land outside the card return `None` from the callback, which drops them before they reach any application.

### Touch ID — LocalAuthentication Framework

Authentication is handled by `LAPolicyDeviceOwnerAuthentication`, which accepts both Touch ID and the system login password as a fallback — no custom credential storage needed:

```python
ctx = LAContext.new()
ctx.evaluatePolicy_localizedReason_reply_(
    LAPolicyDeviceOwnerAuthentication,
    "Unlock LockdownLaptop",
    reply_callback,
)
```

The callback fires on a background thread and dispatches `_unlock()` back to the main thread via `tkinter.after(0, ...)`.

## Setup

**Requirements:** macOS, Python 3.10+

```bash
pip install -r requirements.txt
python3 lockdown.py
```

On first run, macOS will prompt for **Accessibility (Input Monitoring)** permission — required for the CGEventTap to suppress system-wide events. Grant it in **System Settings → Privacy & Security → Accessibility**, then relaunch.

### Dependencies

| Package | Purpose |
|---|---|
| `pyobjc-framework-Quartz` | CGEventTap for keyboard/mouse capture |
| `pyobjc-framework-LocalAuthentication` | Touch ID / system password auth |
| `Pillow` + `mss` | Screenshot capture for clear-screen mode |
| `opencv-python` | Webcam capture for Snitch Cam |

## Usage

1. Run `python3 lockdown.py` — a small "Lock Computer Now" button appears
2. Click it to open the lock settings:
   - Set a duration (auto-unlocks when time expires)
   - Choose unlock method: Touch ID / system password, or custom password
   - Choose screen mode: Clear (see your desktop) or Blur (solid dark)
   - Optionally enable Snitch Cam
3. Click **Lock Now**
4. To unlock: use Touch ID, enter your password, or wait for the timer
5. Emergency exit: power off the machine

## Permissions Required

| Permission | Why |
|---|---|
| Accessibility / Input Monitoring | CGEventTap needs this to intercept and suppress system-wide keyboard and mouse events |
| Camera | Snitch Cam only — not requested if the feature is disabled |

## Architecture

```
lockdown.py
├── QuartzKeyCapture      — CGEventTap thread for keyboard suppression + routing
├── QuartzMouseCapture    — CGEventTap thread for cursor confinement
├── LockdownApp
│   ├── _enter_lock()     — builds fullscreen overlay, starts both taps
│   ├── _system_auth()    — LocalAuthentication call in background thread
│   ├── _try_unlock()     — password comparison + snitch cam trigger
│   ├── _start_countdown()— background thread, fires _unlock() at zero
│   └── _show_snitch_gallery() — PIL image viewer for captured photos
└── snitch_snap()         — OpenCV webcam capture → snitch_photos/
```
