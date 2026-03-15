"""
Fingerprint Attendance - Haloraga Gym Machine (V2 - With Local DB)
Flow: 
  1. Scan finger → D-Bus VerifyStart (1x scan fisik, iterasi semua user di memori)
  2. Langsung ambil data dari database lokal (users.json)
  3. Tampilkan info user di GUI
  4. Kirim ke API untuk attendance record

Improvement dari V1:
  - ✅ INSTANT identification (D-Bus VerifyStart, bukan fprintd-identify/verify loop)
  - ✅ 1x scan fisik langsung ketemu - sensor scan sekali, iterasi user di RAM
  - ✅ Database lokal untuk data caching
  - ✅ Works offline (fallback mechanism)
  - ✅ Auto-sync dengan API

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
API_URL   = "https://machine.haloraga.com/api/v1/attendance-via-finger"
API_BASE  = "https://machine.haloraga.com/api/v1"
TEMP_USER = "fp_attend_tmp"

BASE_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data scan gui")
DB_PATH   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")

# ── FPRINTD D-BUS CONFIG ───────────────────────────────────────────────────────
FPRINTD_BUS       = "net.reactivated.Fprint"
FPRINTD_MGR_PATH  = "/net/reactivated/Fprint/Manager"
FPRINTD_MGR_IFACE = "net.reactivated.Fprint.Manager"
DEVICE_IFACE      = "net.reactivated.Fprint.Device"

def get_device_path() -> str:
    """Resolusi path device secara dinamis via GetDevices() — tidak hardcode."""
    bus = dbus.SystemBus()
    mgr_obj = bus.get_object(FPRINTD_BUS, FPRINTD_MGR_PATH)
    mgr = dbus.Interface(mgr_obj, FPRINTD_MGR_IFACE)
    devices = mgr.GetDevices()
    if not devices:
        raise RuntimeError("Tidak ada device fingerprint terdeteksi oleh fprintd.")
    return str(devices[0])

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


# ── GLIB LOOP (jalan di background thread, wajib untuk D-Bus signal) ──────────
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
_GLIB_LOOP = GLib.MainLoop()

def _start_glib():
    try:
        _GLIB_LOOP.run()
    except Exception:
        pass

threading.Thread(target=_start_glib, daemon=True).start()


# ── DATABASE HELPER ────────────────────────────────────────────────────────────
def load_local_db():
    """Load database lokal users.json"""
    if not os.path.exists(DB_PATH):
        return {}
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERROR] Failed to load local DB: {e}")
        return {}

def save_local_db(data):
    """Save database lokal users.json"""
    try:
        with open(DB_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[ERROR] Failed to save local DB: {e}")

def get_all_user_ids() -> list:
    """Ambil semua user_id dari users.json"""
    db = load_local_db()
    # Support dua format: flat {uid: {...}} atau nested {"users": {uid: {...}}}
    if "users" in db and isinstance(db["users"], dict):
        return sorted(list(db["users"].keys()))
    # Format flat - filter out non-dict values
    return sorted([k for k, v in db.items() if isinstance(v, dict)])

def get_user_info(username: str) -> dict:
    """
    Ambil info user dari database lokal berdasarkan username/user_id.
    Support format nested {"users": {...}} dari app.py (zip).
    """
    db = load_local_db()

    # Coba format nested dulu (dari app.py zip)
    nested = db.get("users", {})
    if username in nested:
        raw = nested[username]
        # Normalisasi field name supaya GUI bisa tampilkan
        return {
            "name":       raw.get("nama",          raw.get("name",       "—")),
            "cardNumber": raw.get("cardNumber",     "—"),
            "packet":     raw.get("paket",          raw.get("packet",     "—")),
            "expDate":    raw.get("expired",        raw.get("expDate",    "—")),
            "lokasi":     raw.get("lokasi_daftar",  "—"),
        }

    # Coba format flat
    if username in db and isinstance(db[username], dict):
        raw = db[username]
        return {
            "name":       raw.get("name",     raw.get("nama",   "—")),
            "cardNumber": raw.get("cardNumber","—"),
            "packet":     raw.get("packet",   raw.get("paket",  "—")),
            "expDate":    raw.get("expDate",  raw.get("expired","—")),
        }

    return None

def update_user_cache(user_id: str, member_data: dict):
    """Update cache user di database lokal"""
    db = load_local_db()
    # Simpan di format flat untuk cache API
    db[user_id] = {
        "name":       member_data.get("name",       "—"),
        "cardNumber": member_data.get("cardNumber", "—"),
        "packet":     member_data.get("packet",     "—"),
        "expDate":    member_data.get("expDate",    "—"),
        "last_updated": datetime.now().isoformat()
    }
    save_local_db(db)
    print(f"[INFO] Updated local cache for {user_id}")


# ── LOG HELPER ────────────────────────────────────────────────────────────────
def save_scan_log(data: dict, message: str = "",
                  status: str = "BERHASIL", finger_b64: str = "") -> str:
    now         = datetime.now()
    folder_name = now.strftime("%d%m%Y_%H%M%S")
    folder_path = os.path.join(BASE_DIR, folder_name)
    os.makedirs(folder_path, exist_ok=True)

    with open(os.path.join(folder_path, "scan_result.txt"), "w", encoding="utf-8") as f:
        f.write("=" * 44 + "\n")
        f.write("   HALORAGA GYM — Fingerprint Attendance\n")
        f.write("=" * 44 + "\n")
        f.write(f"Waktu Scan  : {now.strftime('%d-%m-%Y %H:%M:%S')}\n")
        f.write(f"Status      : {status}\n")
        f.write("-" * 44 + "\n")
        f.write(f"Nama        : {data.get('name',    data.get('nama',   '—'))}\n")
        f.write(f"Paket       : {data.get('packet',  data.get('paket',  '—'))}\n")
        f.write(f"Exp. Date   : {data.get('expDate', data.get('expired','—'))}\n")
        f.write(f"Clock In    : {data.get('clockIn', '—')}\n")
        f.write("-" * 44 + "\n")
        f.write(f"Keterangan  : {message}\n")
        f.write("=" * 44 + "\n")

    if finger_b64:
        with open(os.path.join(folder_path, "finger_data.txt"), "w", encoding="utf-8") as f:
            f.write(finger_b64)

    return folder_path


# ── CORE: D-BUS 1:N IDENTIFY ─────────────────────────────────────────────────
class FprintIdentifier:
    """
    Identifikasi 1:N via D-Bus VerifyStart.
    Cara kerja persis gui_app.py:
      - Scan fisik SEKALI → gambar jari disimpan di daemon fprintd
      - Iterasi tiap user: Claim → VerifyStart("any")
      - Kalau verify-no-match: Release, lanjut user berikutnya (tanpa scan ulang!)
      - Kalau verify-match: ketemu! return user_id itu
    """

    def __init__(self, user_ids: list, on_progress=None):
        self.user_ids    = user_ids
        self.on_progress = on_progress
        self._result     = None   # (user_id, error_msg)
        self._done_event = threading.Event()

        self._bus    = dbus.SystemBus()
        _dev_path    = get_device_path()
        self._device = dbus.Interface(
            self._bus.get_object(FPRINTD_BUS, _dev_path),
            DEVICE_IFACE
        )
        self._sig       = None
        self._idx       = 0
        self._current   = None
        self._awaiting  = False

    def _progress(self, msg):
        if self.on_progress:
            self.on_progress(msg)

    def _release(self):
        try:
            self._device.VerifyStop()
        except Exception:
            pass
        try:
            self._device.Release()
        except Exception:
            pass

    def _kick_next(self):
        """Coba user berikutnya. Dipanggil dari GLib thread."""
        if self._idx >= len(self.user_ids):
            # Semua user sudah dicoba, tidak ada yang match
            self._release()
            self._finish(None, "Sidik jari tidak dikenali")
            return

        uid = self.user_ids[self._idx]
        self._current  = uid
        self._idx     += 1
        self._awaiting = False

        self._progress(f"Mencocokkan... ({self._idx}/{len(self.user_ids)})")

        # Release dulu sebelum claim user lain
        try:
            self._device.Release()
        except Exception:
            pass

        try:
            self._device.Claim(uid)
        except Exception as e:
            print(f"[WARN] Claim({uid}) gagal: {e}")
            GLib.timeout_add(1, self._kick_next)
            return

        try:
            self._device.VerifyStart("any")
            self._awaiting = True
        except Exception as e:
            print(f"[WARN] VerifyStart gagal untuk {uid}: {e}")
            self._release()
            GLib.timeout_add(1, self._kick_next)

    def _on_verify_status(self, result, done):
        if not self._awaiting:
            return

        r = str(result).lower()
        d = bool(done)

        if "verify-match" in r:
            self._awaiting = False
            uid = self._current
            self._release()
            self._finish(uid, None)
            return

        if "verify-no-match" in r and d:
            # Tidak match untuk user ini, coba berikutnya
            self._awaiting = False
            self._release()
            GLib.timeout_add(1, self._kick_next)

    def _finish(self, uid, error):
        # Disconnect signal
        try:
            if self._sig:
                self._bus.remove_signal_receiver(
                    self._on_verify_status,
                    dbus_interface=DEVICE_IFACE,
                    signal_name="VerifyStatus"
                )
        except Exception:
            pass

        self._result = (uid, error)
        self._done_event.set()

    def run(self, timeout=20) -> str:
        """
        Mulai identifikasi. Blocking sampai match atau timeout.
        Return: user_id yang match
        Raise RuntimeError kalau tidak match atau error
        """
        if not self.user_ids:
            raise RuntimeError("Tidak ada user terdaftar di database")

        self._progress("Letakkan jari pada scanner...")

        # Daftarkan signal receiver
        self._sig = self._bus.add_signal_receiver(
            self._on_verify_status,
            dbus_interface=DEVICE_IFACE,
            signal_name="VerifyStatus"
        )

        # Mulai dari user pertama
        GLib.timeout_add(100, self._kick_next)

        # Tunggu hasil (blocking di thread ini, GLib loop jalan di thread lain)
        if not self._done_event.wait(timeout=timeout):
            self._release()
            raise RuntimeError("Timeout — tidak ada input jari dalam 20 detik")

        uid, error = self._result

        if error:
            raise RuntimeError(error)

        return uid


def scan_and_identify_user(on_progress=None) -> tuple:
    """
    Identifikasi sidik jari menggunakan D-Bus VerifyStart (1:N).
    1x scan fisik → langsung ketemu siapa orangnya.

    Return: (matched_user_id, template_bytes, user_info_dict)
    """
    user_ids = get_all_user_ids()

    if not user_ids:
        raise RuntimeError("Tidak ada user terdaftar di database lokal")

    def progress(msg):
        if on_progress:
            on_progress(msg)

    progress(f"Siap ({len(user_ids)} user terdaftar)...")

    # ✅ D-Bus identify — 1x scan fisik, iterasi semua user di RAM
    identifier = FprintIdentifier(user_ids, on_progress=progress)
    matched_user = identifier.run(timeout=20)

    progress(f"✓ Match: {matched_user}")

    # Ambil template file dari /var/lib/fprint untuk dikirim ke API
    base_dir  = "/var/lib/fprint"
    user_dir  = os.path.join(base_dir, matched_user)
    template  = b""

    if os.path.isdir(user_dir):
        find = subprocess.run(
            ["sudo", "find", user_dir, "-type", "f"],
            capture_output=True, text=True
        )
        fp_files = [f.strip() for f in find.stdout.splitlines() if f.strip()]
        if fp_files:
            read = subprocess.run(["sudo", "cat", fp_files[0]], capture_output=True)
            if read.returncode == 0 and read.stdout:
                template = read.stdout

    # Ambil info user dari database lokal
    user_info = get_user_info(matched_user)

    if user_info:
        progress(f"✓ Data: {user_info.get('name', matched_user)}")
    else:
        progress(f"⚠ Cache lokal kosong untuk {matched_user}")

    return (matched_user, template, user_info)


def send_to_api(finger_b64: str) -> dict:
    """Kirim fingerprint ke API untuk attendance record"""
    resp = requests.post(
        API_URL,
        json={"finger": finger_b64},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


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
        tk.Label(self, text="🔹 D-Bus 1:N Identify", bg=BG, fg=GRAY,
                 font=("Courier New", 8)).pack()
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
        for key, label in [("name","Nama"),("cardNumber","No.Card"),
                            ("packet","Paket"),("expDate","Exp. Date"),
                            ("clockIn","Clock In")]:
            row = tk.Frame(rf, bg=CARD)
            row.pack(fill="x", padx=12, pady=3)
            tk.Label(row, text=f"{label:<10} :", bg=CARD, fg=GRAY,
                     font=("Courier New", 9)).pack(side="left")
            v = tk.StringVar(value="—")
            tk.Label(row, textvariable=v, bg=CARD, fg=WHITE,
                     font=("Courier New", 9, "bold")).pack(side="left", padx=6)
            self.rvars[key] = v

        tk.Frame(rf, bg=BORD, height=1).pack(fill="x", padx=12, pady=(10, 4))

        status_row = tk.Frame(rf, bg=CARD)
        status_row.pack(fill="x", padx=12, pady=(0, 4))
        tk.Label(status_row, text="Status    :", bg=CARD, fg=GRAY,
                 font=("Courier New", 9)).pack(side="left")
        self.v_source = tk.StringVar(value="—")
        tk.Label(status_row, textvariable=self.v_source, bg=CARD, fg=LBLUE,
                 font=("Courier New", 8, "bold")).pack(side="left", padx=6)

        log_row = tk.Frame(rf, bg=CARD)
        log_row.pack(fill="x", padx=12, pady=(0, 4))
        tk.Label(log_row, text="Log       :", bg=CARD, fg=GRAY,
                 font=("Courier New", 9)).pack(side="left")
        self.v_log = tk.StringVar(value="—")
        tk.Label(log_row, textvariable=self.v_log, bg=CARD, fg=LBLUE,
                 font=("Courier New", 8), wraplength=240, justify="left").pack(side="left", padx=6)

        tk.Frame(rf, bg=CARD, height=12).pack(fill="x")
        tk.Frame(self, bg=BG, height=8).pack(fill="x")
        tk.Label(self, text="D-Bus 1:N Identify  •  Local DB",
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
        finger_b64  = ""
        matched_user = None
        local_info   = None

        try:
            # Step 1: D-Bus identify — 1x scan fisik langsung ketemu
            matched_user, template, local_info = scan_and_identify_user(
                on_progress=lambda m: self.after(0, lambda msg=m: self._set_sub(msg))
            )

            finger_b64 = base64.b64encode(template).decode("utf-8") if template else ""

            # Step 2: Tampilkan data lokal dulu (instant feedback)
            if local_info:
                self.after(0, lambda: self._show_local_data(matched_user, local_info))
            else:
                self.after(0, lambda: self._set_sub(f"User: {matched_user} (cache kosong)"))

            # Step 3: Kirim ke API
            self.after(0, lambda: self._set_sub("Mengirim ke server..."))
            resp = send_to_api(finger_b64)

            # Step 4: Update dengan data dari API
            self.after(0, lambda r=resp, b=finger_b64, u=matched_user, l=local_info:
                      self._on_success(r, b, u, l))

        except TimeoutError:
            self.after(0, lambda b=finger_b64: self._on_error("Timeout — tidak ada input jari", b))
        except requests.exceptions.ConnectionError:
            if local_info:
                self.after(0, lambda u=matched_user, l=local_info, b=finger_b64:
                          self._on_local_only(u, l, b, "API tidak tersedia"))
            else:
                self.after(0, lambda b=finger_b64: self._on_error("Koneksi ke server gagal", b))
        except requests.exceptions.HTTPError as ex:
            code = ex.response.status_code
            body = ""
            try: body = ex.response.json().get("message", "")
            except Exception: pass
            if local_info:
                self.after(0, lambda u=matched_user, l=local_info, b=finger_b64, c=code, bd=body:
                          self._on_local_only(u, l, b, f"API error {c}: {bd}"))
            else:
                self.after(0, lambda c=code, bd=body, b=finger_b64:
                          self._on_error(f"HTTP {c}: {bd}", b))
        except Exception as ex:
            m = str(ex)
            self.after(0, lambda msg=m, b=finger_b64: self._on_error(msg, b))

    def _show_local_data(self, username: str, user_info: dict):
        self._draw_icon(LBLUE)
        self._set_status("✓ DIKENALI", LBLUE)
        self._set_sub(f"User: {username}")
        self.rvars["name"].set(user_info.get("name", "—"))
        self.rvars["cardNumber"].set(user_info.get("cardNumber", "—"))
        self.rvars["packet"].set(user_info.get("packet", "—"))
        self.rvars["expDate"].set(user_info.get("expDate", "—"))
        self.rvars["clockIn"].set("⏳ Menunggu API...")
        self.v_source.set("📂 LOCAL CACHE")

    def _on_success(self, resp, finger_b64: str, matched_user: str, local_info: dict):
        self._stop_anim()
        self._busy = False
        self.btn.config(state="normal", text="▶  SCAN SIDIK JARI")
        msg  = resp.get("message", "")
        data = resp.get("data") or {}

        if data:
            self._draw_icon(GREEN)
            self._set_status("✓ BERHASIL", GREEN)
            self._set_sub(msg)
            self.rvars["name"].set(data.get("name", "—"))
            self.rvars["cardNumber"].set(data.get("cardNumber", "—"))
            self.rvars["packet"].set(data.get("packet", "—"))
            self.rvars["expDate"].set(data.get("expDate", "—"))
            self.rvars["clockIn"].set(data.get("clockIn", "—"))
            self.v_source.set("✓ API CONFIRMED")
            if matched_user:
                update_user_cache(matched_user, data)
            self._save_log(data, msg, "BERHASIL", finger_b64)
        else:
            self._draw_icon(YEL)
            self._set_status("Tidak Dikenali", YEL)
            self._set_sub(msg or "Sidik jari tidak ditemukan di server")
            self.v_source.set("⚠ NOT IN API")
            self._save_log({}, msg or "Tidak ditemukan di server", "TIDAK DIKENALI", finger_b64)

    def _on_local_only(self, username: str, local_info: dict, finger_b64: str, error_msg: str):
        self._stop_anim()
        self._busy = False
        self.btn.config(state="normal", text="▶  SCAN SIDIK JARI")
        self._draw_icon(YEL)
        self._set_status("⚠ LOCAL ONLY", YEL)
        self._set_sub(f"User: {username} (API: {error_msg})")
        self.rvars["name"].set(local_info.get("name", "—"))
        self.rvars["cardNumber"].set(local_info.get("cardNumber", "—"))
        self.rvars["packet"].set(local_info.get("packet", "—"))
        self.rvars["expDate"].set(local_info.get("expDate", "—"))
        self.rvars["clockIn"].set("✗ API gagal")
        self.v_source.set("📂 LOCAL CACHE ONLY")
        self._save_log(local_info, f"LOCAL ONLY - {error_msg}", "LOCAL_ONLY", finger_b64)

    def _on_error(self, msg: str, finger_b64: str = ""):
        self._stop_anim()
        self._busy = False
        self.btn.config(state="normal", text="▶  SCAN SIDIK JARI")
        self._draw_icon(RED)
        self._set_status("✗ GAGAL", RED)
        self._set_sub(msg)
        self.v_source.set("✗ ERROR")
        self._save_log({}, msg, "GAGAL", finger_b64)

    def _save_log(self, data: dict, message: str, status: str, finger_b64: str):
        try:
            saved_path = save_scan_log(data, message=message,
                                       status=status, finger_b64=finger_b64)
            rel = os.path.relpath(saved_path, os.path.dirname(os.path.abspath(__file__)))
            self.v_log.set(rel)
        except Exception as log_err:
            self.v_log.set(f"⚠ Gagal simpan: {log_err}")

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
    def _set_sub(self, text): self.lbl_sub.config(text=text)


if __name__ == "__main__":
    print("=" * 50)
    print("HALORAGA GYM - Fingerprint Attendance V2")
    print("D-Bus 1:N Identify  •  Local DB Cache")
    print("=" * 50)
    print()
    db = load_local_db()
    users = db.get("users", db)
    user_count = len([k for k, v in users.items() if isinstance(v, dict)])
    print(f"[INFO] Local DB loaded: {user_count} users")
    print()
    App().mainloop()
