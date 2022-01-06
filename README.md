# GSPS ATCG


git clone https://github.com/hologram-io/python-messaging.git
cd python-messaging/
sudo apt install python3-setuptools
python3 setup.py install

sudo apt install python3-serial
sudo pip3 install flask-sock

udevadm info -a -p  $(udevadm info -q path -n /dev/ttyACM0)