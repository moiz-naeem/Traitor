# ============================================================
#  Traitor Traitor Air Defence System — MicroPython Firmware
#  Hardware: Raspberry Pi Pico  
#  Author:   Moiz Ul Rehman
#
#  Below is my code for the air defence turret. 
#  Basically it spins ultrasonic sensor around to look for things in the way. 
#  If something gets to close, it double checks,
#  and sounds the alarm. If I flip the switch, it also moves a 
#  second servo to launch a dart at the detected obj 
#
#  Gpio mapping:
#    Pin 3  -> scanner servo that spins left and right 
#    Pin 4  -> launcher servo that pulls the trigger
#    Pin 5  -> ultrasonic trig 
#    Pin 8  -> ultrasonic echo 
#    Pin 1  -> buzzer for the alarm
#    Pin 9  -> slide switch to choose ALARM or LAUNCH mode
#    Pin 12 -> Big main power button
#    Pin 11 -> Red LED (danger light)
#    Pin 13 -> Green LED (scanning/safe light)
#    Pin 10 -> White LED (tells us system is turned on)
#    Pin 16 -> OLED screen SCL clock pin
#    Pin 17 -> OLED screen SDA data pin
#    Pin 26 -> potentiometer to change distance limit
# ============================================================

from machine import Pin, PWM, ADC, I2C
import time

# ============================================================
#  Screen stuff. 
#  Sometimes the screen library is missing depending on which IDE 
#  you are using and it crashes the whole code. So I put a try/except here. 
#  If it cant find the screen code, it just skips it and prints to the serial debig
# ============================================================
try:
    import ssd1306
    _HAS_SSD1306 = True
except ImportError:
    _HAS_SSD1306 = False
    print("[WARN] ssd1306 not found — OLED disabled")

# Setting up the servo motors. They need a 50 frequency to work right.
servo_scan    = PWM(Pin(3));  servo_scan.freq(50)
servo_trigger = PWM(Pin(4));  servo_trigger.freq(50)

# Trigger and echo of ultrasonic sensor 
trig = Pin(5, Pin.OUT)
echo = Pin(8, Pin.IN)    

# The buzzer needs a crazy high frequency to sound really annoying
buzzer = PWM(Pin(1))
buzzer.freq(2730)
buzzer.duty_u16(0) 

# Setting up all the leds, slider switch and power button
mode_sw = Pin(9, Pin.IN, Pin.PULL_DOWN)
btn_power = Pin(12, Pin.IN)
led_red   = Pin(11, Pin.OUT)
led_green = Pin(13, Pin.OUT)
led_power = Pin(10, Pin.OUT)

# I2C wires so the pico can talk to the oled, frq at 40kHz
try:
    i2c = I2C(0, sda=Pin(16), scl=Pin(17), freq=400000)
except Exception as e:
    i2c = None
    print(f"[WARN] I2C init failed: {e}")

# This is the twisty knob pin
pot = ADC(26)

# before proceeding , check if the screen is actually connected and working
HAS_OLED = False
if _HAS_SSD1306 and i2c is not None:
    try:
        oled = ssd1306.SSD1306_I2C(128, 64, i2c)
        HAS_OLED = True
        print("[BOOT] OLED OK")
    except Exception as e:
        print(f"[WARN] OLED failed: {e}")


def servo_set_us(pwm_obj, us):
    """
    Sets the servo position using microsecond pulse widths.
    microPython's duty_u16() takes 0-65535 siince the PWM frequency is 50Hz 
    a full period is 20000us. Formula: (Pulse / Period) * Max_Duty.
    """
    duty = int(us / 20000.0 * 65535)
    pwm_obj.duty_u16(duty)

def angle_to_us(degrees):
    """
    Maps a physical angle 0-180 to a PWM pulse width in microseconds.
    """
    degrees = max(0, min(180, degrees))
    # 500us -->  0 degres and 2500us --> 180 deg.
    return int(500 + (degrees / 180.0) * 2000) 


def get_distance_cm():
    """
    Calculates distance using the HC-SR04 ultrasonic sensor.
    P.S. : I foudn the math below in a doc blog but I forget where.
    Sound travels at 343m/s. The calculation for distance in cm is:
    distance = (time* speed of sound) / 2
    simplified constant: 1 / (0.0343 / 2) -. 58.3.
    """
    trig.value(0)
    time.sleep_us(2)
    trig.value(1)
    time.sleep_us(10)
    trig.value(0)

    #wait for echo to start or simply wait fr pulse to go high
    t0 = time.ticks_us()
    while echo.value() == 0:
        #we use ticks_diff instead of direct subtraction
        #cause it handles wrap-around automatically
        if time.ticks_diff(time.ticks_us(), t0) > 30000:
            return 999 # took too long so nothing is there

    #measure the duration of pulse
    start = time.ticks_us()
    while echo.value() == 1:
        if time.ticks_diff(time.ticks_us(), start) > 30000:
            return 999
    stop = time.ticks_us()

    return time.ticks_diff(stop, start) / 58.0

def oled_show(line1, line2="", line3=""):
    """
    displays three lines of text on the OLED screen.
    """
    if HAS_OLED:
        oled.fill(0) #clear the old stuff first, very imp
        oled.text(str(line1)[:16], 0, 8)
        oled.text(str(line2)[:16], 0, 28)
        oled.text(str(line3)[:16], 0, 48)
        oled.show()
    else:
        #if oled is disconnected we fallbackto the console.
        print(f"[OLED] {line1} | {line2} | {line3}")

def buzzer_on():
    """activates the buzzer at 50% duty cycle."""
    buzzer.duty_u16(32768)

def buzzer_off():
    """deactivates the buzzer"""
    buzzer.duty_u16(0)


def beep(times=1, on_ms=120, off_ms=100):
    """
    gnrates a sequence of short beeps solely for feedback purposes
    """
    for _ in range(times):
        buzzer_on();  time.sleep_ms(on_ms)
        buzzer_off(); time.sleep_ms(off_ms)

def get_threshold_cm():
    """
    eadspotentiometer and maps it to a distance range.
    default is 10cm
    """
    raw = pot.read_u16()
    return 10 + int((raw / 65535.0) * 140)

def get_mode():
    """ helper function to get current mode. 1--> Launch"""
    return "LAUNCH" if mode_sw.value() == 1 else "ALaRM"


# s etting up the rules for how the turret looks around
SWEEP_MIN_DEG  = 0      
SWEEP_MAX_DEG  = 180    
SWEEP_STEP_DEG = 3 #jump 3 deg at a time
STEP_DELAY_MS  = 40     

sweep_angle = 90        
sweep_dir   = 1         # 1 means go right -1 means go left

def sweep_step():
    """
    calculates and moves the scan servo by one increment.
    when it hits the edge it turns around
    """
    global sweep_angle, sweep_dir
    sweep_angle += sweep_dir * SWEEP_STEP_DEG
    if sweep_angle >= SWEEP_MAX_DEG:     # Reverse direction logic
        sweep_angle = SWEEP_MAX_DEG
        sweep_dir = -1
    elif sweep_angle <= SWEEP_MIN_DEG:
        sweep_angle = SWEEP_MIN_DEG
        sweep_dir = 1
    servo_set_us(servo_scan, angle_to_us(sweep_angle))
    return sweep_angle

def trigger_home():
    """resets the trigger servo to the neutral/home position. --> 90"""
    servo_set_us(servo_trigger, angle_to_us(90))

def full_home():
    """sesets all servos to neutral/home pos and initialies sweep variables."""
    global sweep_angle, sweep_dir
    sweep_angle = 90
    sweep_dir   = 1
    servo_set_us(servo_scan,    angle_to_us(90))
    servo_set_us(servo_trigger, angle_to_us(90))

# I made this part so the button works better. 
# Sometimes buttons glitch and press twice super fast.
# This makesit wait a quarter second before it counts a new press.
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
            _btn_last_ms = curr_ms #reset timer after valid press
            print(f"[POWER] System is now {'ON' if system_active else 'OFF'}")
            
    _btn_prev = curr_val

# ============================================================
# Main State Machine
# ============================================================

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


# The main brain loop. It goes forever.
while True:
    check_button() # check if I pushed power

    # If I turned it off ,turn off all lights and stay sleeping
    if not system_active:
        led_power.value(0)
        led_red.value(0)
        led_green.value(0)
        buzzer_off()
        oled_show("SYSTEM OFF", "Press button")
        state = STATE_IDLE 
        time.sleep_ms(100)
        continue # skip the rest of the code and loop back to start

    led_power.value(1) # power is on

    if state == STATE_IDLE:
        # Just hanging out waiting to start scanning
        led_green.value(1)
        led_red.value(0)
        oled_show("[ IDLE ]", "System armed", f"Mode:{get_mode()}")
        time.sleep_ms(400)
        state = STATE_SCANNING
        print("[STATE] → SCANNING")

    elif state == STATE_SCANNING:
        # Traitor starts actively looking for targets
        current_angle = sweep_step()
        threshold     = get_threshold_cm() # read the knob for threshold everytime
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

        #if we detct object within our range we intitalise trigger but we
        # dont immediately lock, more about it in STATE_CONFIRM
        if dist <= threshold:
            confirm_count = 1
            detected_dist = dist
            locked_angle  = current_angle 
            state = STATE_CONFIRM
            print(f"[STATE] → CONFIRM  dist={dist:.1f}cm  angle={current_angle}deg")

        time.sleep_ms(STEP_DELAY_MS)

    elif state == STATE_CONFIRM:
        # Ultrasonic sensors often give fales low readings due to air 
        # currents or odd angles. therefore we made the decision to require 3
        # consecutive readings below the threshold before engaging the alarm.
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
            # If we see it 3 times, its real. Sound the alarm
            if confirm_count >= 3:
                state = STATE_ALERT
                print(f"[STATE] → ALERT  dist={detected_dist:.1f}cm  angle={locked_angle}deg")
        else:
            # false alarm, we go back to looking around
            confirm_count = 0
            state = STATE_SCANNING
            print("[STATE] → SCANNING")

        time.sleep_ms(STEP_DELAY_MS)

    elif state == STATE_ALERT:
        #engagement state
        led_green.value(0)
        led_red.value(1)

        mode = get_mode()

        #aim at the specific angle where the target was confirmed
        servo_set_us(servo_scan, angle_to_us(locked_angle))

        if mode == "LAUNCH":
            #fire the trigger servo
            servo_set_us(servo_trigger, angle_to_us(locked_angle))
            oled_show("!! DETeCTED !!", f"D:{detected_dist:.0f}cm Az:{locked_angle}", "LAUNCH ENaBLED")
            print(f"[ALERT] LAUnCH  dist={detected_dist:.1f}cm  angel={locked_angle}deg")
        else:
            # Just yell, dont fire
            servo_set_us(servo_trigger, angle_to_us(90))
            oled_show("!! DETECTED !!", f"D:{detected_dist:.0f}cm Az:{locked_angle}", "ALARM ONLY")
            print(f"[ALERT] Alarm   dist={detected_dist:.1f}cm  angel={locked_angle}deg")

        buzzer_on()
        time.sleep_ms(2000)
        buzzer_off()

        state = STATE_COOLDOWN
        print("[STATE] → COOLDOWN")

    elif state == STATE_COOLDOWN:
        # prevents the turret from jittering or firing immediately again.
        # also provides us with enough time to clear the area and 
        # for the motor to return to home before this it'd keep yellign and detecting
        # same obj again and again and servos would start continuously movinf around.
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