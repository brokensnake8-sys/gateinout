"""
check_format.py — Cek format file template di /var/lib/fprint
Jalankan: sudo python3 check_format.py
"""
import subprocess, os, struct

FPRINT_DIR = "/var/lib/fprint"

# Ambil semua file
r = subprocess.run(
    ["sudo", "find", FPRINT_DIR, "-type", "f"],
    capture_output=True, text=True
)
files = [f.strip() for f in r.stdout.splitlines() if f.strip()]

print(f"Total file: {len(files)}")
print()

for f in files[:3]:  # cek 3 file pertama
    print(f"File: {f}")
    r2 = subprocess.run(["sudo", "cat", f], capture_output=True)
    data = r2.stdout
    if not data:
        print("  (kosong atau tidak bisa dibaca)")
        continue
    
    print(f"  Size: {len(data)} bytes")
    print(f"  Header hex: {data[:16].hex()}")
    print(f"  Header str: {repr(data[:16])}")
    
    # Cek magic bytes
    if data[:4] == b'FP1\x00':
        print("  Format: libfprint FP1 (lama)")
    elif data[:8] == b'FP2\x00\x00\x00\x00\x00':
        print("  Format: libfprint FP2")
    elif data[:4] == b'SGFP':
        print("  Format: SGFP")
    elif data[0:2] == b'\x1f\x8b':
        print("  Format: gzip compressed")
    elif data[:4] == b'\x89PNG':
        print("  Format: PNG image")
    else:
        print("  Format: unknown")
        # Cek apakah ini GVariant (fprintd format)
        print(f"  Bytes 0-32: {data[:32].hex()}")
    print()
