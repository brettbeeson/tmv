#!/bin/bash

# run as pi
user=pi

# make a tmv group to allow pi (a member of tmv) to write to config files
echo Adding tmv group
sudo groupadd tmv
sudo usermod -a -G tmv $user

echo Setting up /etc/tmv
sudo mkdir /etc/tmv
sudo chmod 775 /etc/tmv
sudo chgrp tmv /etc/tmv
# new files should take tmv group
sudo chmod g+s /etc/tmv 
# change any existing too
sudo chmod 664 /etc/tmv/* 2>/dev/null
sudo chgrp tmv /etc/tmv/* 2>/dev/null

echo Setting sudoers
# allow user to run systemctl, to allow restart of services by interface app, running as pi
sudo cp scripts/030_tmv /etc/sudoers.d/

echo Making a data directory
mkdir ~/tmv-data
 
echo Installing service files
sudo cp scripts/tmv-camera.service /etc/systemd/system/
sudo cp scripts/tmv-upload.service /etc/systemd/system/
sudo cp scripts/tmv-interface.service /etc/systemd/system/

echo Registering services
sudo systemctl daemon-reload 
sudo systemctl enable tmv-camera
sudo systemctl enable tmv-upload
sudo systemctl enable tmv-interface

echo Redirecting port 80 to 5000
# sudo apt install iptables-persistent # required user input
echo iptables-persistent iptables-persistent/autosave_v4 boolean true | sudo debconf-set-selections
sudo iptables -t nat -I PREROUTING -p tcp --dport 80 -j REDIRECT --to-ports 5000
sudo iptables -t nat -I OUTPUT -p tcp -d 127.0.0.1 --dport 80 -j REDIRECT --to-ports 5000
sudo iptables-save 
sudo mkdir /etc/iptables 2>/dev/null
sudo iptables-save | sudo tee -a /etc/iptables/rules.v4 1>/dev/null
sudo ip6tables-save | sudo tee -a /etc/iptables/rules.v6 1>/dev/null

echo Changing /etc/wpa_supplicant/wpa_supplicant.conf permissions
sudo chgrp netdev /etc/wpa_supplicant/wpa_supplicant.conf 
sudo chmod 664 /etc/wpa_supplicant/wpa_supplicant.conf 

echo Done