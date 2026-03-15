#!/bin/bash
# autostart.sh — jalankan semua script RPi A
# Taruh di /home/yareuun/verify/autostart.sh

# Kill proses lama dulu
cd /home/yareuun/verify
python3 status_server.py &
sudo python3 keren.py &

cd /home/yareuun/bangbil/gym_web_app_finger_reader_fe-main/admin_server
python3 yasin.py &
