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
sudo chmod 664 /etc/tmv/*
sudo chgrp tmv /etc/tmv/*

echo Setting sudoers
# allow user to run systemctl, to allow restart of services by camapp webbie, running as pi
sudo cp scripts/030_tmv /etc/sudoers.d/

# install lighttpd script to redirect just "/" to our camapp
echo Configuring lighttpd
sudo cp scripts/50-tmv.conf /etc/lighttpd/conf-enabled/

echo Making a data directory
mkdir ~/tmv-data
 
echo Installing service files
sudo cp scripts/tmv-camera.service /etc/systemd/system/
sudo cp scripts/tmv-controller.service /etc/systemd/system/
sudo cp scripts/tmv-upload.service /etc/systemd/system/
sudo cp scripts/tmv-camapp.service /etc/systemd/system/

echo Registering services
sudo systemctl daemon-reload 
sudo systemctl enable tmv-controller
sudo systemctl enable tmv-camapp


echo Restarting lighttpd
sudo systemctl restart lighttpd 
echo Done


