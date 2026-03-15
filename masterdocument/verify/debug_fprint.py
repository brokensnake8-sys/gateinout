"""
debug_fprint.py — Debug kenapa perlu scan berkali-kali
Jalankan: sudo python3 debug_fprint.py

Script ini akan:
1. Cek versi fprintd dan fitur yang support
2. List semua user + folder di /var/lib/fprint
3. Test IdentifyStart (1 scan langsung ketemu)
4. Kalau tidak support, test VerifyStart dan ukur waktunya
5. Print diagnosis lengkap
"""

import subprocess, os, dbus, dbus.mainloop.glib, threading, time
from gi.repository import GLib

FPRINT_DIR   = "/var/lib/fprint"
FPRINTD_BUS  = "net.reactivated.Fprint"
FPRINTD_MGR  = "/net/reactivated/Fprint/Manager"
IFACE_MGR    = "net.reactivated.Fprint.Manager"
IFACE_DEV    = "net.reactivated.Fprint.Device"

dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
loop = GLib.MainLoop()
threading.Thread(target=loop.run, daemon=True).start()

print("\n" + "="*60)
print("FINGERPRINT DEBUG TOOL")
print("="*60)

# ── 1. Versi fprintd ──────────────────────────────────────────
print("\n[1] VERSI FPRINTD:")
r = subprocess.run(["fprintd-enroll", "--version"], capture_output=True, text=True)
r2 = subprocess.run(["dpkg", "-l", "fprintd"], capture_output=True, text=True)
print(r.stdout or r.stderr or "tidak bisa cek")
for line in r2.stdout.splitlines():
    if "fprintd" in line: print(line)

# ── 2. Folder di /var/lib/fprint ─────────────────────────────
print("\n[2] FOLDER DI /var/lib/fprint:")
r = subprocess.run(["sudo", "find", FPRINT_DIR, "-mindepth", "1", "-maxdepth", "1", "-type", "d"],
                   capture_output=True, text=True)
folders = [os.path.basename(p.strip()) for p in r.stdout.splitlines() if p.strip()]
print(f"Total folder: {len(folders)}")

# Group by prefix (member yang sama)
groups = {}
for f in folders:
    prefix = f.split("_f")[0] if "_f" in f else f[:16]
    groups.setdefault(prefix, []).append(f)

print(f"Total member unik: {len(groups)}")
for prefix, flist in groups.items():
    print(f"  {prefix} → {len(flist)} folder (jari)")
    for f in flist:
        print(f"    - {f}")

# ── 3. Device info ────────────────────────────────────────────
print("\n[3] DEVICE INFO:")
try:
    bus  = dbus.SystemBus()
    mgr  = dbus.Interface(bus.get_object(FPRINTD_BUS, FPRINTD_MGR), IFACE_MGR)
    devs = mgr.GetDevices()
    print(f"Jumlah device: {len(devs)}")
    for d in devs:
        print(f"  Path: {d}")
        dev_obj = bus.get_object(FPRINTD_BUS, str(d))
        # Cek properties
        try:
            props = dbus.Interface(dev_obj, "org.freedesktop.DBus.Properties")
            for prop in ["name", "num-enroll-stages", "scan-type", "finger-present"]:
                try:
                    val = props.Get(IFACE_DEV, prop)
                    print(f"  {prop}: {val}")
                except: pass
        except Exception as e:
            print(f"  (props tidak bisa dibaca: {e})")
except Exception as e:
    print(f"ERROR: {e}")

# ── 4. Test IdentifyStart ─────────────────────────────────────
print("\n[4] TEST IdentifyStart (1-scan 1:N):")
try:
    bus    = dbus.SystemBus()
    mgr    = dbus.Interface(bus.get_object(FPRINTD_BUS, FPRINTD_MGR), IFACE_MGR)
    devs   = mgr.GetDevices()
    dev    = dbus.Interface(bus.get_object(FPRINTD_BUS, str(devs[0])), IFACE_DEV)

    result = {"done": False}

    def on_identify(matched, done):
        print(f"  IdentifyStatus: matched={matched} done={done}")
        result["matched"] = str(matched)
        result["done"]    = True

    sig = bus.add_signal_receiver(on_identify, dbus_interface=IFACE_DEV, signal_name="IdentifyStatus")

    user_list = dbus.Array([dbus.String(f) for f in folders], signature='s')
    dev.Claim("")
    dev.IdentifyStart(user_list)
    print("  ✅ IdentifyStart SUPPORT! Tempelkan jari untuk test...")
    print("  (tunggu 10 detik)")

    t = 0
    while not result["done"] and t < 10:
        time.sleep(0.5); t += 0.5

    if result["done"]:
        print(f"  MATCH: {result.get('matched', 'none')}")
    else:
        print("  Timeout / tidak ada input jari")

    try: dev.IdentifyStop()
    except: pass
    try: dev.Release()
    except: pass
    bus.remove_signal_receiver(on_identify, dbus_interface=IFACE_DEV, signal_name="IdentifyStatus")

    print("\n[DIAGNOSIS] ✅ IdentifyStart SUPPORT!")
    print("  → Solusi: ganti VerifyStart loop ke IdentifyStart")
    print("  → 1 scan fisik langsung ketemu siapa orangnya")

except Exception as e:
    print(f"  ❌ IdentifyStart TIDAK SUPPORT: {e}")
    print("\n[5] TEST VerifyStart — ukur berapa scan dibutuhkan:")

    bus    = dbus.SystemBus()
    mgr    = dbus.Interface(bus.get_object(FPRINTD_BUS, FPRINTD_MGR), IFACE_MGR)
    devs   = mgr.GetDevices()
    dev    = dbus.Interface(bus.get_object(FPRINTD_BUS, str(devs[0])), IFACE_DEV)

    result2 = {"done": False, "matched": None, "scan_count": 0}
    idx      = [0]

    def try_next():
        if idx[0] >= len(folders):
            result2["done"] = True
            return

        uid = folders[idx[0]]
        idx[0] += 1

        try: dev.Release()
        except: pass
        try: dev.Claim(uid)
        except Exception as e:
            print(f"  Claim({uid}) gagal: {e}")
            GLib.timeout_add(1, try_next)
            return

        try:
            dev.VerifyStart("any")
        except Exception as e:
            print(f"  VerifyStart gagal: {e}")
            GLib.timeout_add(1, try_next)

    def on_verify(result, done):
        r = str(result).lower()
        d = bool(done)
        uid = folders[idx[0]-1] if idx[0] > 0 else "?"

        if "verify-match" in r:
            result2["matched"]    = uid
            result2["done"]       = True
            result2["scan_count"] = idx[0]
            print(f"  ✅ MATCH: {uid} (scan ke-{idx[0]} dari {len(folders)})")
            try: dev.VerifyStop()
            except: pass
            try: dev.Release()
            except: pass
        elif "verify-no-match" in r and d:
            print(f"  ✗ No match: {uid}")
            try: dev.VerifyStop()
            except: pass
            try: dev.Release()
            except: pass
            GLib.timeout_add(1, try_next)

    sig2 = bus.add_signal_receiver(on_verify, dbus_interface=IFACE_DEV, signal_name="VerifyStatus")
    print(f"  Total folder: {len(folders)} — tempelkan jari...")
    GLib.timeout_add(100, try_next)

    t = 0
    while not result2["done"] and t < 30:
        time.sleep(0.5); t += 0.5

    bus.remove_signal_receiver(on_verify, dbus_interface=IFACE_DEV, signal_name="VerifyStatus")

    print(f"\n[DIAGNOSIS]")
    print(f"  Jumlah folder  : {len(folders)}")
    print(f"  Jumlah member  : {len(groups)}")
    print(f"  Scan dibutuhkan: {result2['scan_count']} dari {len(folders)}")
    if len(groups) == 1 and len(folders) > 1:
        print(f"  ⚠️  1 member tapi {len(folders)} folder = {len(folders)} scan!")
        print(f"  → ROOT CAUSE: app.py buat username baru tiap jari")
        print(f"  → SOLUSI: enroll ulang 1 username per member")
    else:
        print(f"  → Butuh {len(groups)} scan (1 per member) - normal")
