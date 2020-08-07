# run from ~/tmv/
cd ~/tmv

# get minio binary and setup
wget https://dl.min.io/server/minio/release/linux-amd64/minio
chmod +x minio
sudo mv minio /usr/local/bin
sudo cp scripts/minio /etc/default/
echo Edit /etc/default/minio and set password

# make a repo
sudo mkdir /var/minio
sudo chown bbeeson /var/minio
sudo chgrp bbeeson /var/minio
echo Check ownership of /var/minio

# run as a service
sudo cp scripts/minio.service /etc/systemd/system/
echo Edit /etc/systemd/system/minio.service and set user
sudo systemctl enable minio.service
sudo systemctl start minio.service

