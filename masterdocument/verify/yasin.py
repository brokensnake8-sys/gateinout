"""
Fingerprint Attendance - Haloraga Gym Machine (V2)
Flow:
  1. Scan sidik jari → verify di RPi via D-Bus (1x scan langsung ketemu)
  2. Baca template file dari /var/lib/fprint/{matched_user}/
  3. Kirim template (base64) ke server API
  4. Tampilkan hasil dari server

Run: sudo python3 fingerprint_verify_v2.py
"""

import tkinter as tk
import threading
import requests
import base64
import subprocess
import os
import json
from datetime import datetime

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

# ── CONFIG ─────────────────────────────────────────────────────────────────────
API_URL    = "https://machine.haloraga.com/api/v1/attendance-via-finger"
FPRINT_DIR = "/var/lib/fprint"

BASE_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data scan gui")
DB_PATH    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")

# ── FPRINTD D-BUS ──────────────────────────────────────────────────────────────
FPRINTD_BUS  = "net.reactivated.Fprint"
FPRINTD_MGR  = "/net/reactivated/Fprint/Manager"
IFACE_MGR    = "net.reactivated.Fprint.Manager"
IFACE_DEV    = "net.reactivated.Fprint.Device"

BG    = "#0e1118"
CARD  = "#161b27"
BORD  = "#252d40"
BLUE  = "#2563eb"
GREEN = "#16a34a"
RED   = "#dc2626"
YEL   = "#ca8a04"
WHITE = "#f1f5f9"
GRAY  = "#475569"
LBLUE = "#60a5fa"

# ── GLIB LOOP ──────────────────────────────────────────────────────────────────
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
_GLIB_LOOP = GLib.MainLoop()
threading.Thread(target=_GLIB_LOOP.run, daemon=True).start()


# ── HELPERS ───────────────────────────────────────────────────────────────────
def get_device():
    """Ambil device fingerprint secara dinamis."""
    bus  = dbus.SystemBus()
    mgr  = dbus.Interface(bus.get_object(FPRINTD_BUS, FPRINTD_MGR), IFACE_MGR)
    devs = mgr.GetDevices()
    if not devs:
        raise RuntimeError("Tidak ada device fingerprint terdeteksi")
    path   = str(devs[0])
    device = dbus.Interface(bus.get_object(FPRINTD_BUS, path), IFACE_DEV)
    print(f"[INFO] Device: {path}")
    return bus, device

def get_fprint_users() -> list:
    """Ambil daftar user yang terdaftar di /var/lib/fprint."""
    r = subprocess.run(["sudo", "ls", FPRINT_DIR], capture_output=True, text=True)
    users = [u.strip() for u in r.stdout.splitlines() if u.strip()]
    print(f"[INFO] Fprint users: {users}")
    return users

def read_template(username: str) -> bytes:
    """
    Baca file template sidik jari dari /var/lib/fprint/{username}/
    Ini yang dikirim ke server.
    """
    user_dir = os.path.join(FPRINT_DIR, username)
    r = subprocess.run(["sudo", "find", user_dir, "-type", "f"],
                       capture_output=True, text=True)
    files = [f.strip() for f in r.stdout.splitlines() if f.strip()]
    if not files:
        print(f"[WARN] Tidak ada file template untuk {username}")
        return b""
    # Ambil semua file dan gabungkan (atau pilih yang terbesar)
    chosen = sorted(files)[-1]  # biasanya file dengan nama terbesar = yang paling baru
    print(f"[INFO] Template file: {chosen}")
    r2 = subprocess.run(["sudo", "cat", chosen], capture_output=True)
    return r2.stdout if r2.returncode == 0 else b""

def load_db() -> dict:
    if not os.path.exists(DB_PATH): return {}
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f: return json.load(f)
    except: return {}

def get_local_info(username: str) -> dict | None:
    """Cari info user di users.json berdasarkan username fprint."""
    db     = load_db()
    src    = db.get("users", db)  # support format nested maupun flat

    if username in src and isinstance(src[username], dict):
        return _norm(src[username])

    # Fuzzy match: kadang nama fprint vs nama di DB beda format
    clean = username.lower().replace("fp","",1).replace("_","").replace("-","")
    for k, v in src.items():
        if not isinstance(v, dict): continue
        kc = k.lower().replace("-","").replace("_","")
        if clean.startswith(kc[:8]) or kc in clean:
            return _norm(v)
    return None

def _norm(r: dict) -> dict:
    return {
        "name":       r.get("name",       r.get("nama",    "—")),
        "cardNumber": r.get("cardNumber", "—"),
        "packet":     r.get("packet",     r.get("paket",   "—")),
        "expDate":    r.get("expDate",    r.get("expired", "—")),
    }

def save_log(data: dict, msg="", status="BERHASIL", finger_b64=""):
    now  = datetime.now()
    path = os.path.join(BASE_DIR, now.strftime("%d%m%Y_%H%M%S"))
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "scan_result.txt"), "w", encoding="utf-8") as f:
        f.write(f"Waktu  : {now.strftime('%d-%m-%Y %H:%M:%S')}\n")
        f.write(f"Status : {status}\n")
        f.write(f"Nama   : {data.get('name','—')}\n")
        f.write(f"Paket  : {data.get('packet','—')}\n")
        f.write(f"Exp    : {data.get('expDate','—')}\n")
        f.write(f"ClockIn: {data.get('clockIn','—')}\n")
        f.write(f"Note   : {msg}\n")
    if finger_b64:
        with open(os.path.join(path, "finger_data.txt"), "w") as f:
            f.write(finger_b64)
    return path


# ── D-BUS 1:N IDENTIFIER ──────────────────────────────────────────────────────
class FprintIdentifier:
    """
    Scan fisik 1x → iterasi semua user di RAM via D-Bus VerifyStart.
    Persis cara kerja gui_app.py: sensor scan sekali,
    daemon fprintd yang compare ke tiap enrolled user tanpa scan ulang.
    """
    def __init__(self, on_progress=None):
        self._on_progress = on_progress
        self._result      = None
        self._event       = threading.Event()
        self._bus, self._dev = get_device()
        self._users       = get_fprint_users()
        self._idx         = 0
        self._current     = None
        self._awaiting    = False
        self._sig         = None

    def _p(self, msg):
        if self._on_progress: self._on_progress(msg)

    def _release(self):
        try: self._dev.VerifyStop()
        except: pass
        try: self._dev.Release()
        except: pass

    def _next(self):
        if self._idx >= len(self._users):
            self._release()
            self._finish(None, "Sidik jari tidak dikenali")
            return

        uid           = self._users[self._idx]
        self._current = uid
        self._idx    += 1
        self._awaiting = False

        self._p("Scanning... tempelkan jari")

        try: self._dev.Release()
        except: pass

        try:
            self._dev.Claim(uid)
        except Exception as e:
            print(f"[WARN] Claim({uid}): {e}")
            GLib.timeout_add(1, self._next)
            return

        try:
            self._dev.VerifyStart("any")
            self._awaiting = True
        except Exception as e:
            print(f"[WARN] VerifyStart({uid}): {e}")
            self._release()
            GLib.timeout_add(1, self._next)

    def _on_status(self, result, done):
        if not self._awaiting: return
        r = str(result).lower()

        if "verify-match" in r:
            self._awaiting = False
            uid = self._current
            self._release()
            self._finish(uid, None)

        elif "verify-no-match" in r and bool(done):
            self._awaiting = False
            self._release()
            GLib.timeout_add(1, self._next)

    def _finish(self, uid, err):
        try:
            if self._sig:
                self._bus.remove_signal_receiver(
                    self._on_status, dbus_interface=IFACE_DEV, signal_name="VerifyStatus")
        except: pass
        self._result = (uid, err)
        self._event.set()

    def run(self, timeout=20) -> str:
        if not self._users:
            raise RuntimeError(f"Tidak ada fingerprint terdaftar di {FPRINT_DIR}")

        self._p(f"Siap ({len(self._users)} user). Tempelkan jari...")

        self._sig = self._bus.add_signal_receiver(
            self._on_status, dbus_interface=IFACE_DEV, signal_name="VerifyStatus")
        GLib.timeout_add(100, self._next)

        if not self._event.wait(timeout=timeout):
            self._release()
            raise RuntimeError("Timeout — tidak ada input jari (20 detik)")

        uid, err = self._result
        if err: raise RuntimeError(err)
        return uid


# ── MAIN SCAN FLOW ─────────────────────────────────────────────────────────────
def scan_verify_and_send(on_progress=None) -> dict:
    """
    1. Verify sidik jari di RPi via D-Bus
    2. Baca template file dari /var/lib/fprint
    3. Kirim template (base64) ke server
    4. Return response dari server
    """
    def p(msg):
        if on_progress: on_progress(msg)

    # Step 1: Verify di RPi
    identifier   = FprintIdentifier(on_progress=p)
    matched_user = identifier.run(timeout=20)
    p(f"✓ Match: {matched_user}")
    print(f"[INFO] Matched user: {matched_user}")

    # Step 2: Baca template sidik jari
    p("Membaca data sidik jari...")
    template = read_template(matched_user)
    if not template:
        raise RuntimeError(f"Gagal baca template untuk {matched_user}")

    finger_b64 = base64.b64encode(template).decode("utf-8")
    p("Mengirim ke server...")

    # Step 3: Kirim ke server
    resp = requests.post(API_URL, json={"finger": finger_b64}, timeout=10)
    resp.raise_for_status()

    result = resp.json()
    result["_matched_user"]  = matched_user
    result["_finger_b64"]    = finger_b64
    result["_local_info"]    = get_local_info(matched_user)
    return result


# ── GUI ────────────────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Finger Attendance V2")
        self.geometry("400x650")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._busy    = False
        self._anim_id = None
        self._anim_i  = 0
        self._build()

    def _build(self):
        tk.Frame(self, bg=BG, height=28).pack(fill="x")
        tk.Label(self, text="HALORAGA GYM", bg=BG, fg=LBLUE,
                 font=("Courier New", 10, "bold")).pack()
        tk.Label(self, text="Fingerprint Attendance V2", bg=BG, fg=WHITE,
                 font=("Courier New", 16, "bold")).pack()
        tk.Frame(self, bg=BG, height=8).pack(fill="x")
        tk.Label(self, text="🔹 Verify di RPi → Kirim ke Server",
                 bg=BG, fg=GRAY, font=("Courier New", 8)).pack()
        tk.Frame(self, bg=BG, height=12).pack(fill="x")

        card = tk.Frame(self, bg=CARD, highlightbackground=BORD, highlightthickness=1)
        card.pack(padx=24, fill="x")
        self.canvas = tk.Canvas(card, width=140, height=140, bg=CARD, highlightthickness=0)
        self.canvas.pack(pady=24)
        self._draw_icon(GRAY)
        self.lbl_status = tk.Label(card, text="SIAP", bg=CARD, fg=WHITE,
                                   font=("Courier New", 15, "bold"))
        self.lbl_status.pack()
        self.lbl_sub = tk.Label(card, text="Tekan tombol untuk absen",
                                bg=CARD, fg=GRAY, font=("Courier New", 9), wraplength=320)
        self.lbl_sub.pack(pady=(4, 24))

        tk.Frame(self, bg=BG, height=16).pack(fill="x")
        self.btn = tk.Button(self, text="▶  SCAN SIDIK JARI",
                             bg=BLUE, fg=WHITE, font=("Courier New", 12, "bold"),
                             relief="flat", bd=0, padx=16, pady=14, cursor="hand2",
                             activebackground="#1d4ed8", activeforeground=WHITE,
                             command=self._on_scan)
        self.btn.pack(padx=24, fill="x")

        tk.Frame(self, bg=BG, height=16).pack(fill="x")
        rf = tk.Frame(self, bg=CARD, highlightbackground=BORD, highlightthickness=1)
        rf.pack(padx=24, fill="both", expand=True)
        tk.Label(rf, text="HASIL", bg=CARD, fg=GRAY,
                 font=("Courier New", 8, "bold"), anchor="w").pack(fill="x", padx=12, pady=(10, 0))

        self.rvars = {}
        for key, label in [("name","Nama"), ("cardNumber","No.Card"),
                            ("packet","Paket"), ("expDate","Exp. Date"), ("clockIn","Clock In")]:
            row = tk.Frame(rf, bg=CARD)
            row.pack(fill="x", padx=12, pady=3)
            tk.Label(row, text=f"{label:<10} :", bg=CARD, fg=GRAY,
                     font=("Courier New", 9)).pack(side="left")
            v = tk.StringVar(value="—")
            tk.Label(row, textvariable=v, bg=CARD, fg=WHITE,
                     font=("Courier New", 9, "bold")).pack(side="left", padx=6)
            self.rvars[key] = v

        tk.Frame(rf, bg=BORD, height=1).pack(fill="x", padx=12, pady=(10, 4))

        sr = tk.Frame(rf, bg=CARD)
        sr.pack(fill="x", padx=12, pady=(0, 4))
        tk.Label(sr, text="Status    :", bg=CARD, fg=GRAY,
                 font=("Courier New", 9)).pack(side="left")
        self.v_source = tk.StringVar(value="—")
        tk.Label(sr, textvariable=self.v_source, bg=CARD, fg=LBLUE,
                 font=("Courier New", 8, "bold")).pack(side="left", padx=6)

        lr = tk.Frame(rf, bg=CARD)
        lr.pack(fill="x", padx=12, pady=(0, 4))
        tk.Label(lr, text="Log       :", bg=CARD, fg=GRAY,
                 font=("Courier New", 9)).pack(side="left")
        self.v_log = tk.StringVar(value="—")
        tk.Label(lr, textvariable=self.v_log, bg=CARD, fg=LBLUE,
                 font=("Courier New", 8), wraplength=240, justify="left").pack(side="left", padx=6)

        tk.Frame(rf, bg=CARD, height=12).pack(fill="x")
        tk.Frame(self, bg=BG, height=8).pack(fill="x")
        tk.Label(self, text="RPi Verify  •  /var/lib/fprint  •  API",
                 bg=BG, fg=GRAY, font=("Courier New", 7)).pack()
        tk.Frame(self, bg=BG, height=12).pack(fill="x")

    # ── scan handler ──────────────────────────────────────────────────────────
    def _on_scan(self):
        if self._busy: return
        self._busy = True
        self.btn.config(state="disabled", text="⏳  Scanning...")
        for v in self.rvars.values(): v.set("—")
        self.v_log.set("—")
        self.v_source.set("—")
        self._set_status("Letakkan jari...", WHITE)
        self._set_sub("Siapkan jari pada scanner")
        self._start_anim()
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self):
        try:
            result = scan_verify_and_send(
                on_progress=lambda m: self.after(0, lambda msg=m: self._set_sub(msg))
            )
            self.after(0, lambda r=result: self._on_done(r))

        except requests.exceptions.ConnectionError:
            self.after(0, lambda: self._on_error("Koneksi ke server gagal"))
        except requests.exceptions.HTTPError as ex:
            code = ex.response.status_code
            try:    body = ex.response.json().get("message", str(ex))
            except: body = str(ex)
            self.after(0, lambda c=code, b=body: self._on_error(f"Server error {c}: {b}"))
        except Exception as ex:
            self.after(0, lambda m=str(ex): self._on_error(m))

    def _on_done(self, result: dict):
        self._stop_anim()
        self._busy = False
        self.btn.config(state="normal", text="▶  SCAN SIDIK JARI")

        msg        = result.get("message", "")
        data       = result.get("data") or {}
        local_info = result.get("_local_info") or {}
        matched    = result.get("_matched_user", "")
        finger_b64 = result.get("_finger_b64", "")

        # Prioritas: data dari server, fallback ke local
        name     = data.get("name",       local_info.get("name",       "—"))
        card     = data.get("cardNumber", local_info.get("cardNumber", "—"))
        packet   = data.get("packet",     local_info.get("packet",     "—"))
        expdate  = data.get("expDate",    local_info.get("expDate",    "—"))
        clockin  = data.get("clockIn",    "—")

        if data:
            self._draw_icon(GREEN)
            self._set_status("✓ BERHASIL", GREEN)
            self._set_sub(msg)
            self.v_source.set("✓ SERVER")
        else:
            self._draw_icon(YEL)
            self._set_status("Tidak Dikenali", YEL)
            self._set_sub(msg or "Tidak ditemukan di server")
            self.v_source.set("⚠ NOT FOUND")

        self.rvars["name"].set(name)
        self.rvars["cardNumber"].set(card)
        self.rvars["packet"].set(packet)
        self.rvars["expDate"].set(expdate)
        self.rvars["clockIn"].set(clockin)

        try:
            log_data = data if data else local_info
            saved = save_log(log_data, msg, "BERHASIL" if data else "TIDAK DIKENALI", finger_b64)
            self.v_log.set(os.path.relpath(saved, os.path.dirname(os.path.abspath(__file__))))
        except Exception as e:
            self.v_log.set(f"⚠ {e}")

    def _on_error(self, msg: str):
        self._stop_anim()
        self._busy = False
        self.btn.config(state="normal", text="▶  SCAN SIDIK JARI")
        self._draw_icon(RED)
        self._set_status("✗ GAGAL", RED)
        self._set_sub(msg)
        self.v_source.set("✗ ERROR")
        try:
            saved = save_log({}, msg, "GAGAL")
            self.v_log.set(os.path.relpath(saved, os.path.dirname(os.path.abspath(__file__))))
        except: pass

    # ── animation & drawing ───────────────────────────────────────────────────
    ANIM_C = [LBLUE, "#93c5fd", "#bfdbfe", "#93c5fd"]

    def _start_anim(self):
        self._anim_i = 0
        def step():
            if not self._busy: return
            self._draw_icon(self.ANIM_C[self._anim_i % 4], pulse=True)
            self._anim_i += 1
            self._anim_id = self.after(350, step)
        step()

    def _stop_anim(self):
        if self._anim_id:
            self.after_cancel(self._anim_id)
            self._anim_id = None

    def _draw_icon(self, color, pulse=False):
        self.canvas.delete("all")
        cx = cy = 70
        if pulse:
            self.canvas.create_oval(cx-62, cy-62, cx+62, cy+62,
                                    outline=color, width=1, dash=(4, 6))
        for i, r in enumerate([54, 43, 32, 22, 13]):
            self.canvas.create_arc(cx-r, cy-r, cx+r, cy+r,
                                   start=210+i*4, extent=120-i*8,
                                   style="arc", outline=color,
                                   width=2 if i==0 else 1.5)
        self.canvas.create_oval(cx-4, cy-4, cx+4, cy+4, fill=color, outline="")

    def _set_status(self, text, color=WHITE): self.lbl_status.config(text=text, fg=color)
    def _set_sub(self, text):                self.lbl_sub.config(text=text)


if __name__ == "__main__":
    print("=" * 50)
    print("HALORAGA GYM - Fingerprint Attendance V2")
    print("Verify di RPi → Kirim template ke Server")
    print("=" * 50)
    print()
    users = get_fprint_users()
    print(f"[INFO] {len(users)} user terdaftar di fprint:")
    for u in users: print(f"  - {u}")
    print()
    App().mainloop()
