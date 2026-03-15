#!/bin/bash
# build.sh — Compile fpwrap.c ke libfpwrap.so
# Jalankan: bash build.sh

echo "[BUILD] Install dependencies..."
sudo apt install -y libfprint-2-dev libglib2.0-dev pkg-config gcc

echo "[BUILD] Compile fpwrap.c..."
gcc -shared -fPIC -o libfpwrap.so fpwrap.c \
    $(pkg-config --cflags --libs libfprint-2) \
    -lglib-2.0 \
    -Wall -O2

if [ $? -eq 0 ]; then
    echo "[BUILD] ✅ Berhasil! libfpwrap.so siap dipakai"
    ls -lh libfpwrap.so
else
    echo "[BUILD] ❌ Gagal compile"
fi
