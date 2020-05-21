# Time Made Visible

TMV provides a "camera to video" timelapse system. The system is comprised of:
- Raspberry PiZeroW camera: take photos, save to disk, upload to S3. USB or battery-and-solar-powered.
- MinIO or AWS S3 server: store photos and videos, store static web pages. 
- Video Encoder: linux box that makes videos from images. Can be seperate from S3 server or combined.
- Web App: browse S3 and display photos and videos. Runs on local browser from static files served from S3 bucket.

## Installation 
### Camera
Testing on a PiZeroW. This is only one of many options on how to setup.
- Write fresh Raspbian Lite to SD and boot
- Use raspi-config to setup passwd, hostname, _camera_, WiFi and SSH. 
- Do a `apt upgrade && apt dist-upgrade`
- Optionally, install a WiFi provisioner such as [RaspAP](https://github.com/billz/raspap-webgui)
- Optionally, install `sudo pip install -U tzupdate` to update your timezone if you travel

#### SSH to the Pi from a linux desktop
```
scp -r .ssh pi@raspberrypi.local:.
ssh pi@raspberrypi.local
```

#### Now on the Pi Zero W with a PiJuiceZero
```
# install TMV and dependancies
sudo apt install -y python3-pip git pijuice-base python3-picamera RPi.GPIO
# Pillow dependancies
sudo apt install -y libjpeg-dev libopenjp2-7 libtiff5
git clone https://github.com/brettbeeson/tmv
cd tmv
#sudo python3 -m pip install timemv # production
sudo python3 setup.py develop   # dev
sudo scripts/install-tmv-camera.sh # install systemd services                
```
### Configure Camera
The camera writes images to the local storage
- Your can turn off the camera's LED via `echo 'disable_camera_led=1' >> /boot/config.txt`
- (It will then only flash during taking a photo)
- edit `/etc/tmv/camera.toml` to set file_root

### Optionally, Configure Camera Uploads
The uploader runs on the camera and sends images to an s3 bucket when possible or locally caches.
- again edit `/etc/tmv/camera.toml` to set s3 upload details such as destination, profile and endpoint
- the directory /home/pi/.aws/ should contain your s3 credentials

### Optionally, Configure PiJuice
Refer to the docs, but briefly:
- `sudo systemctl enable pijuice`
- `echo dtoverlay=i2c-rtc,ds1339 | sudo -a /boot/config.txt` to endable real time clock
- `pijuice_cli` to get settings

### Start Camera
- `sudo tmv-switch-robot auto on` to set camera to auto, and uploads to on
- `journalctl -f -u 'tmv*'` to check logs in operation

### Server 
Tested on Ubuntu 18, but likely to work on most linux. It converts photos to videos and optionally stores them.
- Install [Minio](https://minio.io) to store your images. You could use any s3 server either local or remote (e.g. AWS)
- (Typically you'll store at /var/s3/my.tmv.bucket)
```
sudo apt install -y python3-pip vim git 
git clone https://github.com/brettbeeson/tmv
cd tmv
sudo python3 -m pip install setup.py
mkdir tmv-data
sudo scripts/install-tmv-camera.sh                 

```

#### Configure Server 

#### Further Configure Server (Optional)
- If running locally, a port-forward on your router and a ddyn solution can be setup for external access
- If using Route53 a simple option is (aws-dyndns](https://github.com/famzah/aws-dyndns)


Inspired by [Claude's Pi-Timolo](https://github.com/pageauc/pi-timolo/). Thanks Claude!
