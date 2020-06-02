
#
# PiJuice / TZ
#
echo Installing pijuice
sudo apt install pijuice-base
echo Registering RTC service
sudo cp scripts/rtc-sync.service /etc/systemd/system/
sudo systemctl daemon-reload 
sudo systemctl start rtc-sync
sudo systemctl enable rtc-sync

