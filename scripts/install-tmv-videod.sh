#!/bin/bash
sudo cp scripts/tmv-videod.service /etc/systemd/system/
systemctl daemon-reload # optional
sudo mkdir /etc/tmv
echo Check ownership of /etc/tmv
sudo chgrp bbeeson /etc/tmv
sudo chown bbeeson /etc/tmv
systemctl start tmv-videod
systemctl enable tmv-videod
echo Edit /etc/tmv/videod.toml
