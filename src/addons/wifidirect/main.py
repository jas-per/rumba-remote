import asyncio
import os
import subprocess
import pluggy
from addons.base import BaseAddon
from . import ravel

hookimpl = pluggy.HookimplMarker("rumba-remote")


class Wifidirect(BaseAddon):
    """ This addon integrates WifiDirect with WPS pushbutton method into the control interface.
        If you'd like to run the jukebox on an device not integrated into a home network
        eg in a car, battery powered jukebox etc connecting the android app by
        setting up a normal wireless access point with hostapd is often not very useful.
        (eg some versions of android disconnect from this network if your device does not provide proper internet)
        By using WifiDirect this is not a problem - you could even connect to another wifi access point simultaneously.
        The big issue with WifiDirect that its WPS security is completly broken unless you use
        the pushbutton method for authorization, hence the integration into this app.
        see addons/wifidirect/sys/install_linux for required wpa_supplicant/dhcp-server setup
        and modify ~/.config/rumba-remote/p2p.conf to configure the 'normal' wifi access point
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.config and self.config.get('interface', False):
            interface = self.config.get('interface')
        else:
            interface = 'wlan0'

        if self.config and self.config.get('cfgFile', False) and os.path.isfile(self.config.get('cfgFile')):
            cfgFile = self.config.get('cfgFile')
        else:
            from shutil import copy
            addonCfgFile = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'sys', 'p2p.conf')
            copy(addonCfgFile, self.controller.configDir)
            cfgFile = os.path.join(self.controller.configDir, 'p2p.conf')

        self.dbus = ravel.system_bus()
        self.dbus.attach_asyncio(asyncio.get_event_loop())  # XXX: ref running loop in controller for python >3.10
        self.P2PDevice = None
        self.WPS = None

        self.initP2P(interface, cfgFile)

    def initP2P(self, wifiInterface, configFilePath):
        """ Starts wpa_supplicant via DBUS, initializes a p2p-group with dhcp-server
            and connects a listener for incoming wps connection requests
        """
        self.log.info('Initializing WifiDirect Handler')
        wpa_supplicant = self.dbus['fi.w1.wpa_supplicant1']['/fi/w1/wpa_supplicant1']\
            .get_interface('fi.w1.wpa_supplicant1')
        self.log.debug('Wireless Interfaces found: %s', wpa_supplicant.Interfaces)

        for interface in wpa_supplicant.Interfaces:
            # just reconnect wps listener if p2p has been started already (when restarting rumba-remote)
            ifName = self.dbus['fi.w1.wpa_supplicant1'][interface]\
                .get_interface('fi.w1.wpa_supplicant1.Interface').Ifname

            if ifName.startswith('p2p'):
                self.log.debug('Reconnecting WPS Interface %s', interface)
                self.WPS = self.dbus['fi.w1.wpa_supplicant1'][interface]\
                    .get_interface('fi.w1.wpa_supplicant1.Interface.WPS')
            elif ifName == wifiInterface:
                self.log.debug('Reconnecting P2P Interface %s', interface)
                self.log.debug('Adding PBC Handler')
                self.P2PDevice = self.dbus['fi.w1.wpa_supplicant1'][interface]\
                    .get_interface('fi.w1.wpa_supplicant1.Interface.P2PDevice')
                self.dbus.listen_signal(
                    interface='fi.w1.wpa_supplicant1.Interface.P2PDevice',
                    fallback=True,
                    func=self.onPBCRequest,
                    path=interface,
                    name='ProvisionDiscoveryPBCRequest'
                )

        if self.P2PDevice is None:
            # p2p interface not found -> start initialization
            self.log.debug('Setup Wifi Device')
            self.dbus.listen_signal(
                interface='fi.w1.wpa_supplicant1',
                fallback=True,
                func=self.onInterfaceAdded,
                path='/fi/w1/wpa_supplicant1',
                name='InterfaceAdded'
            )
            wpa_supplicant.CreateInterface({
                'Ifname': ('s', wifiInterface),
                'Driver': ('s', 'nl80211'),
                'ConfigFile': ('s', configFilePath)
            })
        else:
            self.log.info('Success: Reconnected WifiDirect!')

    @ravel.signal(name='InterfaceAdded', in_signature='oa{sv}', arg_keys=('interface', 'props'))
    async def onInterfaceAdded(self, interface, props):
        """ Setup listeners for group-start and incoming wps pbc before creating p2p-group """
        self.log.debug('Setup P2P Device')
        if props['Ifname'] and not props['Ifname'][1].startswith('p2p'):
            self.log.debug('Connecting P2P Interface %s', interface)
            self.log.debug('Adding PBC Handler')
            self.P2PDevice = self.dbus['fi.w1.wpa_supplicant1'][interface]\
                .get_interface('fi.w1.wpa_supplicant1.Interface.P2PDevice')
            self.dbus.listen_signal(
                interface='fi.w1.wpa_supplicant1.Interface.P2PDevice',
                fallback=True,
                func=self.onGroupStart,
                path=interface,
                name='GroupStarted'
            )
            self.dbus.listen_signal(
                interface='fi.w1.wpa_supplicant1.Interface.P2PDevice',
                fallback=True,
                func=self.onPBCRequest,
                path=interface,
                name='ProvisionDiscoveryPBCRequest'
            )
            self.log.debug('Creating P2P-Group on %s', interface)
            self.P2PDevice.GroupAdd({'persistent': ('b', True)})

    @ravel.signal(name='GroupStarted', in_signature='a{sv}', arg_keys=('props',))
    async def onGroupStart(self, props):
        """ Start dhcp server after goup was successfully created """
        self.log.debug('P2P Group started on  %s', props['interface_object'])
        if self.WPS is None:
            self.log.debug('Connecting WPS Interface')
            self.WPS = self.dbus['fi.w1.wpa_supplicant1'][props['interface_object'][1]]\
                .get_interface('fi.w1.wpa_supplicant1.Interface.WPS')

            await asyncio.sleep(4)  # startup time needed for dhcp to find interface XXX: ask via dbus if ready?
            self.log.debug('Starting DHCP server')
            await (
                await asyncio.create_subprocess_exec(
                    'sudo', 'service', 'isc-dhcp-server', 'start',
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ).wait()
            self.log.debug('DHCP server started')
            self.log.info('Success: WifiDirect initialized!')

    @ravel.signal(name='ProvisionDiscoveryPBCRequest', in_signature='o', arg_keys=('peer',))
    async def onPBCRequest(self, peer):
        """ This handler get called on incoming pbc requests.
            Asks for confimation via controller
            and accepts or rejects the peer from the group
        """
        peerInfo = self.dbus['fi.w1.wpa_supplicant1'][peer].get_interface('fi.w1.wpa_supplicant1.Peer')
        devAddress = ':'.join([f'{n:0>2X}' for n in peerInfo.DeviceAddress])
        self.log.info('Connection Request from %s (%s)', peerInfo.DeviceName, devAddress)

        accept = await self.controller.getConfirm(
            f'Accept WifiDirect Request from\n{peerInfo.DeviceName}?',
            'WIFIDIRECT.CONNECT'
        )
        if accept:
            self.log.info('Accepting Connection Request from %s (%s)', peerInfo.DeviceName, devAddress)
            self.WPS.Start({
                'Role': ('s', 'registrar'),
                'Type': ('s', 'pbc'),
                'P2PDeviceAddress': ('ay', peerInfo.DeviceAddress)
            })
        else:
            self.log.info('Denying Connection Request from %s (%s)', peerInfo.DeviceName, devAddress)
            self.P2PDevice.RejectPeer(peer)

    @hookimpl
    def onClose(self):
        """ leaving P2P-Interface running on app shutdown """
        self.log.debug('Closing WPS Handler, leaving P2P-Interface running')
