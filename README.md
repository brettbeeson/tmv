# Time, Made Visible

TMV provides a "camera to video" timelapse system. The system is comprised of:
- Raspberry PiZeroW camera: take photos, save to disk, upload to S3. USB or battery-and-solar-powered.
- MinIO or AWS S3 server: store photos and videos, store static web pages. 
- Video Encoder: linux box that makes videos from images. Can be seperate from S3 server or combined.
- Web App: browse S3 and display photos and videos. Runs on local browser from static files served from S3 bucket.

## Installation 
### Camera
Testing on a PiZeroW. This is only one of many options on how to setup.
- [Write fresh Raspbian Lite](http://brettbeeson.com.au/raspberry-pi-setup-zerow/) to SD and boot headless.
- Use raspi-config to setup passwd, hostname, timezone, _camera_, WiFi country. Reboot.
- Do a `sudo apt upgrade && sudo apt dist-upgrade && sudo reboot`
- Optionally, add a Wifi access point 
- Optionally, install `sudo pip install -U tzupdate` to update your timezone if you travel
- Optionally, use a [PiJuice](https://github.com/PiSupply/PiJuice) to power it. Install API and RTC sync via service: see install-pijuice.sh.
- Optionally, use autossh to 'phone home'. See install script: install-autossh.sh

#### Now SSH to Pi Zero W and...
```
# install TMV and dependancies
sudo apt install -y python3-pip git python3-picamera
# Pillow dependancies
sudo apt install -y libjpeg-dev libopenjp2-7 libtiff5
git clone https://github.com/brettbeeson/tmv
cd tmv
sudo python3 setup.py install      # local production 
#sudo python3 setup.py develop      # dev
#sudo python3 -m pip install timemv # production from pypi - unlikely to be current
sudo scripts/install-tmv-camera.sh # install systemd services                
sudo scripts/install-autossh.sh    # optional
#sudo scripts/install-pijuice.sh   # optional

```
### Configure Camera
The camera writes images to the local storage
- edit `/etc/tmv/camera.toml` to set file_root, etc.
- Your can turn off the camera's LED via `echo 'disable_camera_led=1' | sudo -a /boot/config.txt`
- (It will then only flash during taking a photo)


### Optionally, configure Camera Uploads
The uploader runs on the camera and sends images to an s3 bucket when possible or locally caches.
- again edit `/etc/tmv/camera.toml` to set s3 upload details such as destination, profile and endpoint
- the directory /home/pi/.aws/ should contain your s3 credentials

### Optionally, make the Pi an access point
Use a out-of-the-box such as [RaspAP](https://github.com/billz/raspap-webgui)(didn't work for me) or manually:
```
wget -O rpi-wifi.sh https://raw.githubusercontent.com/lukicdarkoo/rpi-wifi/master/configure 
chmod 755 rpi-wifi.sh
./rpi-wifi.sh  -a tmv-$HOSTNAME-ap imagines -c "NetComm 0405" 12345678
```
See [more info](http://brettbeeson.com.au/pizerow-ap-wifi-client/) on setting it 

### Optionally, configure PiJuice
Refer to the docs, but briefly:
- `sudo systemctl enable pijuice`
- `echo dtoverlay=i2c-rtc,ds1339 | sudo -a /boot/config.txt` to enable real time clock
- `pijuice_cli` to get settings

### Optionally, configure autossh
- `sudo vi /etc/systemd/system/autossh.service`

### Start Camera
- browse to [your-pi-ip](http://tmv.local) to see the Camera App and RaspAP. THis allows you to control most everything you need to take photos.
- Alteratnively, ssh to the pi and run manually:
- `sudo tmv-control auto on` to set camera to auto, and uploads to on
- `journalctl -f -u 'tmv*'` to check logs in operation

## Server
Tested on Ubuntu 18, but likely to work on most linux. It converts photos to videos and optionally stores them.

#### Server - store files, make videos
- Install [Minio](https://minio.io) to store your images. You could use any s3 server either local or remote (e.g. AWS)
- Install as a [service script](https://github.com/minio/minio-service/tree/master/linux-systemd). Typically you'll store at /var/s3/my.tmv.bucket
```
cd ~/tmv
sudo scripts/install-minio.sh
```

```
sudo apt install -y python3-pip vim git 
git clone https://github.com/brettbeeson/tmv
cd tmv
sudo python3 -m pip install .
mkdir tmv-data
sudo scripts/install-tmv-videod.sh                 

```

#### Server - serve videos via web server
Any server is ok. I use nginx.
```
sudo apt install -y nginx
rm /etc/nginx/sites-enabled/default
sudo cp scripts/tmv.ngnix tmv/etc/nginx/sites-enabled/
sudo systemctl start nginx
# install h5ai (todo)
```
Browse to [localhost](http://localhost) to view files via the nice h5ai javascript interface. Browse to [localhost:9000](http://localhost:9000) to see minio interface.

#### Further Configure Server (Optional)
- If running locally, a port-forward on your router and a ddyn solution can be setup for external access
- If using Route53 a simple option is (aws-dyndns](https://github.com/famzah/aws-dyndns)


### Random Options for Connecting via AP
- Force ap0 users to go to localhost:5000 (to see tmv-camapp) by 
-- checking 50-tmv.conf (lighttpd): see notes in the file
-- moving raspap (`mv /var/www/html/* /var/www/html/wifi/`) to enable it to escape the redirect
-- modifying dnsmasq.conf:
```
# route all dns to our address!
# server=8.8.8.8 
address=/#/192.168.10.1
```
-- an iptables alterative (route anything on ap0 to localhost) to the lighttpd redirect might be better. Since need DNS queries to point to localhost via dnsmasq in this case (I figure).

### Improvements
- Add DIM/DARK/LIGHT as an Overlay
- Check for 0 length files

Inspired by [Claude's Pi-Timolo](https://github.com/pageauc/pi-timolo/). Thanks Claude!
