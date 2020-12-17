sudo apt install -y pijuice-base
sudo apt install -y python3-pip git pijuice-base python3-picamera # rpi.gpio
# Pillow dependancies
sudo apt install -y libjpeg-dev libopenjp2-7 libtiff5
# psutils dependancies
sudo apt-get install gcc python3-dev
#  enable saving of iptables
sudo apt install iptables-persistent
# tmv!
git clone https://github.com/brettbeeson/tmv
cd tmv
#sudo python3 -m pip install timemv # production
sudo python3 setup.py develop   # dev
sudo scripts/install-tmv-camera.sh # install systemd services       