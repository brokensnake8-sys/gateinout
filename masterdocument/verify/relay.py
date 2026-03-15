"""
relay.py - Relay Controller
Dipanggil dari fingerprint_verify_v2.py saat verify match.

Usage dari luar:
    from relay import trigger_relay
    trigger_relay()
"""

import threading

try:
    from gpiozero import OutputDevice
    _relay = OutputDevice(27, active_high=False, initial_value=True)
    HAS_GPIO = True
except Exception as e:
    print(f"[RELAY] GPIO tidak tersedia: {e}")
    HAS_GPIO = False

RELAY_SECONDS = 2  # durasi relay ON (detik)


def trigger_relay():
    """Nyalakan relay RELAY_SECONDS detik lalu matikan. Non-blocking."""
    def _run():
        if HAS_GPIO:
            import time
            print(f"[RELAY] ON ({RELAY_SECONDS}s)")
            _relay.on()
            time.sleep(RELAY_SECONDS)
            _relay.off()
            print("[RELAY] OFF")
        else:
            print(f"[RELAY] Simulasi ON {RELAY_SECONDS}s (GPIO tidak tersedia)")

    threading.Thread(target=_run, daemon=True).start()


if __name__ == "__main__":
    print("Test relay...")
    trigger_relay()
    import time; time.sleep(RELAY_SECONDS + 1)
    print("Test selesai.")
