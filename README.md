# Time, Made Visible

TMV provides a "camera to video" timelapse system. The system is comprised of:
- Raspberry PiZeroW camera: take photos, save to disk, upload to S3. USB or battery-and-solar-powered.
- MinIO or AWS S3 server: store photos and videos, store static web pages. 
- Video Encoder: linux box that makes videos from images. Can be seperate from S3 server or combined.
- Web App: browse S3 and display photos and videos. Runs on local browser from static files served from S3 bucket.

## Installation 
### Camera
Testing on a PiZeroW. This is only one of many options on how to setup.
- Setup a the pizero [as described](https://brettbeeson.com.au/raspberry-pi-setup-zerow/) including wifi, camera and ssh.

#### Now SSH to Pi Zero W and...
```
sudo apt install -y python3-pip git
git clone https://github.com/brettbeeson/tmv
cd tmv
sudo scripts/install-tmv.sh
```
### Configure Camera
The camera writes images to the local storage
- edit `/etc/tmv/camera.toml` to set tmv_root, etc.

### Optionally, configure Camera Uploads
Use rclone:
- install and configure rclone, using sftp (i.e. scp) with password file specified (ssh-agent didn't work)
- add a cron job via `crontab -e`
- this will move image files to your server

```
# crontab entries
*/10 * * * * rclone -v move --include '**/*T*.jpg' ~/tmv-data aws:tmv-data/$HOSTNAME/daily-photos >> ~/rclone.log 2>&1
*/10 * * * * rclone rmdirs ~/tmv-data
```
*Note: tmv-uploader is discontinued. *


### Optionally, make the Pi an access point
Use a out-of-the-box such as [RaspAP](https://github.com/billz/raspap-webgui)(didn't work for me on PiZero) or manually:
- `install-ap.sh` 
- See [more info](http://brettbeeson.com.au/pizerow-ap-wifi-client/) on setting it up.

### Optionally, configure a PiJuice
You can use a [PiJuice](https://github.com/PiSupply/PiJuice) to power it. 
- Install and enable the pijuice (refer to the docs)
-  You need to `echo dtoverlay=i2c-rtc,ds1339 | sudo tee -a /boot/config.txt` to enable real time clock (too scary to do in script)
- `~/tmv/scripts/install-pijuice.sh` to install API and RTC sync via a service

### Optionally, install timezone awareness:
- `sudo pip install -U tzupdate` to update your timezone if you travel

### View Camera
- browse to [your-pi-ip](http://raspberrypi.local) to see the Camera App and RaspAP. THis allows you to control most everything you need to take photos.

### Optionally, view logs and start manually details (ssh to pi first)
- `journalctl -f -u 'tmv*'` to check logs in operation
- `cd ~/tmv` and
-- `python3 tmv/camera.py` to start camera
-- `python3 tmv/upload.py` to start uploader
-- `python3 tmv/interface/interface.py` to start web app, screen, LEDs, etc

## Server
Tested on Ubuntu 18, but likely to work on most linux. It converts photos to videos and optionally stores them. rclone copies image files to the server using 'hostname'. The server runs tasks to resize, make videos, etc. It serves the files via http.

#### Server - store files, make videos

Todo: make a 'camera' and 'video' distribution.

```
sudo apt install -y python3-pip vim git 
git clone https://github.com/brettbeeson/tmv
cd tmv
sudo python3 -m pip install .
mkdir tmv-data
sudo scripts/install-tmv-videod.sh                 
sudo systemctl start tmv-videod

```

#### Server - serve videos via web server
Any server is ok. I use nginx.
```
sudo apt install -y nginx
sudo rm /etc/nginx/sites-enabled/default
sudo cp scripts/tmv.ngnix /etc/nginx/sites-enabled/
sudo systemctl start nginx
# install h5ai (todo - needs gd/im and php)
```
Browse to [localhost](http://localhost) to view files via the nice h5ai javascript interface. Browse to [localhost:9000](http://localhost:9000) to see minio interface.

#### Further Configure Server (Optional)
- If running locally, a port-forward on your router and a ddyn solution can be setup for external access
- If using Route53 a simple option is (aws-dyndns](https://github.com/famzah/aws-dyndns)
- An S3 bucket is another option - use server: minio, aws, client: boto, rclone and map the bucket to a filesystem


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

### Battery Notes
These readings were done from the PiJuice (pj.status.GetIoCurrent) using the camera running at 30s intervals (3s fast, 300s slow).

#### With PiCamera always constructed (old code)
- inactive: 465mA (camera is still constructed)
- fast speed photos: 1160 mA
- medium: 800 mA (solid reading)

... and now with all TMV services off ...

- Base level (idle): 220 mA
- just camera init in python: 720mA  (so camera on = consumption)
- just tmv+uploader, no camera: 305mA (tmv-interface @ 2% cpu)

*Summary: the camera should be destroyed / closed() when not in use*

### PiCamera constructed on demand and destroyed, medium speed (new code)
- No screen: 252 mA 
- OLED Screen off (.hide()): 350mA
- OLED screen on: 475mA

*Summary: need about a 4000mAh to run for a 18h day or 6000mAh with screen*

### PiCamera constructed on demand and destroyed, OLED screen off (new code)

### PiCamera constructed on demand and destroyed, OLED screen on (new code)

# Development Setup
Use venv, setuptools and pip. Using Python3.9.
- * install python3.9 on machine *
- `cd ~/tmv`
- `python3 -m venv venv`
- `. venv/bin/activate`
- `pip install -e .` # install dependancies in vnev

Using pytest.
- `pytest --collect-only tests` 
- `pytest tests`

Inspired by [Claude's Pi-Timolo](https://github.com/pageauc/pi-timolo/). Thanks Claude!
