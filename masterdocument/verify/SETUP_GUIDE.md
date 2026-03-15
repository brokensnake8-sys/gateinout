# Setup 3 RPi — Gate System Haloraga Gym

## Arsitektur
```
RPi A (192.168.1.7)  ← SERVER UTAMA
├── /var/lib/fprint   ← data sidik jari semua member
├── /shared/          ← folder shared (status.json)
├── status_server.py  ← port 5050 (komunikasi B & C)
├── app.py            ← enroll via web
└── yasin.py          ← admin server

RPi B  ← GATE IN
├── mount /var/lib/fprint dari RPi A
├── keren.py (GATE_MODE = "IN")
└── config.json

RPi C  ← GATE OUT
├── mount /var/lib/fprint dari RPi A
├── keren.py (GATE_MODE = "OUT")
└── config.json
```

---

## RPi A — Setup Server

### 1. Export NFS
```bash
sudo apt install nfs-kernel-server -y

# Buat folder shared untuk status.json
sudo mkdir -p /shared
sudo chown yareuun:yareuun /shared

# Export dua folder
echo "/var/lib/fprint  *(rw,sync,no_subtree_check,no_root_squash)" | sudo tee -a /etc/exports
echo "/shared          *(rw,sync,no_subtree_check,no_root_squash)" | sudo tee -a /etc/exports

sudo exportfs -ra
sudo systemctl enable nfs-kernel-server
sudo systemctl start nfs-kernel-server
```

### 2. Jalankan status_server.py
```bash
# Test manual
cd ~/verify
python3 status_server.py

# Atau via autostart.sh
```

### 3. config.json RPi A (untuk keren.py kalau mau jalan juga di A)
```json
{
  "GATE_MODE": "IN",
  "STATUS_SERVER": "http://localhost:5050"
}
```

---

## RPi B — Setup Gate IN

### 1. Install NFS client
```bash
sudo apt install nfs-common -y
```

### 2. Mount folder dari RPi A
```bash
# Buat mount point
sudo mkdir -p /var/lib/fprint
sudo mkdir -p /mnt/rpia_shared

# Mount
sudo mount 192.168.1.7:/var/lib/fprint /var/lib/fprint
sudo mount 192.168.1.7:/shared /mnt/rpia_shared

# Test
ls /var/lib/fprint   # harus muncul folder user
ls /mnt/rpia_shared  # kosong dulu, nanti ada status.json
```

### 3. Auto-mount saat boot (fstab)
```bash
sudo nano /etc/fstab
```
Tambah:
```
192.168.1.7:/var/lib/fprint  /var/lib/fprint    nfs  defaults,noac,_netdev  0  0
192.168.1.7:/shared          /mnt/rpia_shared   nfs  defaults,noac,_netdev  0  0
```
```bash
sudo mount -a
```

### 4. Copy file dari RPi A
```bash
mkdir -p ~/gatein
scp yareuun@192.168.1.7:~/verify/keren.py ~/gatein/
scp yareuun@192.168.1.7:~/verify/fpwrap.py ~/gatein/
scp yareuun@192.168.1.7:~/verify/libfpwrap.so ~/gatein/
```

### 5. config.json RPi B
```bash
nano ~/gatein/config.json
```
Isi:
```json
{
  "GATE_MODE": "IN",
  "STATUS_SERVER": "http://192.168.1.7:5050"
}
```

### 6. Jalankan
```bash
cd ~/gatein
sudo python3 keren.py
```

---

## RPi C — Setup Gate OUT

### 1. Install NFS client
```bash
sudo apt install nfs-common -y
```

### 2. Mount folder dari RPi A
```bash
sudo mkdir -p /var/lib/fprint
sudo mkdir -p /mnt/rpia_shared

sudo mount 192.168.1.7:/var/lib/fprint /var/lib/fprint
sudo mount 192.168.1.7:/shared /mnt/rpia_shared
```

### 3. Auto-mount saat boot (fstab)
```bash
sudo nano /etc/fstab
```
Tambah:
```
192.168.1.7:/var/lib/fprint  /var/lib/fprint    nfs  defaults,noac,_netdev  0  0
192.168.1.7:/shared          /mnt/rpia_shared   nfs  defaults,noac,_netdev  0  0
```
```bash
sudo mount -a
```

### 4. Copy file dari RPi A
```bash
mkdir -p ~/gateout
scp yareuun@192.168.1.7:~/verify/keren.py ~/gateout/
scp yareuun@192.168.1.7:~/verify/fpwrap.py ~/gateout/
scp yareuun@192.168.1.7:~/verify/libfpwrap.so ~/gateout/
```

### 5. config.json RPi C
```bash
nano ~/gateout/config.json
```
Isi:
```json
{
  "GATE_MODE": "OUT",
  "STATUS_SERVER": "http://192.168.1.7:5050"
}
```

### 6. Jalankan
```bash
cd ~/gateout
sudo python3 keren.py
```

---

## Autostart saat boot

### RPi A — autostart.sh
```bash
#!/bin/bash
pkill -f status_server.py 2>/dev/null
pkill -f keren.py 2>/dev/null
pkill -f yasin.py 2>/dev/null
sleep 1

cd /home/yareuun/verify
nohup python3 status_server.py > /home/yareuun/verify/log_status.txt 2>&1 &
sleep 2
cd /home/yareuun/bangbil/gym_web_app_finger_reader_fe-main/admin_server
nohup python3 yasin.py > /home/yareuun/verify/log_yasin.txt 2>&1 &
sleep 1
cd /home/yareuun/verify
DISPLAY=:0 nohup sudo python3 keren.py > /home/yareuun/verify/log_keren.txt 2>&1 &
```

### RPi B — autostart
```bash
#!/bin/bash
# Tunggu network + NFS
sleep 5
cd /home/USER/gatein
DISPLAY=:0 nohup sudo python3 keren.py > /home/USER/gatein/log.txt 2>&1 &
```

### RPi C — autostart
```bash
#!/bin/bash
sleep 5
cd /home/USER/gateout
DISPLAY=:0 nohup sudo python3 keren.py > /home/USER/gateout/log.txt 2>&1 &
```

Daftarkan ke systemd atau crontab:
```bash
# Crontab (paling simple)
crontab -e
# Tambah baris:
@reboot sleep 10 && bash /home/USER/gatein/autostart.sh
```

---

## Alur komunikasi

```
Member scan jari di RPi B (Gate IN)
    ↓
fpwrap baca template dari /var/lib/fprint (mount dari RPi A)
    ↓
Cek status ke RPi A port 5050: GET /status/{uid}
    ↓
Kalau status = OUT → boleh masuk
    ↓
Set status = IN ke RPi A: POST /status/{uid}
    ↓
Kirim template ke API server

Member scan jari di RPi C (Gate OUT)
    ↓
Cek status ke RPi A port 5050: GET /status/{uid}
    ↓
Kalau status = IN → boleh keluar
    ↓
Set status = OUT ke RPi A: POST /status/{uid}
```

---

## Cek IP setiap RPi

```bash
hostname -I
```

Kalau IP berubah, edit saja `config.json` di RPi B dan C:
```json
{
  "STATUS_SERVER": "http://IP_BARU_RPI_A:5050"
}
```

Restart program, selesai.
