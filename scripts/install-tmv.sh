echo Updating system
sudo apt update

echo Installing base dependancies
sudo apt install -y python3-pip git pijuice-base python3-picamera

echo Pillow install as setup.py sometimes fails to run correctly without this
sudo apt install libjpeg-dev libopenjp2-7 libtiff5
sudo pip3 install pillow 
#sudo pip3 install pillow --upgrade --force-reinstall pillow # plan b

# if setup.py doesn't install for unknown reason
#sudo pip3 install flask

echo Installing TMV in a venv
python3 -m venv venv
source venv/bin/activate
echo Requests (instead of setup.py where 2.21.0 - not 2.25.1 - is installed)
pip install --upgrade requests
python setup.py -e .
#python setup.py .

echo Installing TMV services
sudo scripts/install-tmv-camera.sh 
