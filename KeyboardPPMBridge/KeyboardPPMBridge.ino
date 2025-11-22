/*
  ===============================================
  Pro Micro → PPM 输出器（D9）— 串口驱动 8 通道
  ===============================================

  ● 作用
    - 通过串口接收一行逗号分隔的通道值（1000..2000 μs），
      例如：1500,1500,1500,1500,1500,1500,1500,1500\n
    - 使用 16 位定时器1 以“正脉冲PPM”（空闲高，脉冲为低电平）在 D9 脚输出 PPM 信号。
    - 帧长 22.5ms，8 通道，单个通道的编码为：一次低电平脉冲 (PULSE_LEN) + 间隔 (通道值 - PULSE_LEN)。
    - 一帧最后用“同步间隔（sync gap）”补齐到固定帧长。

  ● 串口
    - 波特率：115200
    - 每行：最多 8 个通道，逗号分隔，以 '\n' 结尾；缺省的通道保持上次值。
    - 输入值范围自动夹紧到 [1000, 2000]（单位：微秒）。

  ● 接线（3.5mm 母座/TRS）
    - PPM 信号（D9） → 3.5mm Tip（尖端）
    - GND → 3.5mm Sleeve（套筒/地）
    - 常见接收端只用到 Tip 与 Sleeve；Ring 悬空即可。

  ● 时序/计时（定时器1）
    - 主频 16 MHz，预分频 8 ⇒ 计数频率 2 MHz ⇒ 0.5 μs/计数tick
    - OCR1A 设定下一段的比较匹配点，进入 ISR(TIMER1_COMPA_vect) 切换“脉冲/间隔”阶段。
    - 每个阶段结束时，重装 OCR1A = 该阶段持续时间(微秒) × 2（将 μs 转换为 tick）。

  ● 安全/注意
    - 输出为“正脉冲PPM”：空闲为高电平，脉冲期间拉低。
    - 若外设需要“负脉冲PPM”（空闲低、脉冲高），需反相或改动电平逻辑。
    - PPM 是“单线串行”多通道编码，接收端需支持 PPM 输入。
*/

const uint8_t PPM_PIN   = 9;   // PPM 输出脚（接 3.5mm Tip）
const uint8_t CHANNELS  = 8;   // 通道数量
volatile uint16_t ch[CHANNELS] = {
  1500,1500,1500,1500,1500,1500,1500,1500
}; // 通道当前值（μs），用 volatile 以便 ISR 与主循环安全共享

// 帧/脉冲参数（单位：微秒）
const uint16_t FRAME_LEN = 22500; // 整帧长度（常见 18~22.5ms，这里取 22.5ms ≈ 44.4Hz）
const uint16_t PULSE_LEN = 400;   // 每个通道的“低电平脉冲”宽度（常用 300~400μs）

// -------------------------
// 定时器1初始化（CTC 模式）
// -------------------------
void setupTimer1() {
  pinMode(PPM_PIN, OUTPUT);
  digitalWrite(PPM_PIN, HIGH); // 正脉冲PPM的空闲状态为高电平

  // 复位控制寄存器与计数器
  TCCR1A = 0;
  TCCR1B = 0;
  TCNT1  = 0;

  // CTC 模式 (WGM12=1)，预分频 8 (CS11=1) → 2 MHz 计数（0.5μs/tick）
  TCCR1B |= (1 << WGM12) | (1 << CS11);

  // 初始比较值（tick），很快会在 ISR 内被重装
  OCR1A = 1000;

  // 允许比较匹配中断
  TIMSK1 |= (1 << OCIE1A);
}

// ---------------------------------------------
// 定时器1比较匹配中断：驱动 PPM“脉冲/间隔”序列
// ---------------------------------------------
ISR(TIMER1_COMPA_vect) {
  // 静态局部变量保留跨中断调用的状态
  static bool     pulse = false; // 当前是否处于“脉冲阶段”（低电平）
  static uint8_t  chan  = 0;     // 正在输出的通道索引 [0..CHANNELS]
  static uint16_t rest;          // 本帧的同步间隔（μs）

  if (pulse) {
    // ---- 脉冲阶段结束：拉高，进入间隔阶段 ----
    digitalWrite(PPM_PIN, HIGH);
    pulse = false;

    if (chan >= CHANNELS) {
      // 所有通道均已输出 → 输出“同步间隔”以对齐帧长
      // OCR1A 单位为 tick（0.5μs/tick），因此 rest(μs) ×2
      OCR1A = rest * 2;
      chan  = 0; // 准备进入下一帧的第0通道
    } else {
      // 正常通道间隔：通道值 - 脉冲宽度
      uint16_t v = ch[chan];
      if (v < 1000) v = 1000;        // 夹紧到 [1000,2000]
      if (v > 2000) v = 2000;

      // 通道“间隔阶段”的持续时间（μs）
      // 注意：该“间隔”与下一个中断到来前，输出脚保持高电平
      OCR1A = (v - PULSE_LEN) * 2;   // 转换为 tick
      chan++;                        // 切到下一个通道
    }

  } else {
    // ---- 间隔阶段结束：开始一个“低电平脉冲” ----
    digitalWrite(PPM_PIN, LOW);
    pulse = true;

    // 低电平脉冲持续 PULSE_LEN μs
    OCR1A = PULSE_LEN * 2;

    // 在每帧开始（chan==0，即刚刚拉低第0通道前）计算本帧同步间隔
    if (chan == 0) {
      uint32_t sum = 0;
      for (uint8_t i = 0; i < CHANNELS; i++) {
        uint16_t v = ch[i];
        if (v < 1000) v = 1000;
        if (v > 2000) v = 2000;
        sum += v;
      }
      // rest = 帧长 - 所有通道的脉冲总时长 - 所有通道的间隔总时长(=各通道值)
      //     = FRAME_LEN - CHANNELS*PULSE_LEN - sum(ch[i])
      rest = FRAME_LEN - CHANNELS * PULSE_LEN - sum;

      // 给同步间隔留一个下限，避免过短（某些接收端需要明显的sync gap）
      if ((int32_t)rest < 1000) rest = 1000;
    }
  }
}

// -----------------
// Arduino 启动逻辑
// -----------------
void setup() {
  Serial.begin(115200);                // 打开串口
  pinMode(LED_BUILTIN, OUTPUT);        // 板载LED用于回执闪烁

  // 等待串口就绪（部分板子需要；Pro Micro 常见）
  while (!Serial) { ; }

  Serial.println("READY: send up to 8 values 1000..2000 separated by commas, then Enter.");
  // 例如：1500,1600,1700,1800,1500,1500,1500,1500

  setupTimer1();                       // 初始化定时器1 → 开始输出PPM
}

// ---------------------------------------------
// 主循环：读取一行串口并更新通道；无输入时做演示动画
// ---------------------------------------------
void loop() {
  // 若串口有数据，读取到换行符
  if (Serial.available()) {
    String s = Serial.readStringUntil('\n');
    s.trim();
    if (s.length() == 0) return; // 空行直接忽略

    // 解析一行中的逗号分隔通道值
    uint16_t tmp[CHANNELS];
    uint8_t  n = 0;
    int      start = 0;

    while (start < s.length() && n < CHANNELS) {
      int comma = s.indexOf(',', start);
      String tok = (comma == -1) ? s.substring(start) : s.substring(start, comma);
      tok.trim();

      if (tok.length() > 0) {
        long v = tok.toInt();        // 字符串→整数（默认十进制）
        if (v < 1000) v = 1000;      // 夹紧
        if (v > 2000) v = 2000;
        tmp[n++] = (uint16_t)v;
      }

      if (comma == -1) break;        // 已到行尾
      start = comma + 1;             // 跳到下一个字段
    }

    if (n > 0) {
      // 原子性更新通道数组：在 ISR 期间禁用中断，避免读写竞争
      noInterrupts();
      for (uint8_t i = 0; i < n; i++) ch[i] = tmp[i];
      interrupts();

      Serial.print("OK: ");
      Serial.print(n);
      Serial.println(" channels updated");

      // 视觉回执：LED 闪两下
      for (int i = 0; i < 2; i++) {
        digitalWrite(LED_BUILTIN, HIGH); delay(120);
        digitalWrite(LED_BUILTIN, LOW);  delay(120);
      }
    } else {
      Serial.println("ERR: no numbers found"); // 行内未解析到数字
    }
  }

  // ---------- 演示模式 ----------
  // 若 2 秒内没有新串口数据，自动让 CH5/CH6 做反向摆动（便于示波器/接收端观察）
  static uint32_t t_last = millis();  // 上次收到串口数据的时间
  static uint32_t t_anim = millis();  // 上次动画步进时间

  if (Serial.available() == 0 && millis() - t_last > 2000) {
    // 每 20ms 步进一次，制造慢速往返
    if (millis() - t_anim > 20) {
      t_anim = millis();
      static int v = 1500;    // 当前值
      static int dir = 5;     // 递增方向与步长
      v += dir;
      if (v > 1900 || v < 1100) dir = -dir; // 到边界反向

      // CH5, CH6 反向联动：一个升，另一个降
      noInterrupts();
      ch[4] = v;              // 第5通道
      ch[5] = 3000 - v;       // 第6通道（使两者和≈常数）
      interrupts();
    }
  } else {
    // 只要串口有数据流动，就刷新“最近活跃”时间戳
    t_last = millis();
  }
}
