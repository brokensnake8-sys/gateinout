"""
fpwrap.py — Python wrapper untuk libfpwrap.so
Pakai libfprint langsung → fp_device_identify_sync → 1 scan langsung ketemu!
"""

import ctypes, os

_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libfpwrap.so")
_lib      = ctypes.CDLL(_lib_path)

# int fpwrap_identify_from_dir(const char* dir_path, char* matched, int size)
_lib.fpwrap_identify_from_dir.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
_lib.fpwrap_identify_from_dir.restype  = ctypes.c_int

# int fpwrap_enroll_to_file(const char* out_path)
_lib.fpwrap_enroll_to_file.argtypes = [ctypes.c_char_p]
_lib.fpwrap_enroll_to_file.restype  = ctypes.c_int


def identify_from_dir(dir_path: str) -> str | None:
    """
    Scan jari 1x, bandingkan dengan semua template di dir_path.
    Return: path file template yang match, atau None kalau tidak match.
    """
    buf = ctypes.create_string_buffer(512)
    ret = _lib.fpwrap_identify_from_dir(dir_path.encode(), buf, 512)
    if ret == 1:
        return buf.value.decode()
    return None


def enroll_to_file(out_path: str) -> bool:
    """Scan jari dan simpan template ke out_path."""
    ret = _lib.fpwrap_enroll_to_file(out_path.encode())
    return ret == 0
