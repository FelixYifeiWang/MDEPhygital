/*
  PPM Bridge: IN=D3 → 只取 CH7/CH8
              OUT=D9 → CH1..CH6 来自 PC, CH7/CH8 来自 D3

  - D3: 解析上游 PPM，只使用第7、8通道（索引6、7）
  - 串口: PC 发送最多 6 个值，映射到 CH1..CH6
  - D9: 用 Timer1 输出 8 通道 PPM
*/

#include <Arduino.h>

// ========== PPM INPUT (D3) ==========

const uint8_t  PPM_IN_PIN   = 3;
const uint8_t  MAX_CHANNELS = 16;
const uint16_t SYNC_MIN_US  = 3000;  // >2990µs 视为 frame sync
const uint16_t CH_MIN_US    = 900;
const uint16_t CH_MAX_US    = 2100;

volatile uint16_t isrChannels[MAX_CHANNELS];
volatile uint8_t  isrCount       = 0;
volatile bool     frameStarted   = false;

volatile uint16_t frameChannels[MAX_CHANNELS];
volatile uint8_t  frameCount     = 0;
volatile bool     frameReady     = false;

volatile uint32_t lastEdgeMicros = 0;

inline uint16_t clampU16(uint16_t v, uint16_t lo, uint16_t hi) {
  if (v < lo) return lo;
  if (v > hi) return hi;
  return v;
}

void ppmEdgeISR() {
  uint32_t now = micros();
  uint32_t dt  = now - lastEdgeMicros;
  lastEdgeMicros = now;
  if (dt == 0) return;

  // 1) 帧同步
  if (dt > SYNC_MIN_US) {
    if (isrCount > 0) {
      for (uint8_t i = 0; i < isrCount && i < MAX_CHANNELS; i++) {
        frameChannels[i] = isrChannels[i];
      }
      frameCount = isrCount;
      frameReady = true;
    }
    isrCount     = 0;
    frameStarted = true;
    return;
  }

  // 2) 正常通道
  if (dt >= CH_MIN_US && dt <= CH_MAX_US && frameStarted && isrCount < MAX_CHANNELS) {
    uint16_t v = clampU16((uint16_t)dt, 1000, 2000);
    isrChannels[isrCount++] = v;
    return;
  }

  // 3) 异常 → 重置
  isrCount     = 0;
  frameStarted = false;
}

// ========== PPM OUTPUT (D9, Timer1) ==========

const uint8_t PPM_OUT_PIN = 9;
const uint8_t CHANNELS    = 8;   // 输出 8 通道

volatile uint16_t ch[CHANNELS] = {
  1500,1500,1500,1500,1500,1500,1500,1500
};

const uint16_t FRAME_LEN = 22500;  // μs
const uint16_t PULSE_LEN = 400;    // μs

// PC 侧只控制前 6 个通道
uint16_t pcVals[6] = {1500,1500,1500,1500,1500,1500};

// CH7/CH8 平滑用
uint16_t filtCh7 = 1500;
uint16_t filtCh8 = 1500;
// 平滑强度：1 / (2^SMOOTH_SHIFT)
const uint8_t SMOOTH_SHIFT = 3; // 1/8 滤波

inline uint16_t smoothUpdate(uint16_t oldVal, uint16_t newVal) {
  int16_t diff = (int16_t)newVal - (int16_t)oldVal;
  return (uint16_t)(oldVal + (diff >> SMOOTH_SHIFT));
}

void setupTimer1() {
  pinMode(PPM_OUT_PIN, OUTPUT);
  digitalWrite(PPM_OUT_PIN, HIGH); // 空闲高电平（正脉冲 PPM）

  TCCR1A = 0;
  TCCR1B = 0;
  TCNT1  = 0;

  // CTC 模式, 预分频 8 → 2MHz tick (0.5µs)
  TCCR1B |= (1 << WGM12) | (1 << CS11);

  OCR1A = 1000;
  TIMSK1 |= (1 << OCIE1A);
}

// Timer1 中断：驱动 PPM 输出
ISR(TIMER1_COMPA_vect) {
  static bool     pulse = false; // true: 脉冲阶段 (低)
  static uint8_t  chan  = 0;
  static uint16_t rest;

  if (pulse) {
    // 结束脉冲 → 间隔
    digitalWrite(PPM_OUT_PIN, HIGH);
    pulse = false;

    if (chan >= CHANNELS) {
      OCR1A = rest * 2;
      chan  = 0;
    } else {
      uint16_t v = ch[chan];
      if (v < 1000) v = 1000;
      if (v > 2000) v = 2000;
      OCR1A = (v - PULSE_LEN) * 2;
      chan++;
    }

  } else {
    // 结束间隔 → 新脉冲
    digitalWrite(PPM_OUT_PIN, LOW);
    pulse = true;
    OCR1A = PULSE_LEN * 2;

    if (chan == 0) {
      uint32_t sum = 0;
      for (uint8_t i = 0; i < CHANNELS; i++) {
        uint16_t v = ch[i];
        if (v < 1000) v = 1000;
        if (v > 2000) v = 2000;
        sum += v;
      }
      // 注意：这里原本写法会让总帧长 = FRAME_LEN - CHANNELS * PULSE_LEN
      // 保持你原来的行为，不改逻辑，只做 CH7/8 降噪
      rest = FRAME_LEN - CHANNELS * PULSE_LEN - sum;
      if ((int32_t)rest < 1000) rest = 1000;
    }
  }
}

// ========== SETUP ==========

void setup() {
  Serial.begin(115200);
  while (!Serial) {;}

  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(PPM_IN_PIN, INPUT);

  // 和你之前一样用 FALLING，如果不对可以换成 RISING 测一下
  attachInterrupt(digitalPinToInterrupt(PPM_IN_PIN), ppmEdgeISR, FALLING);

  setupTimer1();

  Serial.println("PPM BRIDGE (D3→CH7/8, PC→CH1..6) READY");
  Serial.println("Serial: send up to 6 values (1000..2000) for CH1..CH6, e.g.");
  Serial.println("  1500,1600,1700,1800,1500,1500");
}

// ========== LOOP ==========

void loop() {
  // 1) 串口 → 更新 CH1..CH6
  if (Serial.available()) {
    String s = Serial.readStringUntil('\n');
    s.trim();
    if (s.length() > 0) {
      uint16_t tmp[6];
      uint8_t  n = 0;
      int      start = 0;

      while (start < s.length() && n < 6) {
        int comma = s.indexOf(',', start);
        String tok = (comma == -1) ? s.substring(start) : s.substring(start, comma);
        tok.trim();
        if (tok.length() > 0) {
          long v = tok.toInt();
          if (v < 1000) v = 1000;
          if (v > 2000) v = 2000;
          tmp[n++] = (uint16_t)v;
        }
        if (comma == -1) break;
        start = comma + 1;
      }

      if (n > 0) {
        for (uint8_t i = 0; i < n; i++) {
          pcVals[i] = tmp[i];
        }

        // 原子更新 CH1..CH6
        noInterrupts();
        for (uint8_t i = 0; i < 6; i++) {
          ch[i] = pcVals[i];
        }
        interrupts();

        Serial.print("PC updated CH1..CH");
        Serial.println(n);
      }
    }
  }

  // 2) 新的 PPM 帧 → 更新 CH7/CH8（带降噪）
  uint16_t buf[MAX_CHANNELS];
  uint8_t  count = 0;
  bool     ready = false;

  noInterrupts();
  if (frameReady) {
    frameReady = false;
    count = frameCount;
    if (count > MAX_CHANNELS) count = MAX_CHANNELS;
    for (uint8_t i = 0; i < count; i++) {
      buf[i] = frameChannels[i];
    }
    ready = true;
  }
  interrupts();

  if (ready) {
    // 需要至少 8 个通道才能拿到 CH7/CH8
    if (count >= 8) {
      uint16_t raw7 = clampU16(buf[6], 1000, 2000); // 输入 CH7
      uint16_t raw8 = clampU16(buf[7], 1000, 2000); // 输入 CH8

      // 对 CH7/CH8 做平滑滤波
      filtCh7 = smoothUpdate(filtCh7, raw7);
      filtCh8 = smoothUpdate(filtCh8, raw8);

      noInterrupts();
      ch[6] = filtCh7;  // 输出 CH7（已降噪）
      ch[7] = filtCh8;  // 输出 CH8（已降噪）
      interrupts();
    }
  }

  // (可选) 调试信息
  static uint32_t lastPrint = 0;
  if (millis() - lastPrint > 500) {
    lastPrint = millis();
    Serial.print("Last PPM frame channels: ");
    Serial.println(frameCount);
    // 也可以顺便看一下平滑后的 CH7/CH8 值：
    Serial.print("CH7/CH8 filt = ");
    Serial.print(filtCh7);
    Serial.print(", ");
    Serial.println(filtCh8);
  }
}
