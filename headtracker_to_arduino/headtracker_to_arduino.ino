/*
  ===============================================
  Pro Micro → PPM 输入解码器（只打印 CH8 & CH9）
  源协议参考 headtracker 的 PPMIn/PPMOut 实现
  ===============================================

  ● 硬件接线
    - 上游头控板 3.5mm PPM 输出：
        · 白线 → Pro Micro D3
        · 红线 → Pro Micro GND

  ● 协议假设（参考你贴的 PPMIn.cpp / PPMOut.cpp）
    - PPM 频率约 50Hz，一帧内最多 16 个通道
    - 通道脉宽：约 900..2100 µs
    - 帧同步间隔：> 2990 µs 视为 sync（源码里写死了 2990）
    - 我们只关心通道 8 和 9（索引 7 和 8）

  ● 注意
    - 默认用 RISING 边沿做测量，如若一直解不出通道，可以把
      attachInterrupt 的 RISING 改成 FALLING 再试。
*/

const uint8_t PPM_IN_PIN    = 3;     // PPM 输入脚（白线）

const uint8_t  MAX_CHANNELS = 16;    // 最多记录 16 通道（和对方代码一致）
const uint16_t SYNC_MIN_US  = 3000;  // >2990µs 视为帧同步间隔
const uint16_t CH_MIN_US    = 900;   // 有效通道范围下界
const uint16_t CH_MAX_US    = 2100;  // 有效通道范围上界

// ISR 内使用的通道缓存（本帧正在积累的通道）
volatile uint16_t isrChannels[MAX_CHANNELS];
volatile uint8_t  isrCount         = 0;
volatile bool     frameStarted     = false;

// 主循环读取用的通道缓存（完整帧）
volatile uint16_t frameChannels[MAX_CHANNELS];
volatile uint8_t  frameCount       = 0;
volatile bool     frameReady       = false;

// 上一次边沿的时间戳（micros）
volatile uint32_t lastEdgeMicros   = 0;

// 简单工具函数：夹紧到 [lo, hi]
inline uint16_t clampU16(uint16_t v, uint16_t lo, uint16_t hi) {
  if (v < lo) return lo;
  if (v > hi) return hi;
  return v;
}

// ========== 中断服务函数：在每个边沿计算间隔并解码 ==========
void ppmEdgeISR() {
  uint32_t now = micros();
  uint32_t dt  = now - lastEdgeMicros;
  lastEdgeMicros = now;

  if (dt == 0) return;

  // 1) 帧同步：时间间隔大于 ~3ms
  if (dt > SYNC_MIN_US) {
    // 如果当前帧中已经收集了若干通道，则认为上一帧结束
    if (isrCount > 0) {
      // 把当前帧数据拷贝到安全缓冲区
      for (uint8_t i = 0; i < isrCount && i < MAX_CHANNELS; i++) {
        frameChannels[i] = isrChannels[i];
      }
      frameCount = isrCount;
      frameReady = true;
    }

    // 重置，准备下一帧
    isrCount     = 0;
    frameStarted = true;
    return;
  }

  // 2) 普通通道：900..2100 µs，且已经进入帧
  if (dt >= CH_MIN_US && dt <= CH_MAX_US && frameStarted && isrCount < MAX_CHANNELS) {
    uint16_t v = clampU16((uint16_t)dt, 1000, 2000);  // 顺便夹到 [1000, 2000]
    isrChannels[isrCount++] = v;
    return;
  }

  // 3) 其他情况（抖动 / 错误）→ 重置
  isrCount     = 0;
  frameStarted = false;
}

void setup() {
  Serial.begin(115200);
  while (!Serial) { ; }  // Pro Micro 常见

  pinMode(PPM_IN_PIN, INPUT);

  // 关键：用单边沿（RISING）来测量，和 headtracker 的 PPMIn 一样只看某一极性
  // 如果一直没有正常通道，可以尝试改成 FALLING 再测试：
  //   attachInterrupt(digitalPinToInterrupt(PPM_IN_PIN), ppmEdgeISR, FALLING);
  attachInterrupt(digitalPinToInterrupt(PPM_IN_PIN), ppmEdgeISR, FALLING);

  Serial.println("PPM CH8/CH9 decoder ready.");
  Serial.println("Input on D3. Will print CH8 & CH9 when a full frame (>=9 channels) is decoded.");
}

void loop() {
  static uint32_t lastPrint = 0;
  uint32_t now = millis();

  if (now - lastPrint < 100) return;
  lastPrint = now;

  uint8_t  count = 0;
  bool     hasFrame = false;
  uint16_t chA = 1500;
  uint16_t chB = 1500;

  noInterrupts();
  if (frameReady) {
    frameReady = false;
    count = frameCount;
    if (count >= 8) {                 // ✅ 改成 8 就行
      chA = frameChannels[count - 2]; // 倒数第二个通道
      chB = frameChannels[count - 1]; // 倒数第一个通道
      hasFrame = true;
    }
  } else {
    count = frameCount;
  }
  interrupts();

  if (hasFrame) {
    Serial.print("PPM frame (");
    Serial.print(count);
    Serial.print(" ch):  last-1 = ");
    Serial.print(chA);
    Serial.print("  last = ");
    Serial.println(chB);
  } else {
    Serial.print("No full frame yet. Last channel count = ");
    Serial.println(count);
  }
}
