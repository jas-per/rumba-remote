import asyncio
import logging
import RPi.GPIO as GPIO  # type: ignore
import pluggy

# needs RPi.GPIO package installed
# implements onClose, onToggleMenu, onToggleVideo, onRequestRunning, onToggleConfirm and onServerConnected
hookimpl = pluggy.HookimplMarker("rumba-remote")


class Handler():
    """ Direct input/output via gpio pins
        Plugs into controller and runs in the main aio-eventloop.

        Although in theory RPi.GPIO should be able to handle multiple instances
        using different pins, this is not tested/recommended. use eg i2c with a MCP23017
        for a better approach to connect lots of i/o.
        XXX: cleanup/release i2c-handler
    """
    def __init__(self, config, inputHandler, loop):

        self.log = logging.getLogger('gpio')
        self.log.debug('gpio init started')

        self.inputHandler = inputHandler
        self.outputs = {}  # Menu.1 etc, RUMBA.CONNECTED, RUMBA.VIDEO
        self.blinkTask = None

        GPIO.setmode(GPIO.BOARD)

        # setup GPIO-buttons
        if config.get("input"):
            for cfg in config.get("input").split('\n'):
                try:
                    func, pin = self._parseConfig(cfg)
                    # switch vs pushbutton:
                    # supply pin through lambda to relay on/off state for switch
                    if pin.startswith('s'):
                        pin = int(pin[1:])
                        p = pin
                    else:
                        pin = int(pin)
                        p = None
                    self.log.debug(
                        "setup %s on %s pin %s ('input = %s')",
                        func, 'switch' if p else 'pushbutton', pin, cfg)

                    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
                    GPIO.add_event_detect(
                        pin,
                        GPIO.RISING if p is None else GPIO.BOTH,  # trigger on both flanks vs just once
                        callback=lambda _, f=func, p=p: loop.call_soon_threadsafe(self._callAsync, f, p),
                        bouncetime=400
                    )
                    # call switch functions with initial state after startup
                    if p is not None:
                        self.log.debug('%s(%s) switch pin %s will be called after startup', func, GPIO.input(p), pin)
                        asyncio.ensure_future(self.inputHandler.onInput(func, GPIO.input(p)))

                except ValueError as VE:
                    self.log.error(
                        "config error: 'input=%s'\n%s\ninput config should be should be 'input=FUNCTION, PIN'",
                        cfg, VE)

        # setup GPIO-outputs
        if config.get("output"):
            for output in config.get("output").split('\n'):
                try:
                    func, pin = self._parseConfig(output)
                    self.log.debug("setup %s on pin %s ('output = %s')", func, pin, output)
                    GPIO.setup(int(pin), GPIO.OUT)
                    self.outputs[func] = int(pin)
                except ValueError as VE:
                    self.log.error(
                        "config error: 'output=%s'\n%s\noutput config should be should be 'output=FUNCTION, PIN'",
                        output, VE)

        # quick access to the menu leds
        self.outputsMenu = [pin for (func, pin) in sorted(self.outputs.items()) if func.startswith('MENU')]

    def _callAsync(self, func, pin=None):
        """ input handler - async call of controller on event
            for switch buttons the value of an input pin can be passed along
        """
        val = GPIO.input(pin) if pin is not None else None
        self.log.debug('pressed gpio key: %s(%s)', func, (val if pin is not None else ""))
        asyncio.ensure_future(self.inputHandler.onInput(func, val))

    async def _blink(self, effect='blink'):
        """ async task that blinks/pulses the leds available for menu until stopped """
        cntr = 0
        try:
            while True:
                if effect == 'blink':
                    for pin in self.outputsMenu:
                        GPIO.output(pin, GPIO.HIGH)
                    await asyncio.sleep(0.05)  # short pause in case there is only 1 led available
                    GPIO.output(self.outputsMenu[cntr % len(self.outputsMenu)], GPIO.LOW)
                    cntr += 1
                    await asyncio.sleep(0.4)
                else:  # pulse
                    cntr += 1
                    for pin in self.outputsMenu:
                        GPIO.output(pin, GPIO.LOW if cntr % 2 else GPIO.HIGH)
                    await asyncio.sleep(0.5 if cntr % 2 else 0.2)
        except asyncio.CancelledError:
            for pin in self.outputsMenu:
                GPIO.output(pin, GPIO.HIGH)

    async def _switchLightEffect(self, effect, start=False):
        """ stops current effect if running and starts a new one """
        if self.outputsMenu:
            if self.blinkTask is not None:
                self.log.debug('stoping light effect (gpio)')
                self.blinkTask.cancel()
                await self.blinkTask
                self.blinkTask = None
            if start:
                self.log.debug('start %s lights (gpio)', effect)
                self.blinkTask = asyncio.create_task(self._blink(effect))

    def _parseConfig(self, configLine):
        """ helper to parse cfg eg 'MENU.TOGGLE, 17' """
        func, pin = configLine.split(',')
        return (func.strip(), pin.strip())

    @hookimpl
    def onServerConnect(self, connected):
        """ visual feedback if jukebox is up&running """
        if 'RUMBA.CONNECTED' in self.outputs:
            self.log.debug('onServerConnect triggered: %sCONNECTED!', ("" if connected else "DIS"))
            GPIO.output(self.outputs['RUMBA.CONNECTED'], GPIO.LOW if connected else GPIO.HIGH)

    @hookimpl
    def onToggleVideo(self, videoOut):
        """ visual feedback if jukebox has video out """
        if 'RUMBA.VIDEO' in self.outputs:
            self.log.debug('onToggleVideo triggered: %s!', ("ON" if videoOut else "OFF"))
            GPIO.output(self.outputs['RUMBA.VIDEO'], GPIO.LOW if videoOut else GPIO.HIGH)

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
        if self.outputsMenu:
            self.log.debug('toggle menu: %s (gpio)', menuPage)
            for pin in self.outputsMenu:
                GPIO.output(pin, GPIO.HIGH)
            if menuPage is not None and menuPage > 0:
                for i in range(0, min(menuPage, len(self.outputsMenu))):
                    GPIO.output(self.outputsMenu[i], GPIO.LOW)

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
            turn off leds and gpio release
        """
        self.log.debug('Shutdown, cleanup gpio pins')
        for output in self.outputs.values():
            GPIO.output(output, GPIO.HIGH)
        GPIO.cleanup()
