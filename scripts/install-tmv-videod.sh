#!/bin/bash
sudo cp scripts/tmv-videod.service /etc/systemd/system/
systemctl daemon-reload # optional
sudo mkdir /etc/tmv
echo Check ownership of /etc/tmv
sudo chgrp $USER /etc/tmv
sudo chown $USER /etc/tmv
systemctl start tmv-videod
systemctl enable tmv-videod
echo Edit /etc/tmv/videod.toml

echo Installing Ngix - todo
# sudo apt install
