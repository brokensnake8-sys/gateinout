"""
Fingerprint Attendance - Haloraga Gym Machine (V2 - With Local DB)
Flow: 
  1. Scan finger → fprintd-identify (1x scan langsung ketemu!)
  2. Langsung ambil data dari database lokal (users.json)
  3. Tampilkan info user di GUI
  4. Kirim ke API untuk attendance record

Improvement dari V1:
  - ✅ INSTANT identification (pakai fprintd-identify, BUKAN loop verify!)
  - ✅ 1x scan langsung ketemu - tidak peduli ada 1 user atau 3000 user
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

# ── CONFIG ─────────────────────────────────────────────────────────────────────
API_URL   = "https://machine.haloraga.com/api/v1/attendance-via-finger"
API_BASE  = "https://machine.haloraga.com/api/v1"  # untuk fetch member info
TEMP_USER = "fp_attend_tmp"

# Folder data disimpan di sebelah script ini
BASE_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data scan gui")
DB_PATH   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")

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

def get_user_info(username: str) -> dict:
    """
    Ambil info user dari database lokal berdasarkan username.
    Username format dari app.py yang baru: fpb8eae3a4_f1_20260314153045
    Kita perlu extract member_id dari username
    """
    db = load_local_db()
    
    # Cari user berdasarkan username atau member_id
    if username in db:
        return db[username]
    
    # Coba extract member_id dari username (format: fpXXXXXXXX_fN_timestamp)
    # member_id biasanya ada di bagian awal sebelum _f
    parts = username.split('_')
    if len(parts) >= 1:
        # Coba dengan full username tanpa timestamp
        base_username = parts[0]
        for key in db.keys():
            if key.startswith(base_username) or base_username.startswith(key[:10]):
                return db[key]
    
    return None

def update_user_cache(member_id: str, member_data: dict):
    """Update cache user di database lokal"""
    db = load_local_db()
    
    # Simpan dengan member_id sebagai key
    db[member_id] = {
        "member_id": member_id,
        "name": member_data.get("name", "—"),
        "cardNumber": member_data.get("cardNumber", "—"),
        "packet": member_data.get("packet", "—"),
        "expDate": member_data.get("expDate", "—"),
        "last_updated": datetime.now().isoformat()
    }
    
    save_local_db(db)
    print(f"[INFO] Updated local cache for {member_id}")

def sync_user_from_api(member_id: str, auth_token: str = "", auth_client: str = ""):
    """
    Fetch user data dari API dan simpan ke local cache
    """
    try:
        headers = {
            "Authorization": auth_token,
            "client": auth_client
        }
        
        resp = requests.get(
            f"{API_BASE}/member-name-card/{member_id}",
            headers=headers,
            timeout=10
        )
        
        if resp.ok:
            data = resp.json()
            member = data[0] if isinstance(data, list) else data.get("data", data)
            update_user_cache(member_id, member)
            return member
    except Exception as e:
        print(f"[WARN] Failed to sync user from API: {e}")
    
    return None


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


def scan_and_identify_user(on_progress=None) -> tuple:
    """
    Verifikasi sidik jari menggunakan fprintd-identify - LANGSUNG identify user tanpa loop!
    
    Return: (matched_username, template_bytes, user_info_dict)
    - matched_username: username yang match dari fprintd-identify
    - template_bytes: raw bytes fingerprint template
    - user_info_dict: info user dari database lokal (bisa None kalau belum ada di cache)
    """
    base_dir = "/var/lib/fprint"

    def progress(msg: str):
        if on_progress:
            on_progress(msg)

    if not os.path.isdir(base_dir):
        raise RuntimeError("Folder template lokal /var/lib/fprint tidak ditemukan")

    progress("Letakkan jari pada scanner...")

    # ✅ GUNAKAN fprintd-identify - IDENTIFY 1X LANGSUNG KETEMU!
    # Tidak perlu loop seperti fprintd-verify
    try:
        result = subprocess.run(
            ["sudo", "fprintd-identify"],
            capture_output=True, 
            text=True,
            timeout=15
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Timeout - tidak ada input jari dalam 15 detik")
    except FileNotFoundError:
        raise RuntimeError("fprintd-identify not found. Install fprintd package.")

    out = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    lower = out.lower()

    # Check for errors
    if "nosuchdevice" in lower or "no devices available" in lower:
        raise RuntimeError("Scanner tidak terdeteksi")
    
    if "no enrolled prints" in lower:
        raise RuntimeError("Belum ada sidik jari yang ter-enroll di Raspberry")

    # Parse output untuk dapat username yang match
    # Format output fprintd-identify:
    #   identify-succeeded: <username>
    # atau
    #   Identify result: <username>
    
    matched_user = None
    matched_finger = None
    
    for line in out.splitlines():
        line_lower = line.lower()
        
        # Cari "identify-succeeded: username"
        if "identify-succeeded:" in line_lower:
            parts = line.split(":", 1)
            if len(parts) > 1:
                matched_user = parts[1].strip()
                break
        
        # Atau format lain: "Identify result: username"
        if "identify result:" in line_lower and "identify-succeeded" not in line_lower:
            parts = line.split(":", 1)
            if len(parts) > 1:
                matched_user = parts[1].strip()
                break
    
    # Check if match found
    if not matched_user and result.returncode == 0:
        # Kalau returncode 0 tapi tidak ada explicit match message,
        # coba parse dari output lines
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        if lines:
            # Biasanya username ada di baris terakhir
            matched_user = lines[-1]
    
    if not matched_user:
        raise RuntimeError(f"Sidik jari tidak dikenali.\n{out[:200]}")

    progress(f"✓ Match: {matched_user}")

    # Ambil template file dari user yang match
    user_dir = os.path.join(base_dir, matched_user)
    
    if not os.path.isdir(user_dir):
        raise RuntimeError(f"User folder tidak ditemukan: {user_dir}")

    # Cari file template
    find = subprocess.run(
        ["sudo", "find", user_dir, "-type", "f"],
        capture_output=True, text=True
    )
    fp_files = [f.strip() for f in find.stdout.splitlines() if f.strip()]
    
    if not fp_files:
        raise RuntimeError(f"Tidak ada template file untuk user {matched_user}")

    # Pilih file pertama (atau bisa disesuaikan kalau ada info finger type)
    chosen_file = fp_files[0]
    
    progress(f"✓ Membaca template...")
    
    # Baca template file
    read = subprocess.run(["sudo", "cat", chosen_file], capture_output=True)
    if read.returncode != 0 or not read.stdout:
        raise RuntimeError(f"Gagal membaca template user {matched_user}")

    # Ambil info user dari database lokal
    user_info = get_user_info(matched_user)
    
    if user_info:
        progress(f"✓ Data ditemukan: {user_info.get('name', matched_user)}")
    else:
        progress(f"⚠ Data user belum ada di cache lokal")

    return (matched_user, read.stdout, user_info)


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
        tk.Label(self, text="🔹 With Local Database", bg=BG, fg=GRAY,
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
        
        # Status row
        status_row = tk.Frame(rf, bg=CARD)
        status_row.pack(fill="x", padx=12, pady=(0, 4))
        tk.Label(status_row, text="Status    :", bg=CARD, fg=GRAY,
                 font=("Courier New", 9)).pack(side="left")
        self.v_source = tk.StringVar(value="—")
        tk.Label(status_row, textvariable=self.v_source, bg=CARD, fg=LBLUE,
                 font=("Courier New", 8, "bold")).pack(side="left", padx=6)
        
        # Log row
        log_row = tk.Frame(rf, bg=CARD)
        log_row.pack(fill="x", padx=12, pady=(0, 4))
        tk.Label(log_row, text="Log       :", bg=CARD, fg=GRAY,
                 font=("Courier New", 9)).pack(side="left")
        self.v_log = tk.StringVar(value="—")
        tk.Label(log_row, textvariable=self.v_log, bg=CARD, fg=LBLUE,
                 font=("Courier New", 8), wraplength=240, justify="left").pack(side="left", padx=6)

        tk.Frame(rf, bg=CARD, height=12).pack(fill="x")
        tk.Frame(self, bg=BG, height=8).pack(fill="x")
        tk.Label(self, text="Local DB + API Sync",
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
        finger_b64 = ""
        matched_user = None
        local_info = None
        
        try:
            # Step 1: Scan dan identify dari local DB
            matched_user, template, local_info = scan_and_identify_user(
                on_progress=lambda m: self.after(0, lambda msg=m: self._set_sub(msg))
            )

            # Encode base64
            finger_b64 = base64.b64encode(template).decode("utf-8")

            # Step 2: Tampilkan data dari local cache (kalau ada)
            if local_info:
                self.after(0, lambda: self._show_local_data(matched_user, local_info))
            else:
                self.after(0, lambda: self._set_sub(f"User: {matched_user} (cache kosong)"))

            # Step 3: Kirim ke API untuk attendance record
            self.after(0, lambda: self._set_sub("Mengirim ke server..."))
            resp = send_to_api(finger_b64)
            
            # Step 4: Update dengan data dari API (lebih fresh)
            self.after(0, lambda r=resp, b=finger_b64, u=matched_user, l=local_info: 
                      self._on_success(r, b, u, l))

        except subprocess.TimeoutExpired:
            self.after(0, lambda b=finger_b64: self._on_error("Timeout — tidak ada input jari", b))
        except requests.exceptions.ConnectionError:
            # Kalau API gagal tapi sudah ada data lokal, tetap tampilkan
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
            
            # Kalau API reject tapi ada data lokal, tetap tampilkan dengan warning
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
        """Tampilkan data dari local cache dulu (instant feedback)"""
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
        """Success dengan data dari API (update data yang sudah ditampilkan)"""
        self._stop_anim()
        self._busy = False
        self.btn.config(state="normal", text="▶  SCAN SIDIK JARI")
        msg  = resp.get("message", "")
        data = resp.get("data") or {}

        if data:
            self._draw_icon(GREEN)
            self._set_status("✓ BERHASIL", GREEN)
            self._set_sub(msg)
            
            # Update dengan data dari API (lebih fresh)
            self.rvars["name"].set(data.get("name", "—"))
            self.rvars["cardNumber"].set(data.get("cardNumber", "—"))
            self.rvars["packet"].set(data.get("packet", "—"))
            self.rvars["expDate"].set(data.get("expDate", "—"))
            self.rvars["clockIn"].set(data.get("clockIn", "—"))
            self.v_source.set("✓ API CONFIRMED")
            
            # Update local cache dengan data terbaru dari API
            if matched_user:
                # Extract member_id dari username
                member_id = matched_user.split('_')[0].replace('fp', '')
                update_user_cache(member_id, data)
            
            self._save_log(data, msg, "BERHASIL", finger_b64)
        else:
            self._draw_icon(YEL)
            self._set_status("Tidak Dikenali", YEL)
            self._set_sub(msg or "Sidik jari tidak ditemukan di server")
            self.v_source.set("⚠ NOT IN API")
            self._save_log({}, msg or "Sidik jari tidak ditemukan di server",
                           "TIDAK DIKENALI", finger_b64)

    def _on_local_only(self, username: str, local_info: dict, finger_b64: str, error_msg: str):
        """Tampilkan data lokal saja karena API gagal"""
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
        cleanup_temp()
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
    print("With Local Database Cache")
    print("=" * 50)
    print()
    
    # Load local DB on startup
    db = load_local_db()
    print(f"[INFO] Local DB loaded: {len(db)} users cached")
    print()
    
    App().mainloop()
