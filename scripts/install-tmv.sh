echo Installing base dependancies
sudo apt install -y python3-pip git pijuice-base python3-picamera
# Pillow dependancies
sudo apt install -y libjpeg-dev libopenjp2-7 libtiff5
# psutils dependancies - could remove?
sudo apt-get install gcc python3-dev
#  enable saving of iptables (install without user)
echo iptables-persistent iptables-persistent/autosave_v4 boolean true | sudo debconf-set-selections
echo iptables-persistent iptables-persistent/autosave_v6 boolean true | sudo debconf-set-selections

echo Installing TMV
git clone https://github.com/brettbeeson/tmv
cd tmv
#sudo python3 -m pip install timemv # production
sudo python3 setup.py develop   # dev
sudo scripts/install-tmv-camera.sh # install systemd services       

echo Installing AP
wget -O rpi-wifi.sh https://raw.githubusercontent.com/lukicdarkoo/rpi-wifi/master/configure 
chmod 755 rpi-wifi.sh
./rpi-wifi.sh  -a tmv-$HOSTNAME-ap imagines -c "NetComm 0405" 12345678

echo *** edit the AP password ***
echo vim /etc/hostapd/hostapd.conf