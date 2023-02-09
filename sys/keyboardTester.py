#!/usr/bin/python3
import asyncio
import signal
import evdev

# DEFAULT/Values TO START WITH
DEVICENAME = MENUKEY = STARTUPLED = None
KEYS = []
STATUSLEDS = [  evdev.ecodes.LED_NUML,
                evdev.ecodes.LED_CAPSL,
                evdev.ecodes.LED_SCROLLL
                ]

# CHANGE TO CONNECTED KEYS/LEDS
DEVICENAME = 'CHICONY HP Basic USB Keyboard'
MENUKEY = evdev.ecodes.KEY_C
KEYS = [evdev.ecodes.KEY_G,
       evdev.ecodes.KEY_INSERT,
       evdev.ecodes.KEY_DOWN
       ]
STARTUPLED = evdev.ecodes.LED_CAPSL
STATUSLEDS = [ evdev.ecodes.LED_NUML ]


 # XXX: update to input = / output = -configuration!
 # first start: list all devices dann readme: start mit eg -d "CHICONY HP Basic USB Keyboard"
 # second start: blink && keys anzeigen
class Handler():
    """ Use to configure your custom keyboard

        - Start without configured device name
        - Set DEVICENAME to one of the devices shown
        - Start again and see the evcodes of your keys
        - Configure MENUKEY/KEYS and LEDs to test

        HAZ TO BE RUN AS ROOT!

        (USB-) disconnects are handled, but later reconnects are out of scope
    """
    def __init__(self):

        print('Input device init started')

        self.device = None
        self.keyHandler = None
        self.blinkTask = None
        self.blinkTimer = None
        self.menuPage = 0
        self.menuTimer = None

        # find configured device
        devices = [evdev.InputDevice(fn) for fn in evdev.list_devices()]

        for device in devices:
            if 'input0' in device.phys:
                print(f'Input device found: {device}')
                if  device.name == DEVICENAME:
                    try:
                        self.device = device
                        self.device.grab() # become the sole recipient of all incoming input events
                        print(f'Grabbed input device: {device.name}')
                        break
                    except OSError:
                        self.device = None  # already grabbed

        # setup inputs/outputs
        if self.device is not None:
            for led in STATUSLEDS:
                self.device.set_led(led, 0)
            if STARTUPLED is not None:
                self.device.set_led(STARTUPLED, 1)
            # start async keyHandler
            self.keyHandler = asyncio.ensure_future(self._handleKeyEvents())
            # no menukey configured: blink leds for testing
            if STATUSLEDS and MENUKEY is None:
                # start blinking all leds
                self.blinkTask = asyncio.ensure_future(self.blink())
        elif DEVICENAME is not None and DEVICENAME != '':
            print(f'Input device "{DEVICENAME}" not found! Please change name or check connection')
        else:
            print('Listing all devices because no input device configured!\nPlease provide name of device to select')

    async def _handleKeyEvents(self):
        """ key handler - controller gets called async on event """
        async for event in self.device.async_read_loop():
            if event.type == evdev.ecodes.EV_KEY:
                e = evdev.categorize(event)
                if e.keystate == 0:  # trigger on KEY_UP
                # if e.keystate == 1:  # trigger on KEY_DOWN
                    print(f'KEY pressed {e.keycode} - {e.scancode}')
                    if e.scancode == MENUKEY and len(STATUSLEDS) > 0:
                        if len(STATUSLEDS) > 1:
                            newPage = (self.menuPage + 1) % len(STATUSLEDS)
                        else:
                            newPage = int(not self.menuPage)
                        print(f'KEY is configured: (MENUKEY - PAGE{newPage})')
                        self.updateMenuState(newPage)
                    elif self.menuPage > 0:
                        if self.blinkTask is None:
                            self.blinkTask = asyncio.ensure_future(self.blink())
                        self.startBlinkTimeout()
                    if e.scancode in KEYS:
                        print(f'KEY is configured: (menu {KEYS.index(e.scancode) + 1})')

    async def blink(self):
        """ async task that lights all available leds one after the other until stopped """
        cntr = 0
        try:
            while True:
                if len(STATUSLEDS) > 1:
                    #for led in LEDS:
                    #    self.device.set_led(led, 1)
                    #await asyncio.sleep(4)
                    for led in STATUSLEDS:
                        self.device.set_led(led, 0)
                    self.device.set_led(STATUSLEDS[cntr % len(STATUSLEDS)], 1)
                    cntr += 1
                    await asyncio.sleep(0.4)
                elif len(STATUSLEDS) > 0:
                    self.device.set_led(STATUSLEDS[0], 1)
                    await asyncio.sleep(0.4)
                    self.device.set_led(STATUSLEDS[0], 0)
                    await asyncio.sleep(0.4)
        except (OSError, AttributeError):
            print(f'usb-disconnect: {self.device}')
            self.device = None
            self.onClose()
            return False # stop this timer
        except asyncio.CancelledError:
            if self.device is not None:
                for led in STATUSLEDS:
                    self.device.set_led(led, 0)

    def startMenuTimeout(self):
        """ start/reset timeout to reset menu to page 0 """
        if self.menuTimer is not None:
            self.menuTimer.cancel()
        self.menuTimer = asyncio.get_event_loop().call_later(5, self.updateMenuState) # 5 seconds timeout

    def startBlinkTimeout(self):
        """ stops blinking leds in 10 seconds """
        if self.menuTimer is not None:
            self.menuTimer.cancel()
        if self.blinkTimer is not None:
            self.blinkTimer.cancel()
        self.blinkTimer = asyncio.get_event_loop().call_later(10, self.stopBlink) # 10 seconds timeout

    def stopBlink(self):
        """ stops blink task """
        if self.blinkTask is not None:
            self.blinkTask.cancel()
            self.blinkTask = None
        self.menuPage = 0

    def updateMenuState(self, newPage=0):
        """ indicate currently active menu page with configured statusleds """
        try:
            self.stopBlink()
            for led in STATUSLEDS:
                self.device.set_led(led, 0)
            if newPage == 0:
                self.menuPage = 0
            elif newPage <= len(STATUSLEDS):
                for led in range(newPage):
                    self.device.set_led(STATUSLEDS[led], 1)
                self.menuPage = newPage
                self.startMenuTimeout()
            else:
                print(f'not enough leds configured to indicate menu page no.{newPage}') # shouldn't happen
        except OSError:  # usb-device got disconnected
            print(f'usb-disconnect: {self.device}')
            self.device = None
            self.onClose()

    def onClose(self):
        """ kills tasks, remove keyhandler and turn off leds """
        try:
            if self.device is not None:
                print(f'closing device: {self.device}')
                self.stopBlink()
                if self.menuTimer is not None:
                    self.menuTimer.cancel()
                if STARTUPLED is not None:
                    self.device.set_led(STARTUPLED, 0)
                self.device.ungrab()
        except OSError:
            pass  # usb-device got disconnected somewhere down the road.. nevermind
        finally:
            if self.keyHandler:
                self.keyHandler.cancel()
                self.keyHandler = None
        asyncio.get_event_loop().stop()


async def wait4close():
    """ clean shutdown, waits for closing tasks """
    await asyncio.gather(*asyncio.all_tasks() - {asyncio.current_task()})

if __name__ == "__main__":

    # setup loop & controller
    loop = asyncio.get_event_loop()
    inputHandler = Handler()

    if inputHandler.device is not None:

        # term handler
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, inputHandler.onClose)

        try:
            loop.run_forever()
        except KeyboardInterrupt:
            pass
        finally: # also called when loop stops on SIGTERM
            # give canceled tasks the last chance to run
            loop.run_until_complete(wait4close())
            loop.close()
