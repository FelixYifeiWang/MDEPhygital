"""
=========================================
键盘 → 串口 → Arduino PPM 控制器（CH6 多档位）
=========================================

● 功能概述
    - 监听键盘按键：
        1 → CH6 =  500 µs
        2 → CH6 = 2500 µs
        3 → CH6 = 2212 µs
    - 松开按键后，CH6 恢复到 1500 µs（中位）。
    - 其他通道始终维持 1500 µs。
    - 通道状态变化后，通过串口发送一行形如：
        1500,1500,1500,1500,1500,500,1500,1500\n
      给 Arduino（使用 Pro Micro PPM 代码）。
    - 同时用 Matplotlib 实时显示 8 通道的当前值（柱状图）。
    - 仅在通道值变化时才发送串口数据。

● 串口连接
    - SERIAL_PORT 根据实际端口修改（如 Windows: "COM3"）。
    - BAUD_RATE = 115200，需与 Arduino 程序一致。
"""

import serial
from pynput import keyboard
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import threading

# ==== 串口设置 ====
SERIAL_PORT = "/dev/cu.usbmodem101"  # ✅ 修改为你电脑上实际的端口
BAUD_RATE = 115200
ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
print(f"✅ Connected to {SERIAL_PORT}")

# ==== 全局状态 ====
channels = [1500] * 8      # 8 通道初始值（单位：µs）
last_sent = channels.copy() # 记录上一次发送的值，避免重复发送
lock = threading.Lock()     # 多线程访问锁，防止读写冲突

# 键到 CH6 脉宽的映射
KEY_TO_US = {
    "1": 500,
    "2": 2500,
    "3": 2212,
}

# 当前激活的键（1/2/3），用于处理松开逻辑
active_key = None

# -----------------------------------------------------
# 函数：仅当通道变化时才发送一行新的串口数据
# -----------------------------------------------------
def send_if_changed():
    global last_sent
    with lock:
        if channels != last_sent:
            line = ",".join(str(v) for v in channels)
            ser.write((line + "\n").encode())
            last_sent = channels.copy()
            print(f"→ Sent: {line}")

# -----------------------------------------------------
# 设置 CH6（索引 5）的值并尝试发送
# -----------------------------------------------------
def set_ch6(value):
    with lock:
        if channels[5] == value:
            return
        channels[5] = value
    send_if_changed()

# -----------------------------------------------------
# 键盘事件：按下
# -----------------------------------------------------
def on_press(key):
    global active_key
    try:
        k = key.char
    except AttributeError:
        return

    if k in KEY_TO_US:
        # 记录当前激活键，并设定对应脉宽
        active_key = k
        set_ch6(KEY_TO_US[k])

# -----------------------------------------------------
# 键盘事件：松开
# -----------------------------------------------------
def on_release(key):
    global active_key
    try:
        k = key.char
    except AttributeError:
        return

    # 只有松开当前激活的键时，才恢复到 1500
    if k == active_key:
        active_key = None
        set_ch6(1500)

# -----------------------------------------------------
# 图表初始化
# -----------------------------------------------------
fig, ax = plt.subplots()
bars = ax.bar(range(1, 9), channels)     # 初始化8个柱子
ax.set_ylim(400, 2600)                   # 为 500/1500/2212/2500 预留范围
ax.set_xticks(range(1, 9))
ax.set_xlabel("Channel")
ax.set_ylabel("Value (µs)")
ax.set_title("Real-Time Channel Output (CH6 controlled by 1/2/3)")

# -----------------------------------------------------
# 动画函数：每帧更新柱状高度
# -----------------------------------------------------
def animate(_frame):
    with lock:
        for i, b in enumerate(bars):
            b.set_height(channels[i])
    return bars

# -----------------------------------------------------
# 启动键盘监听与实时图表动画
# -----------------------------------------------------
listener = keyboard.Listener(on_press=on_press, on_release=on_release)
listener.start()

ani = animation.FuncAnimation(
    fig,
    animate,
    interval=100,           # 每 100 ms 刷新图表
    cache_frame_data=False
)

plt.show()

# 程序结束时停止监听（窗口关掉后）
listener.stop()
