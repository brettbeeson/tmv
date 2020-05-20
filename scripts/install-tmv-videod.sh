#!/bin/bash
sudo cp scripts/tmv-videod.service /etc/systemd/system/
systemctl daemon-reload # optional
systemctl start tmv-videod
systemctl enable tmv-videod
