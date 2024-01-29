# GSPS ATCG
```
sudo apt install git python3-pip

git clone https://github.com/hologram-io/python-messaging.git
cd python-messaging/
sudo apt install python3-setuptools
sudo python3 setup.py install

sudo apt install python3-serial
sudo pip3 install flask-sock

udevadm info -a -p  $(udevadm info -q path -n /dev/ttyACM0)
```


```
How to Bind certain USB to /dev/
1. connect all the device , find the udev information

udevadm info -a -n /dev/ttyUSB0
 
e.g:
ATTRS{idProduct}=="23a3"
ATTRS{idVendor}=="067b"
ATTRS{manufacturer}=="Prolific Technology Inc. "
ATTRS{serial}=="AFDDb119D15"

2. add rules on /etc/udev/rules.d

vi /etc/udev/rules.d/idp-1.rules
ACTION=="add", ATTRS{idVendor}=="067b", ATTRS{idProduct}=="23a3", ATTRS{serial}=="AFDDb119D15",  SYMLINK+="idp1", TAG+="systemd", ENV{SYSTEMD_WANTS}="idp-atcg-st6100.service"

udevadm control --reload

3. verify , make sure symlink created

ls -lah /dev



3 create  service 
vi /etc/systemd/system/idp-atcg-st6100.service

[Unit]
Description=Inmarsat IDP ATCG ST6100
BindsTo=dev-idp1.device
After=dev-idp1.device

[Install]
WantedBy=dev-idp1.device

[Service]
Type=simple
ExecStart=/usr/bin/python3 /home/pi/idp-atcg-st6100/webserver.py


4. restart daemon 
systemctl daemon-reload 
systemctl enable idp-atcg-st6100.service
  

5. modify /home/pi/idp-atcg-st6100/idp_serial.py
adjust the portname 

6.debugging 
journalctl -f -u idp-atcg-st6100.service
dmesg
lsusb
```
