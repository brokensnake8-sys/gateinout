#!/usr/bin/env python3
"""
HaloRaga Gym Attendance — URU4500 + pyusb
Jalankan: sudo python3 uru4500_attend.py

Alur (sama persis seperti ori.js SDK):
  1. Init sensor → LED nyala
  2. Tunggu IRQ FINGER_ON (0x0101) → jari beneran ditempel
  3. Capture raw grayscale bytes dari EP 0x82
  4. Convert raw → PNG (seperti SDK menghasilkan samples[0])
  5. Encode Base64 standard (seperti Fingerprint.b64UrlTo64)
  6. POST {"finger": "<base64_png>"} ke API
"""

import usb.core, usb.util
import base64, time, struct, requests
from PIL import Image
import io

# ── Konfigurasi ───────────────────────────────────────
VENDOR_ID  = 0x05ba
PRODUCT_ID = 0x000a
API_URL    = "https://machine.haloraga.com/api/v1/attendance-via-finger"

# ── Register URU4000B ─────────────────────────────────
USB_RQ       = 0x04
CTRL_TIMEOUT = 5000
REG_HWSTAT   = 0x07
REG_MODE     = 0x4e

MODE_AWAIT_FINGER_ON  = 0x10
MODE_AWAIT_FINGER_OFF = 0x12
MODE_CAPTURE          = 0x20

IRQ_FINGER_ON  = 0x0101
IRQ_FINGER_OFF = 0x0200
IRQ_SCANPWR_ON = 0x56aa

CTRL_IN  = usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIPIENT_DEVICE | usb.util.CTRL_IN
CTRL_OUT = usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIPIENT_DEVICE | usb.util.CTRL_OUT

# ── Dimensi sensor (URU4000B) ─────────────────────────
IMG_W = 384
IMG_H = 289   # 384x289 = 110976 bytes (dari hasil pengukuran aktual)


# ══════════════════════════════════════════════════════
# USB LOW LEVEL
# ══════════════════════════════════════════════════════
def setup_device():
    dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
    if dev is None:
        raise RuntimeError("Device tidak ditemukan! Pastikan USB tercolok.")
    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except:
        pass
    dev.set_configuration()
    return dev

def reg_read(dev, reg, n=1):
    return bytes(dev.ctrl_transfer(CTRL_IN,  USB_RQ, reg, 0, n,          CTRL_TIMEOUT))

def reg_write(dev, reg, val):
    dev.ctrl_transfer(         CTRL_OUT, USB_RQ, reg, 0, bytes([val]), CTRL_TIMEOUT)

def read_irq(dev, timeout_ms=3000):
    try:
        return bytes(dev.read(0x81, 64, timeout=timeout_ms))
    except usb.core.USBTimeoutError:
        return None


# ══════════════════════════════════════════════════════
# SENSOR INIT
# ══════════════════════════════════════════════════════
def init_sensor(dev):
    """
    Inisialisasi sensor persis seperti libfprint uru4000.c:
    1. Baca HWSTAT
    2. Set bit 0x80 (power on)
    3. Restore HWSTAT
    4. Wake up device (baca 0xf0)
    5. Set MODE_AWAIT_FINGER_ON
    6. Flush semua IRQ yang tertunda (penting! ini cegah auto-capture)
    """
    print("[*] Init sensor...")

    hwstat = reg_read(dev, REG_HWSTAT)[0]
    reg_write(dev, REG_HWSTAT, hwstat | 0x80)
    time.sleep(0.05)
    reg_write(dev, REG_HWSTAT, hwstat)
    time.sleep(0.05)

    # Wake up
    reg_read(dev, 0xf0, 16)
    time.sleep(0.1)

    # Set mode tunggu jari
    reg_write(dev, REG_MODE, MODE_AWAIT_FINGER_ON)
    time.sleep(0.1)

    # ═══ PENTING: Flush semua IRQ yang tertunda di buffer ═══
    # Ini yang menyebabkan "auto capture sendiri" sebelumnya
    print("[*] Flushing IRQ buffer...")
    flushed = 0
    while True:
        irq = read_irq(dev, timeout_ms=300)
        if irq is None:
            break
        irq_type = struct.unpack('>H', irq[:2])[0]
        print(f"    Flushed IRQ: 0x{irq_type:04x}")
        flushed += 1
    print(f"[+] Flushed {flushed} IRQ. Sensor siap — LED menyala")


# ══════════════════════════════════════════════════════
# SCAN FLOW
# ══════════════════════════════════════════════════════
def wait_finger_on(dev):
    """Tunggu IRQ 0x0101 = jari beneran ditempel."""
    print("\n[~] Tempelkan jari ke sensor...")
    idle_count = 0
    while True:
        irq = read_irq(dev, timeout_ms=2000)
        if irq is None:
            idle_count += 1
            if idle_count % 5 == 0:
                print("    [~] Menunggu jari...")
            continue
        irq_type = struct.unpack('>H', irq[:2])[0]
        print(f"    IRQ: 0x{irq_type:04x}")
        if irq_type == IRQ_FINGER_ON:
            print("    [+] Jari terdeteksi!")
            return True
        # Abaikan IRQ lain (scanpwr, dll)


def capture_raw(dev):
    """
    Set MODE_CAPTURE lalu baca bulk image dari EP 0x82.
    Return: raw grayscale bytes
    """
    print("[*] Capture image...")
    reg_write(dev, REG_MODE, MODE_CAPTURE)
    time.sleep(0.05)
    try:
        raw = bytes(dev.read(0x82, 131072, timeout=10000))
        print(f"    [+] Raw bytes: {len(raw)}")
        return raw
    except usb.core.USBTimeoutError:
        print("    [!] Timeout baca image")
        return b""
    except Exception as e:
        print(f"    [!] Error: {e}")
        return b""
    finally:
        reg_write(dev, REG_MODE, MODE_AWAIT_FINGER_OFF)


def raw_to_png_b64(raw_bytes):
    """
    Konversi raw grayscale → PNG → Base64.

    Ini mereplikasi apa yang dilakukan SDK di ori.js:
        var samples = JSON.parse(s.samples);
        Fingerprint.b64UrlTo64(samples[0])
    samples[0] = PNG yang di-encode Base64URL oleh driver
    b64UrlTo64  = konversi Base64URL → Base64 standard

    Kita hasilkan langsung Base64 standard PNG.
    """
    w, h = IMG_W, IMG_H
    pixel_data = raw_bytes[:w * h]

    img = Image.frombytes('L', (w, h), pixel_data)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    png_bytes = buf.getvalue()

    b64 = base64.b64encode(png_bytes).decode()  # standard b64, bukan b64url

    print(f"    Dimensi : {w}x{h} px")
    print(f"    PNG     : {len(png_bytes)} bytes")
    print(f"    B64 len : {len(b64)} chars")
    print(f"    Prefix  : {b64[:20]}...")

    return b64, img


# ══════════════════════════════════════════════════════
# API
# ══════════════════════════════════════════════════════
def send_to_api(b64_png):
    print("\n[*] Mengirim ke API...")
    try:
        resp = requests.post(
            API_URL,
            json={"finger": b64_png},
            headers={"Content-Type": "application/json"},
            timeout=15
        )
        print(f"    HTTP: {resp.status_code}")
        return resp.json()
    except requests.exceptions.ConnectionError:
        print("    [!] Gagal konek")
    except requests.exceptions.Timeout:
        print("    [!] Timeout")
    except Exception as e:
        print(f"    [!] {e}")
    return None

def show_result(result):
    if not result:
        print("\n[✗] Tidak ada response")
        return
    data    = result.get("data") or {}
    message = result.get("message", "")
    print("\n" + "="*44)
    if data.get("name"):
        print(f"  ✓  ABSENSI BERHASIL")
        print(f"  Nama     : {data.get('name','-')}")
        print(f"  Paket    : {data.get('packet','-')}")
        print(f"  Expired  : {data.get('expDate','-')}")
        print(f"  Clock In : {data.get('clockIn','-')}")
    else:
        print(f"  ✗  GAGAL  —  {message}")
    print("="*44)


# ══════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════
def main():
    print("="*44)
    print("  HALORAGA GYM ATTENDANCE")
    print("  URU4500 + pyusb + Raspberry Pi")
    print("="*44 + "\n")

    dev = setup_device()
    print(f"[+] Device: {dev.product}\n")

    init_sensor(dev)

    try:
        while True:
            input("\n[ Tekan Enter siap scan ]\n")

            # 1. Tunggu jari beneran
            wait_finger_on(dev)

            # 2. Ambil raw image
            raw = capture_raw(dev)
            if len(raw) < 10000:
                print(f"[!] Data terlalu kecil ({len(raw)} B), scan ulang")
                reg_write(dev, REG_MODE, MODE_AWAIT_FINGER_ON)
                continue

            # 3. Konversi raw → PNG Base64 (seperti SDK)
            b64, img = raw_to_png_b64(raw)

            # 4. Simpan file debug
            img.save("last_scan.png")
            with open("last_scan_b64.txt", "w") as f:
                f.write(b64)
            print("    [+] Tersimpan: last_scan.png & last_scan_b64.txt")

            # 5. Kirim ke API
            result = send_to_api(b64)
            show_result(result)

            # 6. Reset untuk scan berikutnya
            reg_write(dev, REG_MODE, MODE_AWAIT_FINGER_ON)
            time.sleep(0.3)

    except KeyboardInterrupt:
        print("\n[*] Dihentikan.")
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        usb.util.dispose_resources(dev)
        print("[*] Device dilepas.")

if __name__ == "__main__":
    main()
