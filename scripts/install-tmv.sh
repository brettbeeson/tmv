echo Installing base dependancies
sudo apt install -y python3-pip git pijuice-base python3-picamera
echo Install Pillow dependancies
sudo apt install -y libjpeg-dev libopenjp2-7 libtiff5
echo Install psutils dependancies (could remove?)
sudo apt-get install gcc python3-dev
echo Installing TMV
sudo python3 setup.py develop   # dev
echo Installing TMV services
sudo scripts/install-tmv-camera.sh # install systemd services       
