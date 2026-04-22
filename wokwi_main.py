# ============================================================
#  Traitor Air Defence System — MicroPython Firmware
#  Hardware: Raspberry Pi Pico  
#  Author:   Moiz Ul Rehman
# ============================================================

from machine import Pin, PWM, ADC, I2C
import time


# ============================================================
#  SSD1306 LIBRARY
#  import always works.
#  Physical Pico: Thonny > Tools > Manage Packages > micropython-ssd1306
# ============================================================
try:
    import ssd1306
    _HAS_SSD1306 = True
except ImportError:
    _HAS_SSD1306 = False
    print("[WARN] ssd1306 not found — OLED disabled")


servo_scan    = PWM(Pin(3));  servo_scan.freq(50)
servo_trigger = PWM(Pin(4));  servo_trigger.freq(50)

trig = Pin(8, Pin.OUT)
echo = Pin(5, Pin.IN)    

buzzer = PWM(Pin(6))
buzzer.freq(2730)
buzzer.duty_u16(0)
mode_sw = Pin(9, Pin.IN, Pin.PULL_DOWN)
btn_power = Pin(12, Pin.IN)
led_red   = Pin(10, Pin.OUT)
led_green = Pin(11, Pin.OUT)
led_power = Pin(13, Pin.OUT)

try:
    i2c = I2C(0, sda=Pin(17), scl=Pin(16), freq=400000)
except Exception as e:
    i2c = None
    print(f"[WARN] I2C init failed: {e}")
pot = ADC(26)


HAS_OLED = False
if _HAS_SSD1306 and i2c is not None:
    try:
        oled = ssd1306.SSD1306_I2C(128, 64, i2c)
        HAS_OLED = True
        print("[BOOT] OLED OK")
    except Exception as e:
        print(f"[WARN] OLED failed: {e}")


def servo_set_us(pwm_obj, us):
    duty = int(us / 20000.0 * 65535)
    pwm_obj.duty_u16(duty)


def angle_to_us(degrees):
    degrees = max(0, min(180, degrees))
    return int(500 + (degrees / 180.0) * 2000)


def get_distance_cm():

    trig.value(0)
    time.sleep_us(2)
    trig.value(1)
    time.sleep_us(10)
    trig.value(0)

    t0 = time.ticks_us()
    while echo.value() == 0:
        if time.ticks_diff(time.ticks_us(), t0) > 30000:
            return 999

    start = time.ticks_us()
    while echo.value() == 1:
        if time.ticks_diff(time.ticks_us(), start) > 30000:
            return 999
    stop = time.ticks_us()

    return time.ticks_diff(stop, start) / 58.0


def oled_show(line1, line2="", line3=""):
    if HAS_OLED:
        oled.fill(0)
        oled.text(str(line1)[:16], 0, 8)
        oled.text(str(line2)[:16], 0, 28)
        oled.text(str(line3)[:16], 0, 48)
        oled.show()
    else:
        print(f"[OLED] {line1} | {line2} | {line3}")


def buzzer_on():
    buzzer.duty_u16(32768)

def buzzer_off():
    buzzer.duty_u16(0)

def beep(times=1, on_ms=120, off_ms=100):
    for _ in range(times):
        buzzer_on();  time.sleep_ms(on_ms)
        buzzer_off(); time.sleep_ms(off_ms)


def get_threshold_cm():
    raw = pot.read_u16()
    return 10 + int((raw / 65535.0) * 140)


def get_mode():
    return "LAUNCH" if mode_sw.value() == 1 else "ALaRM"



SWEEP_MIN_DEG  = 0      
SWEEP_MAX_DEG  = 180    
SWEEP_STEP_DEG = 3      
STEP_DELAY_MS  = 40     

sweep_angle = 90        
sweep_dir   = 1         


def sweep_step():
    global sweep_angle, sweep_dir
    sweep_angle += sweep_dir * SWEEP_STEP_DEG
    if sweep_angle >= SWEEP_MAX_DEG:
        sweep_angle = SWEEP_MAX_DEG
        sweep_dir = -1
    elif sweep_angle <= SWEEP_MIN_DEG:
        sweep_angle = SWEEP_MIN_DEG
        sweep_dir = 1
    servo_set_us(servo_scan, angle_to_us(sweep_angle))
    return sweep_angle


def trigger_home():
    servo_set_us(servo_trigger, angle_to_us(90))


def full_home():
    global sweep_angle, sweep_dir
    sweep_angle = 90
    sweep_dir   = 1
    servo_set_us(servo_scan,    angle_to_us(90))
    servo_set_us(servo_trigger, angle_to_us(90))

system_active = False
_btn_prev     = 0
_btn_last_ms  = 0
def check_button():
    global system_active, _btn_prev, _btn_last_ms
    
    curr_val = btn_power.value()
    curr_ms = time.ticks_ms()
    
    if curr_val == 1 and _btn_prev == 0:
        if time.ticks_diff(curr_ms, _btn_last_ms) > 250:
            system_active = not system_active

            beep(1, 50, 0) 
            print(f"[POWER] System is now {'ON' if system_active else 'OFF'}")
            
    _btn_prev = curr_val


STATE_IDLE     = 0
STATE_SCANNING = 1
STATE_CONFIRM  = 2
STATE_ALERT    = 3
STATE_COOLDOWN = 4

state         = STATE_IDLE
confirm_count = 0
detected_dist = 0.0
locked_angle  = 90



led_power.value(1)
led_red.value(0)
led_green.value(0)

full_home()
beep(times=2, on_ms=80, off_ms=80)   

oled_show("AIR DEFENCE", "Traitor READY")
time.sleep_ms(1500)

print("=" * 42)
print("[BOOT] Traiotr Air Defence")
print(f"[BOOT] OLED  : {'OK' if HAS_OLED else 'FAILED'}")
print(f"[BOOT] I2C   : Bus 0  SDA=GP17  SCL=GP16")
print(f"[BOOT] Mode  : {get_mode()}")
print("=" * 42)


while True:
    check_button()

    if not system_active:

        led_power.value(0)
        led_red.value(0)
        led_green.value(0)
        buzzer_off()
        oled_show("SYSTEM OFF", "Press button")
        state = STATE_IDLE 
        time.sleep_ms(100)
        continue 

    led_power.value(1) 

    if state == STATE_IDLE:
        led_green.value(1)
        led_red.value(0)
        oled_show("[ IDLE ]", "System armed", f"Mode:{get_mode()}")
        time.sleep_ms(400)
        state = STATE_SCANNING
        print("[STATE] → SCANNING")

    elif state == STATE_SCANNING:
        current_angle = sweep_step()
        threshold     = get_threshold_cm()
        dist          = get_distance_cm()
        mode          = get_mode()

        led_green.value(1 if (current_angle % 30) < 15 else 0)
        led_red.value(0)

        oled_show(
            f"[{mode}] SCAN",
            f"D:{dist:.0f}cm T:{threshold}cm",
            f"A:{current_angle:03d} {'>>>' if sweep_dir > 0 else '<<<'}"
        )
        print(f"[SCAN] angle={current_angle}  dist={dist:.1f}cm  thresh={threshold}cm")

        if dist <= threshold:
            confirm_count = 1
            detected_dist = dist
            locked_angle  = current_angle
            state = STATE_CONFIRM
            print(f"[STATE] → CONFIRM  dist={dist:.1f}cm  angle={current_angle}deg")

        time.sleep_ms(STEP_DELAY_MS)

    elif state == STATE_CONFIRM:
        threshold = get_threshold_cm()
        dist      = get_distance_cm()

        led_green.value(1)
        led_red.value(0)

        oled_show(
            "CONFIRMING...",
            f"D:{dist:.0f}cm T:{threshold}cm",
            f"Reading {confirm_count}/3"
        )
        print(f"[CONFIRM] dist={dist:.1f}cm  count={confirm_count}/3")

        if dist <= threshold:
            confirm_count += 1
            detected_dist = dist
            if confirm_count >= 3:
                state = STATE_ALERT
                print(f"[STATE] → ALERT  dist={detected_dist:.1f}cm  angle={locked_angle}deg")
        else:
            confirm_count = 0
            state = STATE_SCANNING
            print("[STATE] → SCANNING")

        time.sleep_ms(STEP_DELAY_MS)

    elif state == STATE_ALERT:
        led_green.value(0)
        led_red.value(1)

        mode = get_mode()

        servo_set_us(servo_scan, angle_to_us(locked_angle))

        if mode == "LAUNCH":
            servo_set_us(servo_trigger, angle_to_us(locked_angle))
            oled_show("!! DETeCTED !!", f"D:{detected_dist:.0f}cm Az:{locked_angle}", "LAUNCH ENaBLED")
            print(f"[ALERT] LAUnCH  dist={detected_dist:.1f}cm  angel={locked_angle}deg")
        else:
            servo_set_us(servo_trigger, angle_to_us(90))
            oled_show("!! DETECTED !!", f"D:{detected_dist:.0f}cm Az:{locked_angle}", "ALARM ONLY")
            print(f"[ALERT] Alarm   dist={detected_dist:.1f}cm  angel={locked_angle}deg")

        buzzer_on()
        time.sleep_ms(2000)
        buzzer_off()

        state = STATE_COOLDOWN
        print("[STATE] → COOLDOWN")

    elif state == STATE_COOLDOWN:
        led_red.value(1)
        led_green.value(0)
        buzzer_off()

        for i in range(5, 0, -1):
            oled_show("[ COOLDOWN ]", f"Resume in {i}s", f"Az:{locked_angle:03d} locked")
            print(f"[COOLDOWN] {i}s  scan locked at {locked_angle}deg")
            time.sleep_ms(1000)

        trigger_home()  
        led_red.value(0)
        confirm_count = 0
        state = STATE_SCANNING
        print(f"[STATE] → SCANNING from {sweep_angle}deg")