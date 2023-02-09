# rumba-remote
status display/remote control for rumba music server (using the subsonic protocol)

only features things I needed so far to configure my own collection of devices, but should be extensible enough to expand to other usecases - PRs welcome!


### install
```
apt-get install python3-pip python3-aiohttp python3-evdev 
pip3 install pluggy
```

allow uinput virtual device input via evdev for all users in input group:
```
nano /etc/udev/rules.d/10-evdev-uinput.rules
```
```
KERNEL=="uinput", SUBSYSTEM=="misc", OPTIONS+="static_node=uinput", TAG+="uaccess", GROUP="input", MODE="0660"
```
(evdev.uinput.UInputError: "/dev/uinput" cannot be opened for writing)


install other dependencies if needed by your devices/addons:

##### GPIO:
```
apt-get install raspi-gpio
pip install RPi.GPIO
```
##### pygame:
```
apt-get install fonts-dejavu fonts-freefont-ttf libsdl2-2.0-0 libsdl2-gfx-1.0-0 libsdl2-image-2.0-0 libsdl2-mixer-2.0-0 libsdl2-net-2.0-0 libsdl2-ttf-2.0-0 python3-pygame
```
##### debussy:
```
pip install DBussy
```