import tkinter as tk
from tkinter import Canvas
import serial
from serial.tools import list_ports
import time
import threading


BAUD_RATE = 115200


def find_arduino_port():
    """
    Try to automatically find an Arduino-like serial device.
    Prints all candidates for debugging.
    """
    ports = list_ports.comports()
    if not ports:
        print("No serial ports found.")
        return None

    print("Available serial ports:")
    candidate = None
    for p in ports:
        vid = hex(p.vid) if p.vid else None
        pid = hex(p.pid) if p.pid else None
        print(f"  {p.device} | {p.description} | VID={vid} PID={pid}")

        # Heuristic: Arduino-ish devices
        if ("Arduino" in (p.description or "")) or \
           ("usbmodem" in (p.device or "")) or \
           ("usbserial" in (p.device or "")):
            candidate = p.device

    if candidate:
        print("Using serial port:", candidate)
    else:
        print("⚠️ No Arduino-like serial device found by heuristic.")
    return candidate


class GesturePPMApp:
    def __init__(self):
        # ----- Serial -----
        port = find_arduino_port()
        if port is not None:
            try:
                self.ser = serial.Serial(port, BAUD_RATE, timeout=0.1)
                print(f"✅ Connected to {port}")
            except Exception as e:
                self.ser = None
                print(f"⚠️ Failed to open serial port {port}: {e}")
        else:
            self.ser = None

        # ----- Channel state -----
        self.channels = [1500] * 8           # 8 通道初始值
        self.pressed = [False] * 8           # index 0–6 对应按键 1–7
        self.last_sent = self.channels.copy()
        self.lock = threading.Lock()
        self.running = True

        # Sequence activation: tap 0, then 4/5/6
        self.armed_special = False           # 是否已经点了 0（等待 4/5/6）
        self.allowed_special = [False] * 8   # 当前这一轮按下的 4/5/6 是否被“授权”

        # 按下时的目标值 (index = 通道号 - 1)
        self.press_values = [2000] * 8
        self.press_values[3] = 1700  # CH4: vibration
        self.press_values[4] = 1000  # CH5: drop pin left
        # CH6 (index 5) remains 2000 (Drop Right)

        # 显示文字映射（前端）
        self.feature_names = {
            4: "Vibration",
            5: "Drop Pin · Left",
            6: "Drop Pin · Right",
        }

        # ----- Tk UI -----
        self.root = tk.Tk()
        self.root.title("Gesture Console")

        self.root.attributes("-fullscreen", True)
        self.root.configure(bg="#050508")

        self.canvas = Canvas(self.root, bg="#050508", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # UI element handles
        self.exit_rect = None
        self.exit_text = None
        self.title_text = None
        self.main_text = None
        self.subtitle_text = None
        self.helper_text = None

        # Bar chart info
        self.bar_rects = []
        self.bar_base_y = 0
        self.bar_max_height = 160
        self.min_us = 1000
        self.max_us = 2000

        self.build_ui()

        # Key listeners
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.bind("<KeyRelease>", self.on_key_release)
        self.root.focus_force()

        # Mouse for close button
        self.canvas.bind("<Button-1>", self.on_click)

        # Resize handler
        self.root.bind("<Configure>", self.on_resize)

        # Graceful close
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Start background thread for PPM updates
        threading.Thread(target=self.updater_loop, daemon=True).start()

        # Start bar animation
        self.update_bars()

        self.root.mainloop()

    # =================== UI =================== #

    def get_size(self):
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        if w < 200 or h < 200:
            w = self.root.winfo_screenwidth()
            h = self.root.winfo_screenheight()
        return w, h

    def build_ui(self):
        w, h = self.get_size()
        self.canvas.delete("all")
        self.bar_rects = []

        # ---- Top bar ----
        top_height = 56
        padding_x = 24

        self.canvas.create_rectangle(
            0, 0, w, top_height,
            fill="#090A10", outline=""
        )

        self.title_text = self.canvas.create_text(
            padding_x,
            top_height / 2,
            anchor="w",
            text="Gesture Console",
            fill="#F5F5F7",
            font=("Helvetica", 16, "bold")
        )

        # Exit pill
        btn_w = 72
        btn_h = 28
        bx2 = w - padding_x
        bx1 = bx2 - btn_w
        by1 = (top_height - btn_h) / 2
        by2 = by1 + btn_h

        self.exit_rect = self.canvas.create_rectangle(
            bx1, by1, bx2, by2,
            fill="#1F2027", outline="#3A3D45", width=1
        )
        self.exit_text = self.canvas.create_text(
            (bx1 + bx2) / 2,
            (by1 + by2) / 2,
            text="Exit",
            fill="#E5E5EA",
            font=("Helvetica", 11)
        )

        # ---- Center content ----
        center_y = h * 0.38

        self.main_text = self.canvas.create_text(
            w / 2,
            center_y,
            text="Waiting",
            fill="#FFFFFF",
            font=("Helvetica", 42, "bold")
        )

        self.subtitle_text = self.canvas.create_text(
            w / 2,
            center_y + 40,
            text="Press 1–7  ·  0 then 4/5/6 for actions",
            fill="#8E8E93",
            font=("Helvetica", 16)
        )

        # ---- Bar chart for 8 channels ----
        margin_bottom = 90
        chart_top = center_y + 90
        chart_height = min(self.bar_max_height, max(120, h - chart_top - margin_bottom))
        self.bar_max_height = chart_height
        self.bar_base_y = chart_top + chart_height

        bar_width = 26
        gap = 18
        total_width = 8 * bar_width + 7 * gap
        start_x = (w - total_width) / 2

        self.bar_rects = []
        for i in range(8):
            x1 = start_x + i * (bar_width + gap)
            x2 = x1 + bar_width
            val = self.channels[i]
            height = self.value_to_height(val)
            y1_bar = self.bar_base_y - height
            y2_bar = self.bar_base_y

            rect = self.canvas.create_rectangle(
                x1, y1_bar, x2, y2_bar,
                fill="#3D79FF", outline=""
            )
            self.bar_rects.append(rect)

            label = f"{i+1}"
            self.canvas.create_text(
                (x1 + x2) / 2,
                self.bar_base_y + 14,
                text=label,
                fill="#6C6C70",
                font=("Helvetica", 10)
            )

        self.canvas.create_line(
            start_x,
            self.bar_base_y,
            start_x + total_width,
            self.bar_base_y,
            fill="#2C2C34",
            width=1
        )

        # ---- Helper text ----
        helper = "1–3,7: gestures   •   0 → 4: Vibration   •   0 → 5: Drop Left   •   0 → 6: Drop Right   •   Esc/Q: exit"
        self.helper_text = self.canvas.create_text(
            w / 2,
            h - 40,
            text=helper,
            fill="#5C5C60",
            font=("Helvetica", 11)
        )

    def value_to_height(self, val):
        val_clamped = max(self.min_us, min(self.max_us, val))
        ratio = (val_clamped - self.min_us) / (self.max_us - self.min_us)
        return ratio * self.bar_max_height

    # =================== EVENTS =================== #

    def on_resize(self, event):
        if event.widget == self.root:
            self.build_ui()

    def on_click(self, event):
        x, y = event.x, event.y
        if self.exit_rect and self.is_inside(x, y, self.exit_rect):
            self.on_close()

    def on_close(self):
        self.running = False
        time.sleep(0.05)
        if self.ser is not None:
            try:
                self.ser.close()
            except:
                pass
        self.root.destroy()

    def play_arm_sound(self):
        """Simple sound cue when 0 is tapped to arm."""
        try:
            self.root.bell()  # cross-platform Tk beep
        except Exception:
            pass

    def on_key_press(self, event):
        # Exit
        if event.keysym == "Escape" or (event.char and event.char.lower() == "q"):
            self.on_close()
            return

        # Tap 0 → arm special actions
        if event.char == "0":
            with self.lock:
                self.armed_special = True
            self.play_arm_sound()
            self.canvas.itemconfig(self.main_text, text="Armed")
            self.canvas.itemconfig(
                self.subtitle_text,
                text="0 tapped · Choose 4 / 5 / 6"
            )
            print("Activation tapped: waiting for 4/5/6")
            return

        # Gesture keys 1–7
        if event.char in "1234567":
            idx = int(event.char) - 1
            with self.lock:
                # 🔑 Ignore key auto-repeat: only handle first press
                if self.pressed[idx]:
                    return

                self.pressed[idx] = True

                # Special channels 4/5/6 (index 3, 4, 5) need 0→key sequence
                if idx in (3, 4, 5):  # CH4, CH5, CH6
                    if self.armed_special:
                        # Authorized for this press; consume the arm
                        self.allowed_special[idx] = True
                        self.armed_special = False
                    else:
                        # Not armed: this press is NOT authorized
                        self.allowed_special[idx] = False

            self.show_gesture(event.char)

    def on_key_release(self, event):
        if event.char in "1234567":
            idx = int(event.char) - 1
            with self.lock:
                self.pressed[idx] = False
                if idx in (3, 4, 5):
                    # One-shot: releasing 4/5/6 ends this authorized gesture
                    self.allowed_special[idx] = False

                any_pressed = any(self.pressed)
            if not any_pressed:
                self.clear_gesture()

    # =================== UI UPDATES =================== #

    def show_gesture(self, key_char: str):
        """
        UI 显示：
        - 4/5/6：显示功能名；如果没走 0→4/5/6 序列，则提示需要 0
        - 1/2/3/7：显示 Gesture N
        """
        if not key_char or key_char not in "1234567":
            return

        num = int(key_char)
        feature = self.feature_names.get(num)

        if feature:
            main_text = feature
            idx = num - 1
            with self.lock:
                allowed = self.allowed_special[idx]
            if allowed:
                subtitle = f"Gesture {num} · {feature}"
            else:
                subtitle = f"Gesture {num} · Need 0 → {num} to execute"
        else:
            main_text = f"Gesture {num}"
            subtitle = "Detected gesture"

        self.canvas.itemconfig(self.main_text, text=main_text)
        self.canvas.itemconfig(self.subtitle_text, text=subtitle)
        print(f"Gesture detected: {subtitle}")

    def clear_gesture(self):
        self.canvas.itemconfig(self.main_text, text="Waiting")
        self.canvas.itemconfig(
            self.subtitle_text,
            text="Press 1–7  ·  0 then 4/5/6 for actions"
        )

    def update_bars(self):
        """定时从 channels[] 更新 8 个柱子的高度"""
        if not self.bar_rects:
            self.root.after(50, self.update_bars)
            return

        with self.lock:
            values = self.channels.copy()

        for i, rect in enumerate(self.bar_rects):
            val = values[i]
            height = self.value_to_height(val)
            x1, _, x2, _ = self.canvas.coords(rect)
            y1 = self.bar_base_y - height
            y2 = self.bar_base_y
            self.canvas.coords(rect, x1, y1, x2, y2)

        self.root.after(50, self.update_bars)

    # =================== PPM / SERIAL BACKGROUND =================== #

    def send_if_changed(self):
        with self.lock:
            if self.channels != self.last_sent:
                line = ",".join(str(v) for v in self.channels)
                if self.ser is not None and self.ser.is_open:
                    try:
                        self.ser.write((line + "\n").encode())
                    except Exception as e:
                        print(f"⚠️ Serial write error: {e}")
                self.last_sent = self.channels.copy()
                print(f"→ Sent: {line}")

    def updater_loop(self):
        """
        后台线程：
        - CH1–3,7: 按下 → press_values[i]，松开 → 1500
        - CH4–6: 必须先 0，再按 4/5/6，且在 allowed_special=True 且 pressed=True 时才输出 press_values
          （PPM 只在按键释放后才回到 1500）
        - CH8: 始终 1500
        """
        while self.running:
            changed = False
            with self.lock:
                for i in range(7):  # CH1~CH7
                    if i in (3, 4, 5):  # special channels
                        active = self.pressed[i] and self.allowed_special[i]
                    else:
                        active = self.pressed[i]

                    target = self.press_values[i] if active else 1500
                    if self.channels[i] != target:
                        self.channels[i] = target
                        changed = True

                # CH8 保持 1500
                if self.channels[7] != 1500:
                    self.channels[7] = 1500
                    changed = True

            if changed:
                self.send_if_changed()

            time.sleep(0.02)  # ~50Hz

    # =================== UTIL =================== #

    def is_inside(self, x, y, shape_id):
        x1, y1, x2, y2 = self.canvas.coords(shape_id)
        return x1 <= x <= x2 and y1 <= y <= y2


if __name__ == "__main__":
    GesturePPMApp()
