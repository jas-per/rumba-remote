import asyncio
import logging
import evdev
import pluggy
from config import ConfigError

# needs evdev package installed
# implements onClose, onToggleMenu, onToggleVideo, onRequestRunning, onToggleConfirm and onServerConnected
hookimpl = pluggy.HookimplMarker("rumba-remote")


class Handler():
    """ Handles input devices on Linux directly via evdev (https://en.wikipedia.org/wiki/Evdev)
        Plugs into controller and runs in the main aio-eventloop.

        All devices available via evdev can be used if their exact name is suppplied,
        if no name is configured a device must have keys and status leds to be considered.
        Multiple instances can be configured to connect multiple devices at the same time.

        Keyboards usually have at least 3 leds for shift-, num- and scroll-lock,
        these can provide a simple visual feedback

        Use sys/keyboardTester.py to find keyboard names and keycodes to set up your config

        (USB-) disconnects are handled, but later reconnects are not - out of scope
        because you'd need to listen to udev/dbus which complicates things a bit.
        If your environment supports this see devices/dbus.py for async dbus-handling
        via 'dbussy' or implement a plugin device directly via udev with eg 'pyudev'
    """
    def __init__(self, config, controller, loop):

        self.log = logging.getLogger('keyboard')
        self.log.debug('Input device init started')

        self.controller = controller
        self.device = None
        self.keyHandler = None
        self.blinkTask = None
        self.outputs = {}  # kbd leds
        self.outputsMenu = []  # kbd leds that indicate current menu page, also used as blink/pulse indicators

        if 'name' in config:  # specific keyboard devices: use device name as the filter
            deviceName = config.get('deviceName', fallback='')
            if deviceName == '':
                raise ConfigError(
                    f'Specific keyboard {config["name"]} configured but no device name given: Ignoring section!')
            config['name'] = deviceName

        # find configured device
        devices = [evdev.InputDevice(fn) for fn in evdev.list_devices()]
        for device in devices:
            # generic keyboards == all devicess with keys and status leds:
            # successfully filters out strange devices with 'keys' like hdmi-cec etc
            if 'input0' in device.phys:
                self.log.debug('Input device found: %s', device)
                if 'name' in config and device.name == config['name'] or\
                   'name' not in config and\
                   evdev.ecodes.EV_KEY in device.capabilities() and\
                   evdev.ecodes.EV_LED in device.capabilities():
                    try:
                        self.device = device
                        self.device.grab()  # become the sole recipient of all incoming input events
                        self.log.info('Grabbed input device: %s', device.name)
                        break
                    except OSError:
                        self.device = None  # already grabbed, probably by us ;)

        # setup inputs/outputs
        if self.device is not None:
            inputs = config.get("input")
            if not inputs:
                self.onClose()  # release device
                raise ConfigError(
                    f'No inputs configured for {self.device.name}! Ignoring device, please check your configuration')

            configuredInputs = {}
            for cfg in inputs.split('\n'):
                try:
                    func, key = self._parseConfig(cfg)
                    self.log.debug("setup %s on key %s ('input = %s')", func, key, cfg)
                    configuredInputs[key] = func
                except ValueError as VE:
                    self.log.error(
                        "config error: 'input=%s'\n%s\ninput config should be should be 'input=FUNCTION, KEY'",
                        cfg, VE)
                except KeyError:
                    self.log.warning(
                        'Illegal key configured: %s! See config-file for details on legal ecodes', key)

            if config.get("output"):
                for output in config.get("output").split('\n'):
                    try:
                        func, led = self._parseConfig(output)
                        self.log.debug("setup %s on led %s ('output = %s')", func, led, output)
                        self.outputs[func] = led
                    except AttributeError:
                        pass  # No outputs configured
                    except ValueError as VE:
                        self.log.error(
                            "config error: 'output=%s'\n%s\noutput config should be should be 'output=FUNCTION, LED'",
                            output, VE)

            # quick access to the menu leds
            self.outputsMenu = [led for (func, led) in sorted(self.outputs.items()) if func.startswith('MENU')]

            # start async keyHandler and supply key/func-mapping
            self.keyHandler = asyncio.ensure_future(self._handleKeyEvents(configuredInputs))
        else:
            devName = config['name'] if 'name' in config else 'Generic Keyboard'
            self.log.warning('Configured input device "%s" not found! Please check connection or config.', devName)

    async def _handleKeyEvents(self, configuredInputs):
        """ key handler - controller gets called async on event """
        async for event in self.device.async_read_loop():
            if event.type == evdev.ecodes.EV_KEY:
                e = evdev.categorize(event)
                if e.keystate == 1 and e.scancode in configuredInputs:  # trigger on KEY_RELEASE
                    try:
                        self.log.debug(
                            'pressed key %s - %s (%s)',
                            e.keycode, e.scancode, configuredInputs[e.scancode])
                        asyncio.ensure_future(self.controller.onInput(configuredInputs[e.scancode]))
                    except Exception as e:  # pylint: disable=broad-except
                        # catchall to avoid getting unresponsive
                        self.log.error(e)

    async def _blink(self, effect='blink'):
        """ async task that blinks/pulses the leds available for menu until stopped """
        cntr = 0
        try:
            while True:
                if effect == 'blink':
                    for led in self.outputsMenu:
                        self.device.set_led(led, 0)
                    await asyncio.sleep(0.05)  # short pause in case there is only 1 led available
                    self.device.set_led(self.outputsMenu[cntr % len(self.outputsMenu)], 1)
                    cntr += 1
                    await asyncio.sleep(0.4)
                else:  # pulse
                    cntr += 1
                    for led in self.outputsMenu:
                        self.device.set_led(led, cntr % 2)
                    await asyncio.sleep(0.5 if cntr % 2 else 0.2)
        except (OSError, AttributeError):
            self.log.warning('usb-disconnect: %s', self.device)
            self.device = None
            return False  # stop this timer
        except asyncio.CancelledError:
            if self.device is not None:
                for led in self.outputsMenu:
                    self.device.set_led(led, 0)

    async def _switchLightEffect(self, effect, start=False):
        """ stops current effect if running and starts a new one """
        if self.outputsMenu and self.device is not None:
            if self.blinkTask is not None:
                self.log.debug('stoping light effect (%s)', self.device)
                self.blinkTask.cancel()
                await self.blinkTask
                self.blinkTask = None
            if start:
                self.log.debug('start %s lights (%s)', effect, self.device)
                self.blinkTask = asyncio.create_task(self._blink(effect))

    def _parseConfig(self, configLine):
        """ helper to parse cfg eg 'MENU.TOGGLE, KEY_3' """
        func, key = configLine.split(',')
        key = evdev.ecodes.ecodes[key.strip()]
        return (func.strip(), key)

    @hookimpl
    def onServerConnect(self, connected):
        """ visual feedback if jukebox is up&running """
        if 'RUMBA.CONNECTED' in self.outputs:
            self.log.debug('onServerConnect triggered: %sCONNECTED!', ("" if connected else "DIS"))
            self.device.set_led(self.outputs['RUMBA.CONNECTED'], connected)

    @hookimpl
    def onToggleVideo(self, videoOut):
        """ visual feedback if jukebox has video out """
        if 'RUMBA.VIDEO' in self.outputs:
            self.log.debug('onToggleVideo triggered: %s!', ("ON" if videoOut else "OFF"))
            self.device.set_led(self.outputs['RUMBA.VIDEO'], videoOut)

    @hookimpl
    def onToggleMenu(self, menuPage):
        """ visual feedback for currently active menu page
            page 0: no leds
            page 1: 1 led
            page 2: 2 leds etc
            if there are not enough leds available to indicate a page no
            the max number of available leds will be lit
            eg. menupage 3 will only light 2 leds if no more are available
        """
        if self.outputsMenu and self.device is not None:
            self.log.debug('toggle menu: %s (%s)', menuPage, self.device)
            try:
                for led in self.outputsMenu:
                    self.device.set_led(led, 0)
                if menuPage is not None and menuPage > 0:
                    for i in range(0, min(menuPage, len(self.outputsMenu))):
                        self.device.set_led(self.outputsMenu[i], 1)
            except (OSError, AttributeError):
                self.log.warning('usb-disconnect: %s', self.device)
                self.device = None

    @hookimpl
    def onToggleConfirm(self, action):
        """ visual feedback if action needs confimation
            simple blink of status leds one after the other
        """
        asyncio.ensure_future(self._switchLightEffect('blink', start=action is not None))

    @hookimpl
    def onRequestRunning(self, started):
        """ visual feedback while a request is running, pulse status leds
        """
        asyncio.ensure_future(self._switchLightEffect('pulse', start=started))

    @hookimpl
    def onClose(self):
        """ hook gets called when shutting app down
            remove keyhandler and turn off leds
        """
        self.log.debug('Shutdown, closing device: %s', self.device)
        try:
            if self.device:
                if self.blinkTask is not None:
                    self.log.debug('stoping light effect (%s)', self.device)
                    self.blinkTask.cancel()
                    # await self.blinkTask
                    # asyncio.ensure_future(self.blinkTask)
                for output in self.outputs.values():
                    self.device.set_led(output, 0)
                self.device.ungrab()
        except OSError:
            pass  # usb-device got disconnected somewhere down the road.. nevermind
        finally:
            if self.keyHandler:
                self.keyHandler.cancel()
                self.keyHandler = None
