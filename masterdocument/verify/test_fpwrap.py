"""
test_fpwrap.py — Test libfpwrap.so
Jalankan: sudo python3 test_fpwrap.py

Tempelkan jari saat diminta.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fpwrap import identify_from_dir

FPRINT_DIR = "/var/lib/fprint"

print("="*50)
print("TEST fpwrap_identify_from_dir")
print("="*50)
print(f"Dir: {FPRINT_DIR}")
print()
print("Tempelkan jari pada scanner...")
print()

result = identify_from_dir(FPRINT_DIR)

print()
if result:
    # Extract username dari path
    parts    = result.replace(FPRINT_DIR, "").strip("/").split("/")
    username = parts[0]
    print(f"✅ MATCH!")
    print(f"   File    : {result}")
    print(f"   Username: {username}")
else:
    print("❌ Tidak dikenali")
