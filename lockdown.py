#!/usr/bin/env python3
"""
LockdownLaptop — lock your screen while keeping programs running.
Install deps: pip install -r requirements.txt
"""

import tkinter as tk
from tkinter import ttk
import threading
import time
import os
import datetime

# ── optional imports ──────────────────────────────────────────────────────────
try:
    from PIL import Image, ImageFilter, ImageTk
    import mss
    PIL_OK = True
except ImportError:
    PIL_OK = False
    print("[warn] Pillow/mss not found — blur mode unavailable")
    print("       Run: pip install Pillow mss")

try:
    import Quartz
    QUARTZ = True
except ImportError:
    QUARTZ = False
    print("[warn] pyobjc-framework-Quartz not found — keyboard/mouse lock disabled")
    print("       Run: pip install pyobjc-framework-Quartz")

try:
    from LocalAuthentication import LAContext, LAPolicyDeviceOwnerAuthentication
    LA = True
except ImportError:
    LA = False
    print("[warn] LocalAuthentication not available — fingerprint/system-password auth disabled")
    print("       Run: pip install pyobjc-framework-LocalAuthentication")

try:
    import cv2
    CAMERA = True
except ImportError:
    CAMERA = False
    print("[warn] opencv-python not found — snitch cam disabled")
    print("       Run: pip install opencv-python")


# ── Palette ───────────────────────────────────────────────────────────────────
DARK   = "#0f172a"
PANEL  = "#1e293b"
ACCENT = "#3b82f6"
GREEN  = "#22c55e"
RED    = "#ef4444"
AMBER  = "#f59e0b"
MUTED  = "#64748b"
WHITE  = "#f1f5f9"


def fmt_time(seconds: int) -> str:
    h, r = divmod(max(0, seconds), 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _center(win, w, h):
    win.update_idletasks()
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    win.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")


# ── Quartz keyboard capture ───────────────────────────────────────────────────
# US-QWERTY keycode → character (unshifted / shifted)
_KC = {
    0:('a','A'),1:('s','S'),2:('d','D'),3:('f','F'),4:('h','H'),5:('g','G'),
    6:('z','Z'),7:('x','X'),8:('c','C'),9:('v','V'),11:('b','B'),
    12:('q','Q'),13:('w','W'),14:('e','E'),15:('r','R'),16:('y','Y'),17:('t','T'),
    18:('1','!'),19:('2','@'),20:('3','#'),21:('4','$'),22:('6','^'),23:('5','%'),
    24:('=','+'),25:('9','('),26:('7','&'),27:('-','_'),28:('8','*'),29:('0',')'),
    30:(']','}'),31:('o','O'),32:('u','U'),33:('[','{'),34:('i','I'),35:('p','P'),
    37:('l','L'),38:('j','J'),39:("'",'"'),40:('k','K'),41:(';',':'),
    42:('\\','|'),43:(',','<'),44:('/','?'),45:('n','N'),46:('m','M'),47:('.', '>'),
    49:(' ',' '),50:('`','~'),
}
_KC_BACKSPACE = 51
_KC_RETURN    = 36
_KC_NUMPAD_ENTER = 76


class QuartzKeyCapture:
    """System-wide keyboard event tap using Quartz CGEventTap.

    Suppresses all key events and manually routes printable chars,
    backspace, and enter to the provided callbacks — no pynput/HIToolbox needed.
    """

    def __init__(self, on_char, on_backspace, on_enter):
        self._on_char      = on_char
        self._on_backspace = on_backspace
        self._on_enter     = on_enter
        self._tap          = None
        self._run_loop     = None
        self._thread       = None
        self.active        = False

    def start(self):
        if not QUARTZ:
            return
        self.active = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self.active = False
        if self._tap:
            try:
                Quartz.CGEventTapEnable(self._tap, False)
            except Exception:
                pass
        if self._run_loop:
            try:
                Quartz.CFRunLoopStop(self._run_loop)
            except Exception:
                pass

    def _run(self):
        # Mask: key-down, key-up, modifier changes — we suppress them all
        mask = (
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown) |
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp) |
            Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged)
        )

        capture = self

        def _cb(proxy, event_type, event, refcon):
            if not capture.active:
                return event  # pass through when not locked

            # Suppress key-up and modifier events unconditionally
            if event_type != Quartz.kCGEventKeyDown:
                return None

            keycode = int(Quartz.CGEventGetIntegerValueField(
                event, Quartz.kCGKeyboardEventKeycode))
            flags = int(Quartz.CGEventGetFlags(event))
            cmd  = bool(flags & Quartz.kCGEventFlagMaskCommand)
            ctrl = bool(flags & Quartz.kCGEventFlagMaskControl)

            # Always block Cmd/Ctrl combos (Cmd-Q, Cmd-Tab, etc.)
            if cmd or ctrl:
                return None

            if keycode in (_KC_RETURN, _KC_NUMPAD_ENTER):
                capture._on_enter()
                return None

            if keycode == _KC_BACKSPACE:
                capture._on_backspace()
                return None

            pair = _KC.get(keycode)
            if pair:
                shift = bool(flags & Quartz.kCGEventFlagMaskShift)
                caps  = bool(flags & Quartz.kCGEventFlagMaskAlphaShift)
                lo, hi = pair
                if lo.isalpha():
                    use_upper = shift ^ caps
                    ch = hi if use_upper else lo
                else:
                    ch = hi if shift else lo
                capture._on_char(ch)

            return None  # suppress everything

        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault,   # can suppress events
            mask,
            _cb,
            None,
        )

        if not self._tap:
            print("[warn] CGEventTap creation failed.")
            print("       Go to System Settings → Privacy & Security → Accessibility")
            print("       and grant permission to Terminal (or your Python executable).")
            return

        source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        self._run_loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(
            self._run_loop, source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self._tap, True)
        Quartz.CFRunLoopRun()  # blocks until stop() calls CFRunLoopStop


class QuartzMouseCapture:
    """Confines the mouse cursor and clicks to a rectangular card region.

    Movement outside the card is clamped to the nearest edge; clicks outside
    are suppressed entirely. Uses a separate CGEventTap so it doesn't interfere
    with the keyboard tap.
    """

    def __init__(self, bounds):
        # bounds: (x1, y1, x2, y2) in screen points, top-left origin
        self._x1, self._y1, self._x2, self._y2 = bounds
        self._tap       = None
        self._run_loop  = None
        self._thread    = None
        self.active     = False

    def start(self):
        if not QUARTZ:
            return
        self.active = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self.active = False
        if self._tap:
            try:
                Quartz.CGEventTapEnable(self._tap, False)
            except Exception:
                pass
        if self._run_loop:
            try:
                Quartz.CFRunLoopStop(self._run_loop)
            except Exception:
                pass

    def _run(self):
        x1, y1, x2, y2 = self._x1, self._y1, self._x2, self._y2
        capture = self

        # Events where we suppress if cursor is outside the card
        CLICK_EVENTS = frozenset([
            Quartz.kCGEventLeftMouseDown,
            Quartz.kCGEventRightMouseDown,
            Quartz.kCGEventOtherMouseDown,
            Quartz.kCGEventScrollWheel,
        ])
        # Events where we clamp the cursor position to card bounds
        MOVE_EVENTS = frozenset([
            Quartz.kCGEventMouseMoved,
            Quartz.kCGEventLeftMouseDragged,
            Quartz.kCGEventRightMouseDragged,
            Quartz.kCGEventOtherMouseDragged,
        ])

        def _cb(proxy, event_type, event, refcon):
            if not capture.active:
                return event

            pos = Quartz.CGEventGetLocation(event)
            x, y = pos.x, pos.y
            inside = (x1 <= x <= x2 and y1 <= y <= y2)

            if event_type in CLICK_EVENTS:
                return event if inside else None  # block outside clicks

            if event_type in MOVE_EVENTS:
                nx = max(x1, min(x2, x))
                ny = max(y1, min(y2, y))
                if nx != x or ny != y:
                    # Modify the event location and warp cursor to clamped pos
                    try:
                        new_pt = Quartz.CGPoint(nx, ny)
                    except Exception:
                        new_pt = (nx, ny)
                    Quartz.CGEventSetLocation(event, new_pt)
                    Quartz.CGWarpMouseCursorPosition(new_pt)
                return event  # always pass through (possibly with modified pos)

            return event

        mask = 0
        for et in [
            Quartz.kCGEventMouseMoved,
            Quartz.kCGEventLeftMouseDown,  Quartz.kCGEventLeftMouseUp,
            Quartz.kCGEventLeftMouseDragged,
            Quartz.kCGEventRightMouseDown, Quartz.kCGEventRightMouseUp,
            Quartz.kCGEventRightMouseDragged,
            Quartz.kCGEventOtherMouseDown, Quartz.kCGEventOtherMouseUp,
            Quartz.kCGEventOtherMouseDragged,
            Quartz.kCGEventScrollWheel,
        ]:
            mask |= Quartz.CGEventMaskBit(et)

        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault,
            mask,
            _cb,
            None,
        )

        if not self._tap:
            print("[warn] Mouse CGEventTap failed — check Accessibility permissions")
            return

        source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        self._run_loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(
            self._run_loop, source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self._tap, True)
        Quartz.CFRunLoopRun()


# ── Snitch cam ────────────────────────────────────────────────────────────────
SNITCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snitch_photos")


def snitch_snap() -> str | None:
    if not CAMERA:
        return None
    try:
        os.makedirs(SNITCH_DIR, exist_ok=True)
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return None
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        for _ in range(3):   # warm-up frames
            cap.read()
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return None
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(SNITCH_DIR, f"attempt_{stamp}.jpg")
        cv2.imwrite(path, frame)
        return path
    except Exception as e:
        print(f"[snitch] photo failed: {e}")
        return None


# ── Main App ──────────────────────────────────────────────────────────────────

class LockdownApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("LockdownLaptop")
        self.root.geometry("260x70")
        self.root.resizable(False, False)
        self.root.configure(bg=DARK)
        self.root.attributes("-topmost", True)
        _center(self.root, 260, 70)

        # Runtime state
        self.locked          = False
        self.lock_win        = None
        self.key_capture     = None
        self.mouse_capture   = None
        self.timer_secs      = 0
        self.custom_pw       = None
        self.blur_mode       = False
        self.snitch_enabled  = False
        self._bg_photo       = None
        self._auth_busy      = False
        self._snitch_paths   = []

        self._build_main()

    # ── Main window ───────────────────────────────────────────────────────────

    def _build_main(self):
        btn = tk.Button(
            self.root, text="🔒  Lock Computer Now",
            bg=DARK, fg=WHITE, activebackground=PANEL, activeforeground=WHITE,
            relief="flat", cursor="hand2",
            font=("Helvetica Neue", 15, "bold"),
            command=self._show_dialog, pady=18,
        )
        btn.pack(fill="both", expand=True)

    # ── Lock-settings dialog ──────────────────────────────────────────────────

    def _show_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Lock Settings")
        dlg.resizable(False, False)
        dlg.configure(bg=DARK)
        dlg.attributes("-topmost", True)
        dlg.grab_set()
        _center(dlg, 400, 430)

        def section(text):
            tk.Label(dlg, text=text, bg=DARK, fg=WHITE,
                     font=("Helvetica Neue", 12, "bold")).pack(
                         anchor="w", padx=20, pady=(14, 4))

        def radio(parent, text, var, val):
            tk.Radiobutton(parent, text=text, variable=var, value=val,
                           bg=DARK, fg=WHITE, selectcolor=PANEL,
                           activebackground=DARK, activeforeground=WHITE).pack(anchor="w")

        # ── Duration ─────────────────────────────────────────────────────────
        section("Duration")
        tframe = tk.Frame(dlg, bg=DARK)
        tframe.pack(anchor="w", padx=20)
        h_var = tk.StringVar(value="0")
        m_var = tk.StringVar(value="30")
        es = dict(bg=PANEL, fg=WHITE, insertbackground=WHITE, relief="flat", width=4)
        tk.Entry(tframe, textvariable=h_var, **es).pack(side="left")
        tk.Label(tframe, text=" h  ", bg=DARK, fg=MUTED).pack(side="left")
        tk.Entry(tframe, textvariable=m_var, **es).pack(side="left")
        tk.Label(tframe, text=" m", bg=DARK, fg=MUTED).pack(side="left")

        # ── Auth ─────────────────────────────────────────────────────────────
        section("Unlock Method")
        auth_var = tk.StringVar(value="system")
        arb = tk.Frame(dlg, bg=DARK)
        arb.pack(anchor="w", padx=20)
        fp_label = "Fingerprint / system password" + ("" if LA else "  (unavailable — install pyobjc)")
        radio(arb, fp_label, auth_var, "system")
        radio(arb, "Custom password", auth_var, "custom")

        pw_frame = tk.Frame(dlg, bg=DARK)
        pw_frame.pack(anchor="w", padx=20, pady=(4, 0))
        tk.Label(pw_frame, text="Password:", bg=DARK, fg=MUTED).pack(side="left")
        pw_var = tk.StringVar()
        pw_entry = tk.Entry(pw_frame, textvariable=pw_var, show="•",
                            bg=PANEL, fg=WHITE, insertbackground=WHITE,
                            relief="flat", width=18)
        pw_entry.pack(side="left", padx=(6, 0))

        def toggle_pw(*_):
            if auth_var.get() == "custom":
                pw_frame.pack(anchor="w", padx=20, pady=(4, 0))
                pw_entry.focus_set()
            else:
                pw_frame.pack_forget()
        auth_var.trace_add("write", toggle_pw)
        pw_frame.pack_forget()

        # ── Screen mode ───────────────────────────────────────────────────────
        section("Screen Mode")
        mode_var = tk.StringVar(value="clear")
        mf = tk.Frame(dlg, bg=DARK)
        mf.pack(anchor="w", padx=20)
        radio(mf, "Clear — screen stays visible", mode_var, "clear")
        radio(mf, "Blurred — screen hidden" + (
            "" if PIL_OK else "  (unavailable — install Pillow mss)"),
              mode_var, "blur")

        # ── Snitch cam ────────────────────────────────────────────────────────
        section("Snitch Cam")
        snitch_var = tk.BooleanVar(value=False)
        snitch_label = (
            "📸 Snap photo on wrong password" +
            ("" if CAMERA else "  (unavailable — install opencv-python)")
        )
        tk.Checkbutton(dlg, text=snitch_label, variable=snitch_var,
                       bg=DARK, fg=WHITE, selectcolor=PANEL,
                       activebackground=DARK, activeforeground=WHITE,
                       state="normal" if CAMERA else "disabled").pack(
                           anchor="w", padx=20)
        tk.Label(dlg,
                 text="  Photos saved to snitch_photos/ and shown when unlocked",
                 bg=DARK, fg=MUTED, font=("Helvetica Neue", 10)).pack(
                     anchor="w", padx=20)

        # ── Buttons ───────────────────────────────────────────────────────────
        self._err_lbl = tk.Label(dlg, text="", fg=RED, bg=DARK,
                                 font=("Helvetica Neue", 10))
        self._err_lbl.pack(pady=(10, 0))

        bf = tk.Frame(dlg, bg=DARK)
        bf.pack(fill="x", padx=20, pady=12)
        tk.Button(bf, text="Cancel", bg=PANEL, fg=WHITE, relief="flat",
                  command=dlg.destroy).pack(side="right", padx=(6, 0))
        tk.Button(
            bf, text="Lock Now", bg=ACCENT, fg=WHITE, relief="flat",
            font=("Helvetica Neue", 12, "bold"),
            command=lambda: self._validate_and_lock(
                dlg, h_var, m_var, auth_var, pw_var, mode_var, snitch_var),
        ).pack(side="right")

    def _validate_and_lock(self, dlg, h_var, m_var, auth_var, pw_var, mode_var, snitch_var):
        try:
            secs = int(h_var.get() or 0) * 3600 + int(m_var.get() or 0) * 60
        except ValueError:
            self._show_err("Enter valid numbers for duration.")
            return
        if secs <= 0:
            self._show_err("Duration must be greater than 0.")
            return

        use_system = auth_var.get() == "system"
        custom_pw  = pw_var.get() if not use_system else None
        if not use_system and not custom_pw:
            self._show_err("Enter a custom password.")
            return

        self.timer_secs     = secs
        self.custom_pw      = custom_pw
        self.blur_mode      = mode_var.get() == "blur"
        self.snitch_enabled = snitch_var.get()
        self._snitch_paths  = []

        dlg.destroy()
        self.root.after(180, self._enter_lock)

    def _show_err(self, msg):
        self._err_lbl.config(text=msg)
        self.root.after(4000, lambda: self._err_lbl.config(text=""))

    # ── Lock screen ───────────────────────────────────────────────────────────

    def _enter_lock(self):
        self.locked = True

        # Grab screenshot BEFORE hiding/creating windows so it shows the real desktop.
        # Clear mode → unblurred snapshot; blur mode → solid dark (nothing visible).
        self.root.withdraw()
        self.root.update()  # flush withdraw so screenshot excludes our window
        bg_image = self._grab_screenshot() if not self.blur_mode else None

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()

        win = tk.Toplevel()
        win.overrideredirect(True)
        win.geometry(f"{sw}x{sh}+0+0")
        win.configure(bg=DARK)  # solid dark fallback / blur-mode background
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", lambda: None)
        self.lock_win = win

        # Background — only shown in clear mode
        if bg_image and PIL_OK:
            bg_image = bg_image.resize((sw, sh), Image.LANCZOS)
            self._bg_photo = ImageTk.PhotoImage(bg_image)
            tk.Label(win, image=self._bg_photo, bd=0).place(
                x=0, y=0, relwidth=1, relheight=1)

        # Central card
        CW, CH = 440, 340
        cx, cy = (sw - CW) // 2, (sh - CH) // 2
        card = tk.Frame(win, bg=PANEL, bd=0)
        card.place(x=cx, y=cy, width=CW, height=CH)
        # Store card bounds (screen coords, top-left origin) for mouse confinement
        self._card_bounds = (cx, cy, cx + CW, cy + CH)

        tk.Label(card, text="🔒", font=("Helvetica Neue", 40), bg=PANEL, fg=WHITE).pack(pady=(26, 2))
        tk.Label(card, text="Computer Locked", font=("Helvetica Neue", 18, "bold"),
                 bg=PANEL, fg=WHITE).pack()

        self._timer_lbl = tk.Label(
            card, text=fmt_time(self.timer_secs),
            font=("Helvetica Neue", 28, "bold"), bg=PANEL, fg=GREEN)
        self._timer_lbl.pack(pady=(8, 14))

        if self.custom_pw is None:
            tk.Label(card, text="Use fingerprint or system password to unlock",
                     font=("Helvetica Neue", 11), bg=PANEL, fg=MUTED).pack()
            if LA:
                tk.Button(
                    card, text="🔑  Authenticate", bg=ACCENT, fg=WHITE,
                    relief="flat", font=("Helvetica Neue", 12, "bold"),
                    cursor="hand2",
                    command=lambda: threading.Thread(
                        target=self._system_auth, daemon=True).start(),
                ).pack(pady=(12, 4))
            else:
                tk.Label(card,
                         text="(LocalAuthentication unavailable — wait for timer)",
                         font=("Helvetica Neue", 10), bg=PANEL, fg=RED).pack(pady=8)
        else:
            tk.Label(card, text="Enter password to unlock:",
                     font=("Helvetica Neue", 11), bg=PANEL, fg=MUTED).pack()
            self._pw_var = tk.StringVar()
            self._pw_entry = tk.Entry(
                card, textvariable=self._pw_var, show="•",
                font=("Helvetica Neue", 14), width=22, justify="center",
                bg=DARK, fg=WHITE, insertbackground=WHITE, relief="flat", bd=6,
            )
            self._pw_entry.pack(pady=(6, 4))
            self._status_lbl = tk.Label(card, text="",
                                        font=("Helvetica Neue", 10), bg=PANEL, fg=RED)
            self._status_lbl.pack()

        win.bind("<Button-1>", lambda _: self._refocus())

        self._start_key_capture()
        self._start_mouse_capture()
        self._start_countdown()
        self._keep_focus()

        if self.custom_pw is None and LA:
            threading.Thread(target=self._system_auth, daemon=True).start()

    def _refocus(self):
        if self.lock_win and self.custom_pw is not None:
            try:
                self._pw_entry.focus_set()
            except Exception:
                pass

    def _grab_screenshot(self):
        """Capture the current screen with no modifications (clear mode)."""
        if not PIL_OK:
            return None
        try:
            with mss.mss() as sct:
                raw = sct.grab(sct.monitors[0])
                return Image.frombytes("RGB", raw.size, raw.rgb)
        except Exception as e:
            print(f"[warn] screenshot failed: {e}")
            return None

    # ── Authentication ────────────────────────────────────────────────────────

    def _system_auth(self):
        if not LA:
            return
        self._auth_busy = True
        ctx = LAContext.new()
        result = [False]
        done = threading.Event()

        def reply(success, error):
            result[0] = bool(success)
            done.set()

        ctx.evaluatePolicy_localizedReason_reply_(
            LAPolicyDeviceOwnerAuthentication,
            "Unlock LockdownLaptop",
            reply,
        )
        done.wait(timeout=60)
        self._auth_busy = False
        if result[0] and self.locked:
            self.lock_win.after(0, self._unlock)

    def _try_unlock(self):
        if self.custom_pw is None:
            return
        attempt = self._pw_var.get()
        if attempt == self.custom_pw:
            self._unlock()
        else:
            if self.snitch_enabled:
                threading.Thread(target=self._do_snitch, daemon=True).start()
            self._pw_var.set("")
            self._status_lbl.config(text="Wrong password — try again")
            if self.lock_win:
                self.lock_win.after(2000,
                    lambda: self._status_lbl.config(text="") if self.locked else None)

    def _do_snitch(self):
        path = snitch_snap()
        if path:
            self._snitch_paths.append(path)

    def _unlock(self):
        if not self.locked:
            return
        self.locked = False

        if self.key_capture:
            self.key_capture.stop()
            self.key_capture = None

        if self.mouse_capture:
            self.mouse_capture.stop()
            self.mouse_capture = None

        if self.lock_win:
            self.lock_win.destroy()
            self.lock_win = None

        self.root.deiconify()
        self.root.lift()
        self.root.after(200, self._maybe_show_snitch)

    def _maybe_show_snitch(self):
        paths = self._snitch_paths[:]
        if not paths:
            return
        if not PIL_OK:
            print(f"[snitch] {len(paths)} photo(s) saved to {SNITCH_DIR}")
            return
        self._show_snitch_gallery(paths)

    def _show_snitch_gallery(self, paths):
        g = tk.Toplevel(self.root)
        g.title(f"🕵️ Snitch Cam — {len(paths)} failed attempt(s)")
        g.configure(bg=DARK)
        g.attributes("-topmost", True)
        _center(g, 700, 520)

        tk.Label(g, text=f"🕵️  {len(paths)} failed unlock attempt(s) caught",
                 font=("Helvetica Neue", 14, "bold"), bg=DARK, fg=AMBER).pack(pady=(16, 4))
        tk.Label(g, text=f"Photos saved to: {SNITCH_DIR}",
                 font=("Helvetica Neue", 10), bg=DARK, fg=MUTED).pack(pady=(0, 10))

        canvas = tk.Canvas(g, bg=DARK, bd=0, highlightthickness=0)
        scrollbar = tk.Scrollbar(g, orient="horizontal", command=canvas.xview)
        canvas.configure(xscrollcommand=scrollbar.set)
        scrollbar.pack(side="bottom", fill="x")
        canvas.pack(fill="both", expand=True, padx=16, pady=8)

        strip = tk.Frame(canvas, bg=DARK)
        canvas.create_window((0, 0), window=strip, anchor="nw")

        self._snitch_photos = []
        for path in paths:
            try:
                img = Image.open(path)
                img.thumbnail((200, 150), Image.LANCZOS)
                ph = ImageTk.PhotoImage(img)
                self._snitch_photos.append(ph)
                frame = tk.Frame(strip, bg=PANEL, bd=2, relief="flat")
                frame.pack(side="left", padx=8, pady=8)
                tk.Label(frame, image=ph, bg=PANEL).pack()
                tk.Label(frame, text=os.path.basename(path), bg=PANEL, fg=MUTED,
                         font=("Helvetica Neue", 8)).pack(pady=(2, 4))
            except Exception as e:
                print(f"[snitch] could not load {path}: {e}")

        strip.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))
        tk.Button(g, text="Dismiss", bg=PANEL, fg=WHITE, relief="flat",
                  command=g.destroy).pack(pady=12)

    # ── Keyboard capture (Quartz CGEventTap — no HIToolbox, no pynput) ────────

    def _start_key_capture(self):
        if not QUARTZ:
            return

        win = self.lock_win

        def on_char(ch):
            if self.locked and win and self.custom_pw is not None:
                win.after(0, lambda: self._pw_var.set(self._pw_var.get() + ch))

        def on_backspace():
            if self.locked and win and self.custom_pw is not None:
                win.after(0, lambda: self._pw_var.set(self._pw_var.get()[:-1]))

        def on_enter():
            if self.locked and win:
                if self.custom_pw is not None:
                    win.after(0, self._try_unlock)
                else:
                    # In system-auth mode, Enter triggers fingerprint prompt
                    threading.Thread(target=self._system_auth, daemon=True).start()

        self.key_capture = QuartzKeyCapture(on_char, on_backspace, on_enter)
        self.key_capture.start()

    # ── Mouse confinement ─────────────────────────────────────────────────────

    def _start_mouse_capture(self):
        if not QUARTZ:
            return
        self.mouse_capture = QuartzMouseCapture(self._card_bounds)
        self.mouse_capture.start()

    # ── Countdown ─────────────────────────────────────────────────────────────

    def _start_countdown(self):
        def tick():
            while self.timer_secs > 0 and self.locked:
                time.sleep(1)
                self.timer_secs -= 1
                if self.locked and self.lock_win:
                    t = self.timer_secs
                    try:
                        self.lock_win.after(0, lambda t=t:
                            self._timer_lbl.config(text=fmt_time(t)))
                    except Exception:
                        break
            if self.locked:
                try:
                    self.lock_win.after(0, self._unlock)
                except Exception:
                    pass

        threading.Thread(target=tick, daemon=True).start()

    # ── Focus guard ───────────────────────────────────────────────────────────

    def _keep_focus(self):
        if self.locked and self.lock_win and not self._auth_busy:
            try:
                self.lock_win.lift()
                self.lock_win.focus_force()
                if self.custom_pw is not None:
                    self._pw_entry.focus_set()
            except Exception:
                pass
        if self.locked and self.lock_win:
            self.lock_win.after(400, self._keep_focus)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    LockdownApp().run()
