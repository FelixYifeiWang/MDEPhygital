"""
=========================================
键盘 → 串口 → Arduino PPM 控制器（带图形显示）
=========================================

● 功能概述
    - 监听键盘按键 1~7，对应 7 个通道的“开/关”状态。
    - 当某个键被按下时，对应通道输出 2000（即“高位”信号），
      松开后恢复 1500（即中位）。
    - 通道状态变化后，通过串口发送一行形如：
        2000,1500,1500,1500,1500,1500,1500,1500\n
      给 Arduino（使用前面的 Pro Micro PPM 代码）。
    - 同时用 Matplotlib 实时显示 8 通道的当前值（柱状图）。
    - 仅在通道值变化时才发送串口数据，避免LED乱闪、串口过载。

● 串口连接
    - SERIAL_PORT 根据实际端口修改（如 Windows: "COM3"）。
    - BAUD_RATE = 115200，需与 Arduino 程序一致。
    - 每行发送以 '\n' 结尾，Arduino 那边使用 `readStringUntil('\n')` 接收。

● 模块功能
    - serial：与 Arduino 通信。
    - pynput.keyboard：捕获键盘事件（非阻塞）。
    - matplotlib：实时可视化通道变化。
    - threading：后台线程更新通道状态。
"""

import serial
from pynput import keyboard
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import time
import threading

# ==== 串口设置 ====
SERIAL_PORT = "/dev/cu.usbmodem101"  # ✅ 修改为你电脑上实际的端口
BAUD_RATE = 115200
ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
print(f"✅ Connected to {SERIAL_PORT}")

# ==== 全局状态 ====
channels = [1500] * 8      # 8通道初始值（单位：μs）
pressed = [False] * 8       # 每个通道的按键是否按下
last_sent = channels.copy() # 记录上一次发送的值，避免重复发送
lock = threading.Lock()     # 多线程访问锁，防止读写冲突

# -----------------------------------------------------
# 函数：仅当通道变化时才发送一行新的串口数据
# -----------------------------------------------------
def send_if_changed():
    global last_sent
    with lock:
        if channels != last_sent:
            # 将通道值转换为逗号分隔字符串
            line = ",".join(str(v) for v in channels)
            ser.write((line + "\n").encode())  # 发送到 Arduino
            last_sent = channels.copy()
            # 控制台调试打印，可注释掉避免刷屏
            print(f"→ Sent: {line}")

# -----------------------------------------------------
# 后台线程：周期性检查按键状态并更新通道
# -----------------------------------------------------
def updater_loop():
    """
    持续运行（独立线程）：
    - 根据 pressed[] 数组更新 channels[]。
    - 按下的通道 → 2000，松开的通道 → 1500。
    - 若有变化则触发 send_if_changed()。
    """
    while True:
        changed = False
        with lock:
            # 1~7 键映射到 CH1~CH7
            for i in range(7):
                target = 2000 if pressed[i] else 1500
                if channels[i] != target:
                    channels[i] = target
                    changed = True
        if changed:
            send_if_changed()   # 仅当变化时才真正发串口
        time.sleep(0.02)        # 每20ms更新一次，等价于50Hz刷新率

# -----------------------------------------------------
# 键盘事件：按下
# -----------------------------------------------------
def on_press(key):
    """当键被按下时，将对应 pressed[idx] 置为 True"""
    try:
        k = key.char
        if k in "1234567":         # 仅监听数字键 1~7
            idx = int(k) - 1
            if not pressed[idx]:   # 避免重复赋值
                pressed[idx] = True
    except:
        pass

# -----------------------------------------------------
# 键盘事件：松开
# -----------------------------------------------------
def on_release(key):
    """当键松开时，将对应 pressed[idx] 置为 False"""
    try:
        k = key.char
        if k in "1234567":
            idx = int(k) - 13
            if pressed[idx]:
                pressed[idx] = False
    except:
        pass

# -----------------------------------------------------
# 图表初始化
# -----------------------------------------------------
fig, ax = plt.subplots()
bars = ax.bar(range(1, 9), channels)     # 初始化8个柱子
ax.set_ylim(900, 2100)                   # Y轴范围：1000~2000之间留余量
ax.set_xticks(range(1, 9))
ax.set_xlabel("Channel")
ax.set_ylabel("Value (µs)")
ax.set_title("Real-Time Channel Output") # 标题（避免 emoji 警告）

# -----------------------------------------------------
# 动画函数：每帧更新柱状高度
# -----------------------------------------------------
def animate(_frame):
    """Matplotlib 动画回调：每100ms刷新一次柱状图"""
    with lock:
        for i, b in enumerate(bars):
            b.set_height(channels[i])
    return bars

# -----------------------------------------------------
# 启动后台线程与键盘监听器
# -----------------------------------------------------
threading.Thread(target=updater_loop, daemon=True).start()   # 通道更新线程
keyboard.Listener(on_press=on_press, on_release=on_release).start()  # 键盘监听

# -----------------------------------------------------
# 启动实时图表动画
# -----------------------------------------------------
ani = animation.FuncAnimation(
    fig,
    animate,
    interval=100,           # 每100ms刷新图表
    cache_frame_data=False  # 避免 Matplotlib 缓存警告
)
plt.show()
