echo Updating system
sudo apt update

echo Installing base dependancies
sudo apt install -y python3-pip git pijuice-base python3-picamera

echo Pillow install (setup.py sometimes fails to run correctly without this)
sudo apt install libjpeg-dev libopenjp2-7 libtiff5
sudo pip3 install pillow 
#sudo pip3 install pillow --upgrade --force-reinstall pillow # plan b

echo botocore install (faster than in setup.py)
sudo pip3 install botocore

echo Installing TMV
sudo python3 setup.py develop   # dev
sudo python3 setup.py develop   # twice appears required ???

echo Installing TMV services
sudo scripts/install-tmv-camera.sh 
