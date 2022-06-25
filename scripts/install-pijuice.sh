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

echo Optionally, configure PiJuice:
echo python3 ~/PiJuice/Software/Source/Utilities/pijuice_util.py  --load < ~/tmv/scripts/pijuice.conf

# the apt installs in /usr so need to copy to our venv. use a symlink
echo Setting up Python API for venv
cd ~/tmv/venv/lib/python3.7/site-packages/
ln -s /usr/lib/python3/dist-packages/pijuice.py .

echo Installing smbus required by pijuice package
cd ~/tmv
source venv/bin/activate
pip install smbus

echo Run the following to install rtc module
echo `echo dtoverlay=i2c-rtc,ds1339 | sudo tee -a /boot/config.txt`