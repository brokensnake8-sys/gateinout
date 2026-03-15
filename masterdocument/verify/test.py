from gpiozero import OutputDevice
import time

relay = OutputDevice(17, active_high=False, initial_value=False)

try:
    relay.on()
    print("Relay ON di GPIO27. Tekan Ctrl+C untuk keluar.")
    while True:
        time.sleep(1)
finally:
    relay.off()
    relay.close()
    print("Relay OFF.")
