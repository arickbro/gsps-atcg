echo "install depedencies"
git clone https://github.com/hologram-io/python-messaging.git
cd python-messaging/
sudo apt install python3-setuptools
sudo python3 setup.py install
cd ..
sudo rm -rf python-messaging/
sudo apt install python3-serial
sudo pip3 install flask-sock

echo "install systemd"
sudo cp install/gsps-atcg.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable gsps-atcg.service
sudo systemctl start gsps-atcg.service

echo "install udev"
sudo cp install/90-usb.inmarsat.rules /etc/udev/rules.d/
