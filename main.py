from machine import Pin, ADC, RTC, WDT, deepsleep
from time import sleep, sleep_ms
from umqtt import MQTTClient
import gc
import ds18x20
import onewire
import sim800
import socket
import struct
import utime


'''  TODO
remove phys leds
'''

# Modem SIM800L
modem = sim800.Modem(modem_pwkey_pin=4,
                     modem_rst_pin=5,
                     modem_power_on_pin=23,
                     modem_tx_pin=26,
                     modem_rx_pin=27)
gc.collect()

# temp ds18b20
ds_pin = Pin(0)
temp_sensor = ds18x20.DS18X20(onewire.OneWire(ds_pin))

# cap moisture sensor + cal
sm_air = 755
sm_water = 324
sm_adc = ADC(Pin(2))

# rain sensor + cal
rd_air = 1023
rd_water = 236
rd_adc = ADC(Pin(15))

# battery
bat_adc = ADC(Pin(12))
bat_adc.width(ADC.WIDTH_12BIT)
bat_adc.atten(ADC.ATTN_11DB)

# relay
relay = Pin(14, Pin.OUT)

# misc
onboard_led = Pin(13, Pin.OUT)
sensor_reads = 10
sensor_delay_ms = 200
synced_time = False
online = False
ntp_delta = 3155673600
service_retries = 5
host = "se.pool.ntp.org"
rtc = RTC()
gc.collect()

# WDT
print('enabling WDT')
sleep(5)
wdt = WDT(timeout=900000)  # 15min WDT, feed from read_sensors()
wdt.feed()


def ntp_time():
    ntp_query = bytearray(48)
    ntp_query[0] = 0x1B
    msg = None
    i = 0
    while i < service_retries:
        try:
            addr = socket.getaddrinfo(host, 123)[0][-1]
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(20)
            _ = s.sendto(ntp_query, addr)
            msg = s.recv(48)
            if msg:
                s.close()
                break
        except:
            pass
        finally:
            s.close()
        i += 1
    if msg:
        val = struct.unpack("!I", msg[40:44])[0]
        tm = utime.gmtime(val - ntp_delta)
        # only CEST
        rtc.datetime((tm[0], tm[1], tm[2], tm[6] + 1, tm[3] + 2, tm[4], tm[5], 0))
        return True
    return False


def filter_reads(data):
    lst = sorted(data)[2:-2]
    return sum(lst)/len(lst)


def temp_read():
    raw_data = []
    ds18b20 = temp_sensor.scan()[0]
    for _ in range(0, sensor_reads):
        temp_sensor.convert_temp()
        sleep_ms(50)
        raw_data.append(temp_sensor.read_temp(ds18b20))
        sleep_ms(sensor_delay_ms)
    return f'{filter_reads(raw_data):.2f}'


def cap_read(adc, air, water):
    raw_data = []
    adc.width(ADC.WIDTH_10BIT)
    adc.atten(ADC.ATTN_11DB)
    for _ in range(0, sensor_reads):
        raw_data.append(adc.read())
        sleep_ms(sensor_delay_ms)
    res = filter_reads(raw_data)
    if air < res:
        res = air
    elif water > res:
        res = water
    return_res = (air - res) * 100 / (air - water)
    return f'{return_res:.2f}'


def read_bat():
    raw_data = []
    for _ in range(0, sensor_reads):
        raw_data.append(bat_adc.read_uv()/1000000*0.975*7.665)
        sleep_ms(sensor_delay_ms)
    res = filter_reads(raw_data)
    if res < 2:
        res = 0
    return f'{res:.2f}'


def read_sensors():
    wdt.feed()
    try:
        res = {
            'battery': read_bat(),
            'temp': temp_read(),
            'soil': cap_read(sm_adc, sm_air, sm_water),
            'rain': cap_read(rd_adc, rd_air, rd_water),
            'relay': str(relay.value())
            }
    except:
        res = {
            'battery': '0',
            'temp': '0',
            'soil': '0',
            'rain': '0',
            'relay': '0',
        }
    wdt.feed()
    return res


def run_pump():
    relay.on()
    while 17 <= rtc.datetime()[4] <= 18:
        print('pump loop')
        sensors = read_sensors()
        mqtt_status = post_mqtt(sensors)
        if not mqtt_status:
            print('failed to post mqtt')
            power_down()
        if float(sensors.get('battery')) < 11.7:
            print('low voltage cut-off')
            break
        sleep(240)  # 4 min wait, 2 wdt feeds
    relay.off()


def connect_mqtt():
    wdt.feed()
    global online
    if not modem.ppp.isconnected() or not online:
        online = init_modem()
    broker = MQTTClient("", "", user="", password="", port=)
    i = 0

    if online:
        while i < service_retries:
            try:
                status = broker.connect(clean_session=False)
                if status == 1:
                    return broker
            except:
                broker = MQTTClient("", "", user="", password="", port=)
                pass
            sleep_ms(250)
            i += 1
        else:
            return False
    return False


def post_mqtt(data):
    success = False
    broker = connect_mqtt()
    for k, v in data.items():
        i = 0
        if broker:
            while i < service_retries:
                try:
                    broker.publish(f'telemetry/pump/{k}', v, qos=1)
                    success = True
                    break
                except OSError:
                    broker = connect_mqtt()
                sleep_ms(250)
                i += 1
    return success


def reset_modem(modem):
    print('modem power reset')
    modem.modem_power_on_pin_obj.off()
    sleep(2)
    modem.modem_power_on_pin_obj.on()
    sleep(5)


def init_modem():
    try:
        modem.initialize()
        # TODO: save RSSI before PPPoS setup?
        modem.ppp_connect()
        i = 0
        while not modem.ppp.isconnected():
            sleep(1)
            i += 1
            if i > 25:
                reset_modem(modem)
                return False
    except:
        reset_modem(modem)
        return False
    return True


def power_down():
    relay.off()
    print('going to sleep')
    sleep(3)
    deepsleep(300000)  # 5 min deep sleep


if __name__ == "__main__":
    print('wait for tty')
    sleep(3)
    online = init_modem()
    wdt.feed()

    if online:
        synced_time = ntp_time()
        print(rtc.datetime())
        sensors = read_sensors()
        mqtt_status = post_mqtt(sensors)

        if synced_time and float(sensors.get('battery')) > 11.9:
            if 17 <= rtc.datetime()[4] <= 18:
                run_pump()
    power_down()

