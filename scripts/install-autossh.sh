#!/bin/bash
echo EDIT /etc/systend/system/autossh.service
sudo apt install autossh
sudo cp scripts/autossh.service /etc/systemd/system/
sudo systemctl daemon-reload 
sudo systemctl enable autossh
sudo systemctl start autossh
