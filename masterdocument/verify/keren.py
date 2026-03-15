"""
Fingerprint Attendance V2 — Gate IN / Gate OUT
- Fullscreen untuk LCD 7 inch RPi
- Auto-scan, 2 detik tampil hasil lalu scan lagi
- WiFi status + IP di GUI
- Tombol close + stop

Run: sudo python3 fingerprint_verify_v2.py
"""

import tkinter as tk
import threading
import requests
import base64
import subprocess
import os
import json
import socket
from datetime import datetime

from fpwrap import identify_from_dir

def trigger_relay(): pass

# ── CONFIG — baca dari config.json ───────────────────────────────────────────
_CFG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
try:
    with open(_CFG_PATH) as _f:
        _CFG = json.load(_f)
    print(f"[CONFIG] Loaded: {_CFG_PATH}")
except Exception as _e:
    print(f"[CONFIG] Gagal baca config.json, pakai default: {_e}")
    _CFG = {}

GATE_MODE      = _CFG.get("GATE_MODE",      "IN")
API_URL        = _CFG.get("API_URL",         "https://machine.haloraga.com/api/v1/attendance-via-finger")
FPRINT_DIR     = _CFG.get("FPRINT_DIR",      "/var/lib/fprint")
STATUS_SERVER  = _CFG.get("STATUS_SERVER",   "http://localhost:5050")
RESULT_SECONDS = _CFG.get("RESULT_SECONDS",  2000)
BASE_DIR       = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data scan gui")

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
ORNG  = "#ea580c"

GATE_COLOR = GREEN if GATE_MODE == "IN" else ORNG
GATE_LABEL = "GATE MASUK" if GATE_MODE == "IN" else "GATE KELUAR"


# ── NETWORK HELPERS ───────────────────────────────────────────────────────────
def get_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "Tidak tersambung"

def get_wifi_ssid() -> str:
    try:
        r = subprocess.run(["iwgetid", "-r"], capture_output=True, text=True)
        ssid = r.stdout.strip()
        return ssid if ssid else "Tidak terhubung WiFi"
    except:
        return "—"


# ── STATUS HELPERS ─────────────────────────────────────────────────────────────
def get_user_status(uid: str) -> str:
    try:
        resp = requests.get(f"{STATUS_SERVER}/status/{uid}", timeout=3)
        return resp.json().get("status", "OUT")
    except Exception as e:
        print(f"[WARN] get_user_status: {e}")
        return "OUT"

def set_user_status(uid: str, status: str, name: str = ""):
    try:
        requests.post(f"{STATUS_SERVER}/status/{uid}", json={
            "status":     status,
            "name":       name,
            "last_event": datetime.now().isoformat(timespec="seconds")
        }, timeout=3)
    except Exception as e:
        print(f"[WARN] set_user_status: {e}")

def check_gate_allowed(uid: str) -> tuple:
    current = get_user_status(uid)
    if GATE_MODE == "IN":
        if current == "OUT":
            return True, "Silakan masuk"
        else:
            return False, "Anda sudah TAP-IN\nSilakan TAP-OUT dulu di gate keluar"
    elif GATE_MODE == "OUT":
        if current == "IN":
            return True, "Silakan keluar"
        else:
            return False, "Anda belum TAP-IN\nSilakan masuk lewat gate masuk dulu"
    return False, f"GATE_MODE tidak valid: {GATE_MODE}"


# ── API ───────────────────────────────────────────────────────────────────────
def read_template(uid: str) -> bytes:
    user_dir = os.path.join(FPRINT_DIR, uid)
    r = subprocess.run(["sudo", "find", user_dir, "-type", "f"],
                       capture_output=True, text=True)
    files = sorted([f.strip() for f in r.stdout.splitlines() if f.strip()])
    if not files: return b""
    r2 = subprocess.run(["sudo", "cat", files[0]], capture_output=True)
    return r2.stdout if r2.returncode == 0 else b""

def send_to_api(uid: str) -> dict:
    template = read_template(uid)
    if not template:
        raise RuntimeError(f"Gagal baca template: {uid}")
    finger_b64 = base64.b64encode(template).decode()
    resp = requests.post(API_URL, json={"finger": finger_b64}, timeout=10)
    resp.raise_for_status()
    result = resp.json()
    result["_finger_b64"] = finger_b64
    return result

def save_log(data: dict, msg="", status="BERHASIL", finger_b64=""):
    now  = datetime.now()
    path = os.path.join(BASE_DIR, now.strftime("%d%m%Y_%H%M%S"))
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "scan_result.txt"), "w", encoding="utf-8") as f:
        f.write(f"Waktu  : {now.strftime('%d-%m-%Y %H:%M:%S')}\n")
        f.write(f"Gate   : {GATE_MODE}\n")
        f.write(f"Status : {status}\n")
        f.write(f"Nama   : {data.get('name','—')}\n")
        f.write(f"Paket  : {data.get('packet','—')}\n")
        f.write(f"Exp    : {data.get('expDate','—')}\n")
        f.write(f"ClockIn: {data.get('clockIn','—')}\n")
        f.write(f"Note   : {msg}\n")
    if finger_b64:
        with open(os.path.join(path, "finger_data.txt"), "w") as f:
            f.write(finger_b64)


# ── SCANNER ────────────────────────────────────────────────────────────────────
def scan_once(on_progress=None):
    if on_progress: on_progress("Tempelkan jari pada scanner...")
    return identify_from_dir(FPRINT_DIR)


# ── GUI ────────────────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Finger Attendance — {GATE_LABEL}")
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Fullscreen
        self.attributes("-fullscreen", True)
        self.update_idletasks()
        self._W = self.winfo_screenwidth()
        self._H = self.winfo_screenheight()

        self._anim_id  = None
        self._anim_i   = 0
        self._scanning = False
        self._build()
        self._update_network()
        self.after(500, self._start_scan)

    def _on_close(self):
        self._scanning = False
        self.destroy()

    def _build(self):
        # ── Top bar ───────────────────────────────────────────────────────────
        top = tk.Frame(self, bg="#0a0d13", height=36)
        top.pack(fill="x")
        top.pack_propagate(False)

        tk.Label(top, text="HALORAGA GYM", bg="#0a0d13", fg=LBLUE,
                 font=("Courier New", 11, "bold")).pack(side="left", padx=12)

        # Tombol close di kanan atas
        tk.Button(top, text="✕", bg="#0a0d13", fg=GRAY,
                  font=("Courier New", 13, "bold"), relief="flat", bd=0,
                  activebackground=RED, activeforeground=WHITE,
                  cursor="hand2", command=self._on_close).pack(side="right", padx=8)

        # WiFi + IP
        self.lbl_net = tk.Label(top, text="Memuat...", bg="#0a0d13", fg=GRAY,
                                font=("Courier New", 8))
        self.lbl_net.pack(side="right", padx=12)

        # ── Gate badge ────────────────────────────────────────────────────────
        badge = tk.Frame(self, bg=GATE_COLOR, height=38)
        badge.pack(fill="x")
        badge.pack_propagate(False)
        tk.Label(badge, text=f"  {GATE_LABEL}  ", bg=GATE_COLOR, fg=WHITE,
                 font=("Courier New", 13, "bold")).pack(expand=True)

        # ── Main content ──────────────────────────────────────────────────────
        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True, padx=20, pady=10)

        # Kiri: fingerprint icon + status
        left = tk.Frame(main, bg=CARD, highlightbackground=BORD, highlightthickness=1)
        left.pack(side="left", fill="both", expand=True, padx=(0,10))

        icon_size = min(self._W // 4, 160)
        self.canvas = tk.Canvas(left, width=icon_size, height=icon_size,
                                bg=CARD, highlightthickness=0)
        self.canvas.pack(pady=(20, 10))
        self._icon_size = icon_size
        self._draw_icon(GRAY)

        self.lbl_status = tk.Label(left, text="MEMULAI...", bg=CARD, fg=WHITE,
                                   font=("Courier New", 18, "bold"))
        self.lbl_status.pack()
        self.lbl_sub = tk.Label(left, text="Inisialisasi...",
                                bg=CARD, fg=GRAY, font=("Courier New", 10),
                                wraplength=int(self._W * 0.4))
        self.lbl_sub.pack(pady=(4, 16))

        # Tombol stop/start
        self.btn = tk.Button(left, text="⏹  STOP",
                             bg=RED, fg=WHITE, font=("Courier New", 12, "bold"),
                             relief="flat", bd=0, padx=16, pady=12,
                             cursor="hand2", activebackground="#b91c1c",
                             command=self._toggle_scan)
        self.btn.pack(padx=20, fill="x", pady=(0, 20))

        # Kanan: hasil scan
        right = tk.Frame(main, bg=CARD, highlightbackground=BORD, highlightthickness=1)
        right.pack(side="right", fill="both", expand=True)

        tk.Label(right, text="HASIL SCAN", bg=CARD, fg=GRAY,
                 font=("Courier New", 9, "bold"), anchor="w").pack(fill="x", padx=16, pady=(14,0))

        self.rvars = {}
        for key, label in [("name","Nama"), ("cardNumber","No.Card"),
                            ("packet","Paket"), ("expDate","Exp. Date"),
                            ("clockIn","Clock In")]:
            row = tk.Frame(right, bg=CARD)
            row.pack(fill="x", padx=16, pady=4)
            tk.Label(row, text=f"{label:<10} :", bg=CARD, fg=GRAY,
                     font=("Courier New", 10)).pack(side="left")
            v = tk.StringVar(value="—")
            tk.Label(row, textvariable=v, bg=CARD, fg=WHITE,
                     font=("Courier New", 10, "bold")).pack(side="left", padx=8)
            self.rvars[key] = v

        tk.Frame(right, bg=BORD, height=1).pack(fill="x", padx=16, pady=(10,4))

        sr = tk.Frame(right, bg=CARD)
        sr.pack(fill="x", padx=16, pady=(0,4))
        tk.Label(sr, text="Status    :", bg=CARD, fg=GRAY,
                 font=("Courier New", 10)).pack(side="left")
        self.v_source = tk.StringVar(value="—")
        tk.Label(sr, textvariable=self.v_source, bg=CARD, fg=LBLUE,
                 font=("Courier New", 9, "bold")).pack(side="left", padx=8)

        # ── Bottom bar ────────────────────────────────────────────────────────
        bot = tk.Frame(self, bg="#0a0d13", height=28)
        bot.pack(fill="x", side="bottom")
        bot.pack_propagate(False)
        tk.Label(bot, text=f"Auto-scan  •  {GATE_LABEL}  •  Haloraga Gym",
                 bg="#0a0d13", fg=GRAY, font=("Courier New", 7)).pack(expand=True)

    def _update_network(self):
        """Update WiFi SSID dan IP setiap 10 detik."""
        ip   = get_ip()
        ssid = get_wifi_ssid()
        self.lbl_net.config(text=f"📶 {ssid}  |  {ip}")
        self.after(10000, self._update_network)

    # ── scan ──────────────────────────────────────────────────────────────────
    def _start_scan(self):
        if self._scanning: return
        self._scanning = True
        self.btn.config(text="⏹  STOP", bg=RED, activebackground="#b91c1c")
        self._set_status("SCANNING", LBLUE)
        self._set_sub("Tempelkan jari pada scanner")
        self._start_anim()
        self._scan_loop()

    def _scan_loop(self):
        if not self._scanning: return
        threading.Thread(target=self._do_scan_once, daemon=True).start()

    def _do_scan_once(self):
        try:
            matched_path = scan_once(
                on_progress=lambda m: self.after(0, lambda msg=m: self._set_sub(msg))
            )
            if matched_path:
                parts = matched_path.replace(FPRINT_DIR, "").strip("/").split("/")
                uid   = parts[0] if parts else matched_path
                self.after(0, lambda u=uid: self._handle_match(u))
            else:
                if self._scanning:
                    self.after(200, self._scan_loop)
        except Exception as ex:
            print(f"[ERROR] scan: {ex}")
            if self._scanning:
                self.after(1000, self._scan_loop)

    def _stop_scan(self):
        if not self._scanning: return
        self._scanning = False
        self._stop_anim()
        self.btn.config(text="▶  START", bg=BLUE, activebackground="#1d4ed8")
        self._set_status("BERHENTI", GRAY)
        self._set_sub("Tekan START untuk scan")
        self._draw_icon(GRAY)

    def _toggle_scan(self):
        if self._scanning: self._stop_scan()
        else: self._start_scan()

    # ── match ─────────────────────────────────────────────────────────────────
    def _handle_match(self, uid):
        self._stop_anim()
        allowed, reason = check_gate_allowed(uid)

        if not allowed:
            self._draw_icon(RED)
            self._set_status("✗ DITOLAK", RED)
            self._set_sub(reason)
            self.v_source.set("✗ DENIED")
            if self._scanning:
                self.after(RESULT_SECONDS, self._resume_scan)
            return

        self._draw_icon(LBLUE)
        self._set_status(f"✓ {GATE_LABEL}", GATE_COLOR)
        self._set_sub("Mengirim ke server...")

        new_status = "IN" if GATE_MODE == "IN" else "OUT"
        set_user_status(uid, new_status)
        trigger_relay()

        def worker():
            try:
                result = send_to_api(uid)
                self.after(0, lambda r=result, u=uid: self._on_api_done(r, u))
            except Exception as ex:
                self.after(0, lambda m=str(ex): self._on_api_error(m))

        threading.Thread(target=worker, daemon=True).start()

    def _on_api_done(self, result: dict, uid: str):
        msg        = result.get("message", "")
        data       = result.get("data") or {}
        finger_b64 = result.get("_finger_b64", "")

        if data:
            self._draw_icon(GREEN)
            self._set_status("✓ BERHASIL", GREEN)
            self._set_sub(msg)
            self.v_source.set(f"✓ {GATE_LABEL}")
            self.rvars["name"].set(data.get("name", "—"))
            self.rvars["cardNumber"].set(data.get("cardNumber", "—"))
            self.rvars["packet"].set(data.get("packet", "—"))
            self.rvars["expDate"].set(data.get("expDate", "—"))
            self.rvars["clockIn"].set(data.get("clockIn", "—"))
            name = data.get("name", "")
            if name:
                set_user_status(uid, "IN" if GATE_MODE == "IN" else "OUT", name)
            try: save_log(data, msg, "BERHASIL", finger_b64)
            except: pass
        else:
            self._draw_icon(YEL)
            self._set_status("Tidak Dikenali", YEL)
            self._set_sub(msg or "Tidak ditemukan di server")
            self.v_source.set("⚠ NOT FOUND")

        self.after(RESULT_SECONDS, self._resume_scan)

    def _on_api_error(self, msg: str):
        self._draw_icon(RED)
        self._set_status("✗ API ERROR", RED)
        self._set_sub(msg)
        self.v_source.set("✗ ERROR")
        self.after(RESULT_SECONDS, self._resume_scan)

    def _resume_scan(self):
        if self._scanning:
            self._start_anim()
            self._set_status("SCANNING", LBLUE)
            self._set_sub("Tempelkan jari pada scanner")
            self._scan_loop()

    # ── anim ──────────────────────────────────────────────────────────────────
    ANIM_C = [LBLUE, "#93c5fd", "#bfdbfe", "#93c5fd"]

    def _start_anim(self):
        self._anim_i = 0
        def step():
            if not self._scanning: return
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
        s  = self._icon_size
        cx = cy = s // 2
        if pulse:
            self.canvas.create_oval(4, 4, s-4, s-4,
                                    outline=color, width=1, dash=(4, 6))
        radii = [int(s*r) for r in [0.39, 0.31, 0.23, 0.16, 0.09]]
        for i, r in enumerate(radii):
            self.canvas.create_arc(cx-r, cy-r, cx+r, cy+r,
                                   start=210+i*4, extent=120-i*8,
                                   style="arc", outline=color,
                                   width=2 if i==0 else 1.5)
        d = max(3, s//18)
        self.canvas.create_oval(cx-d, cy-d, cx+d, cy+d, fill=color, outline="")

    def _set_status(self, text, color=WHITE): self.lbl_status.config(text=text, fg=color)
    def _set_sub(self, text):                self.lbl_sub.config(text=text)


if __name__ == "__main__":
    print("=" * 50)
    print(f"HALORAGA GYM — {GATE_LABEL}")
    print(f"STATUS_SERVER: {STATUS_SERVER}")
    print(f"IP: {get_ip()}  |  WiFi: {get_wifi_ssid()}")
    print("=" * 50)
    print()
    r = subprocess.run(["sudo","find",FPRINT_DIR,"-mindepth","1","-maxdepth","1","-type","d"],
                       capture_output=True, text=True)
    users = [os.path.basename(p.strip()) for p in r.stdout.splitlines() if p.strip()]
    print(f"[INFO] {len(users)} user di fprint:")
    for u in users: print(f"  - {u}")
    print()
    App().mainloop()
