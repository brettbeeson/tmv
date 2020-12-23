
echo Installing AP
wget -O rpi-wifi.sh https://raw.githubusercontent.com/brettbeeson/rpi-wifi/master/configure
chmod 755 rpi-wifi.sh
./rpi-wifi.sh  -a tmv-$HOSTNAME imagines -c "NetComm 0405" 12345678
echo *** edit the AP password ***
echo vim /etc/hostapd/hostapd.conf