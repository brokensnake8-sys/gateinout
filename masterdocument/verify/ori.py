"""
Fingerprint Attendance - Haloraga Gym Machine
Flow: fprintd-enroll (subprocess) → baca file /var/lib/fprint/ → base64 → kirim API
Sama persis dengan cara app.py enroll sidik jari ke server.

Run: sudo python3 fingerprint_verify.py
"""

import tkinter as tk
import threading
import requests
import base64
import subprocess
import os
from datetime import datetime

# ── CONFIG ─────────────────────────────────────────────────────────────────────
API_URL   = "https://machine.haloraga.com/api/v1/attendance-via-finger"
TEMP_USER = "fp_attend_tmp"

# Folder log disimpan di sebelah script ini
BASE_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data scan gui")

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


# ── LOG HELPER ────────────────────────────────────────────────────────────────
def save_scan_log(data: dict, message: str = "",
                  status: str = "BERHASIL", finger_b64: str = "") -> str:
    """
    Buat folder  data scan gui / ddmmyyyy_HHMMss  lalu simpan:
      - scan_result.txt  → detail hasil scan
      - finger_data.txt  → base64 yang dikirim ke API (untuk compare)
    status: "BERHASIL" | "TIDAK DIKENALI" | "GAGAL"
    Return: path folder yang dibuat.
    """
    now         = datetime.now()
    folder_name = now.strftime("%d%m%Y_%H%M%S")
    folder_path = os.path.join(BASE_DIR, folder_name)
    os.makedirs(folder_path, exist_ok=True)

    # ── scan_result.txt ───────────────────────────────────────────────────────
    with open(os.path.join(folder_path, "scan_result.txt"), "w", encoding="utf-8") as f:
        f.write("=" * 44 + "\n")
        f.write("   HALORAGA GYM — Fingerprint Attendance\n")
        f.write("=" * 44 + "\n")
        f.write(f"Waktu Scan  : {now.strftime('%d-%m-%Y %H:%M:%S')}\n")
        f.write(f"Status      : {status}\n")
        f.write("-" * 44 + "\n")
        f.write(f"Nama        : {data.get('name',    '—')}\n")
        f.write(f"Paket       : {data.get('packet',  '—')}\n")
        f.write(f"Exp. Date   : {data.get('expDate', '—')}\n")
        f.write(f"Clock In    : {data.get('clockIn', '—')}\n")
        f.write("-" * 44 + "\n")
        f.write(f"Keterangan  : {message}\n")
        f.write("=" * 44 + "\n")

    # ── finger_data.txt  (base64 persis yang dikirim ke API) ─────────────────
    if finger_b64:
        with open(os.path.join(folder_path, "finger_data.txt"), "w", encoding="utf-8") as f:
            f.write(finger_b64)

    return folder_path


# ── CORE ──────────────────────────────────────────────────────────────────────
def cleanup_temp():
    subprocess.run(["sudo", "fprintd-delete", TEMP_USER], capture_output=True)
    subprocess.run(["sudo", "userdel", "-r", TEMP_USER], capture_output=True)
    subprocess.run(["sudo", "rm", "-rf", f"/var/lib/fprint/{TEMP_USER}"], capture_output=True)


def scan_and_get_template(on_progress=None) -> bytes:
    cleanup_temp()

    subprocess.run(
        ["sudo", "useradd", "-m", "-s", "/bin/bash", TEMP_USER],
        capture_output=True
    )

    if on_progress:
        on_progress("Letakkan jari pada scanner...")

    result = subprocess.run(
        ["sudo", "fprintd-enroll", TEMP_USER],
        capture_output=True, text=True,
        timeout=30
    )

    out = (result.stdout or "") + (result.stderr or "")

    if result.returncode != 0:
        cleanup_temp()
        if "NoSuchDevice" in out or "No devices" in out:
            raise RuntimeError("Scanner tidak terdeteksi")
        raise RuntimeError(f"Scan gagal: {out.strip()[:80]}")

    if on_progress:
        on_progress("Membaca template...")

    find = subprocess.run(
        ["sudo", "find", f"/var/lib/fprint/{TEMP_USER}", "-type", "f"],
        capture_output=True, text=True
    )
    fp_files = [f.strip() for f in find.stdout.splitlines() if f.strip()]

    if not fp_files:
        cleanup_temp()
        raise RuntimeError("File template tidak ditemukan setelah scan")

    read = subprocess.run(["sudo", "cat", fp_files[0]], capture_output=True)

    if read.returncode != 0 or not read.stdout:
        cleanup_temp()
        raise RuntimeError("Gagal baca file template")

    raw_bytes = read.stdout
    cleanup_temp()
    return raw_bytes


def send_to_api(finger_b64: str) -> dict:
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
        self.title("Finger Attendance")
        self.geometry("400x620")
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
        tk.Label(self, text="Fingerprint Attendance", bg=BG, fg=WHITE,
                 font=("Courier New", 16, "bold")).pack()
        tk.Frame(self, bg=BG, height=20).pack(fill="x")

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
        for key, label in [("name","Nama"),("expDate","Exp. Date"),
                            ("packet","Paket"),("clockIn","Clock In")]:
            row = tk.Frame(rf, bg=CARD)
            row.pack(fill="x", padx=12, pady=3)
            tk.Label(row, text=f"{label:<10} :", bg=CARD, fg=GRAY,
                     font=("Courier New", 9)).pack(side="left")
            v = tk.StringVar(value="—")
            tk.Label(row, textvariable=v, bg=CARD, fg=WHITE,
                     font=("Courier New", 9, "bold")).pack(side="left", padx=6)
            self.rvars[key] = v

        tk.Frame(rf, bg=BORD, height=1).pack(fill="x", padx=12, pady=(10, 4))
        log_row = tk.Frame(rf, bg=CARD)
        log_row.pack(fill="x", padx=12, pady=(0, 4))
        tk.Label(log_row, text="Log       :", bg=CARD, fg=GRAY,
                 font=("Courier New", 9)).pack(side="left")
        self.v_log = tk.StringVar(value="—")
        tk.Label(log_row, textvariable=self.v_log, bg=CARD, fg=LBLUE,
                 font=("Courier New", 8), wraplength=240, justify="left").pack(side="left", padx=6)

        tk.Frame(rf, bg=CARD, height=12).pack(fill="x")
        tk.Frame(self, bg=BG, height=8).pack(fill="x")
        tk.Label(self, text="via fprintd-enroll → base64 → API",
                 bg=BG, fg=GRAY, font=("Courier New", 7)).pack()
        tk.Frame(self, bg=BG, height=12).pack(fill="x")

    # ── scan handler ──────────────────────────────────────────────────────────
    def _on_scan(self):
        if self._busy: return
        self._busy = True
        self.btn.config(state="disabled", text="⏳  Scanning...")
        for v in self.rvars.values(): v.set("—")
        self.v_log.set("—")
        self._set_status("Letakkan jari...", WHITE)
        self._set_sub("Siapkan jari pada scanner")
        self._start_anim()
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self):
        finger_b64 = ""
        try:
            template = scan_and_get_template(
                on_progress=lambda m: self.after(0, lambda msg=m: self._set_sub(msg))
            )

            # Encode base64 di sini — inilah yang dikirim ke API & disimpan ke file
            finger_b64 = base64.b64encode(template).decode("utf-8")

            self.after(0, lambda: self._set_sub("Mengirim ke server..."))
            resp = send_to_api(finger_b64)
            self.after(0, lambda r=resp, b=finger_b64: self._on_success(r, b))

        except subprocess.TimeoutExpired:
            self.after(0, lambda b=finger_b64: self._on_error("Timeout — tidak ada input jari", b))
        except requests.exceptions.ConnectionError:
            self.after(0, lambda b=finger_b64: self._on_error("Koneksi ke server gagal", b))
        except requests.exceptions.HTTPError as ex:
            code = ex.response.status_code
            body = ""
            try: body = ex.response.json().get("message", "")
            except Exception: pass
            self.after(0, lambda c=code, bd=body, b=finger_b64: self._on_error(f"HTTP {c}: {bd}", b))
        except Exception as ex:
            m = str(ex)
            self.after(0, lambda msg=m, b=finger_b64: self._on_error(msg, b))

    def _on_success(self, resp, finger_b64: str = ""):
        self._stop_anim()
        self._busy = False
        self.btn.config(state="normal", text="▶  SCAN SIDIK JARI")
        msg  = resp.get("message", "")
        data = resp.get("data") or {}

        if data:
            self._draw_icon(GREEN)
            self._set_status("✓ BERHASIL", GREEN)
            self._set_sub(msg)
            self.rvars["name"].set(data.get("name",    "—"))
            self.rvars["expDate"].set(data.get("expDate", "—"))
            self.rvars["packet"].set(data.get("packet",  "—"))
            self.rvars["clockIn"].set(data.get("clockIn", "—"))
            self._save_log(data, msg, "BERHASIL", finger_b64)
        else:
            self._draw_icon(YEL)
            self._set_status("Tidak Dikenali", YEL)
            self._set_sub(msg or "Sidik jari tidak ditemukan di server")
            self._save_log({}, msg or "Sidik jari tidak ditemukan di server",
                           "TIDAK DIKENALI", finger_b64)

    def _on_error(self, msg: str, finger_b64: str = ""):
        self._stop_anim()
        self._busy = False
        cleanup_temp()
        self.btn.config(state="normal", text="▶  SCAN SIDIK JARI")
        self._draw_icon(RED)
        self._set_status("✗ GAGAL", RED)
        self._set_sub(msg)
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
    App().mainloop()
