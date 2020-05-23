#!/bin/bash
mkdir ~/tmv-data
sudo cp scripts/tmv-camera.service /etc/systemd/system/
sudo cp scripts/tmv-controller.service /etc/systemd/system/
sudo cp scripts/tmv-upload.service /etc/systemd/system/
systemctl daemon-reload 
systemctl start tmv-controller
systemctl enable tmv-controller

# RTC
sudo cp scripts/rtc-sync.service /etc/systemd/system/
systemctl daemon-reload 
systemctl start rtc-sync
systemctl enable rtc-sync

# tzupdate (optional) to automatically set your timezone
# pip install -U tzupdate

