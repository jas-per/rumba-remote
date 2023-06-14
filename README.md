# rumba-remote
status display/remote control for rumba music server (using the subsonic protocol)

<p align="center">
<img src="https://jas-per.github.io/rum.ba/raw/posts/230212-remote/01-hex00.jpg" alt="" style="width:640px;align:center;"/>
</p>

<p align="center">
<img src="https://jas-per.github.io/rum.ba/raw/posts/230212-remote/02-4keys01.jpg" alt="" style="width:440px;align:center;"/>
<img src="https://jas-per.github.io/rum.ba/raw/posts/230212-remote/03-4keys02.jpg" alt="" style="width:380px;align:center;"/>
</p>

<p align="center">
<img src="https://jas-per.github.io/rum.ba/raw/posts/230212-remote/04-car-installation.jpg" alt="" style="width:420px;align:center;"/>
<img src="https://jas-per.github.io/rum.ba/raw/posts/230212-remote/05-4keys06.jpg" alt="" style="width:400px;align:center;"/>
</p>

<p align="center">
<img src="https://jas-per.github.io/rum.ba/raw/posts/230212-remote/06-hex05.jpg" alt="" style="width:640px;align:center;"/>
</p>

only features things needed so far to configure my own collection of devices,<br/>
but should be extensible enough to expand to more usecases


### install
```
apt-get install python3-pip python3-aiohttp python3-evdev 
pip3 install pluggy
```

evdev.uinput.UInputError: "/dev/uinput" cannot be opened for writing<br/>
allow uinput virtual device input via evdev for all users in input group:
```
nano /etc/udev/rules.d/10-evdev-uinput.rules
```
```
KERNEL=="uinput", SUBSYSTEM=="misc", OPTIONS+="static_node=uinput", TAG+="uaccess", GROUP="input", MODE="0660"
```



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

### WifiDirect:
```
pip install DBussy
```
This addon integrates WifiDirect with WPS pushbutton method into the control interface.
If you'd like to run the jukebox on an device not integrated into a home network
eg in a car, battery powered jukebox etc connecting the android app by
setting up a normal wireless access point with hostapd is often not very useful.
(eg some versions of android disconnect from this network if your device does not provide proper internet)
By using WifiDirect this is not a problem - you could even connect to another wifi access point simultaneously.
The big issue with WifiDirect that its WPS security is completly broken unless you use
the pushbutton method for authorization, hence the integration into this app.
see `addons/wifidirect/sys/install_linux` for required wpa_supplicant/dhcp-server setup
and modify `~/.config/rumba-remote/p2p.conf` to configure the 'normal' wifi access point
