echo Installing base dependancies
sudo apt install -y python3-pip git pijuice-base python3-picamera
echo Installing TMV
sudo python3 setup.py develop   # dev
echo Installing TMV services
sudo scripts/install-tmv-camera.sh # install systemd services       
