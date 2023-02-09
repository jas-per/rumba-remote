import asyncio
import subprocess
import pluggy
from addons.base import BaseAddon

hookimpl = pluggy.HookimplMarker("rumba-remote")


class C64(BaseAddon):
    """ Provides 2 buttons: 'C64.ENABLE' and 'C64.RESETEMU'
        to start/reset the vice c64 emulator https://vice-emu.sourceforge.io/

        The addon is modal - the jukebox gets suspended
        when starting the emulator and resumed again after exiting c64

        The default start command can be changed with the cmd config option eg
        x64 /home/pi/bbobble.vsf
        to select a game on startup or change audio settings
        x64 -sounddev alsa -soundarg plughw:CARD=Device,DEV=0 /home/pi/bbobble.vsf
        to get a list of available audio devices use 'aplay -L'

        To use multiple instances of c64 game loaders
        (eg for starting multiple games directly)
        see addons.bublbobl!
    """

    CONFIRM = {
        'ENABLE': 'start c64?',
        'RESETEMU': 'reset c64?'
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.running = False
        self.cmd = ['x64']
        if self.config and self.config.get('cmd', False):
            self.cmd = self.config.get('cmd').split(' ')
        self.vice = None  # emulator process

    async def do(self, func, val=None):
        """ Calls the addon functions """
        self.log.debug(f'Calling c64: {func}')
        if func == 'ENABLE':
            await self.controller.changeMode(self)
        elif func == 'RESETEMU':
            await self.controller.resetMode()
        else:
            self.log.warning(f'Method {func} not defined in C64!')

    def getMenuItems(self):
        """ Enables Quickload and Quicksave default key combos in vice/x64
        """
        return ['KEY.LEFTALT+P.P', 'KEY.LEFTALT+F10.QL', 'KEY.LEFTALT+F11.QS', 'C64.RESETEMU']

    async def start(self):
        """ starts c64 emulation! """
        self.log.debug('starting c64 emulation')
        self.vice = subprocess.Popen(self.cmd)
        await asyncio.sleep(5)  # approx vice64 startup time on rpi4 (no feedback on startup available)
        self.running = True
        self.log.info('c64 emulation started!')

    async def stop(self):
        """ stops c64 emulation """
        self.log.debug('stopping c64 emulation')
        if self.vice:
            self.vice.kill()
            await asyncio.sleep(1)
        self.running = False
        self.log.info('c64 emulation stopped!')

    @hookimpl
    def onClose(self):
        """ kill x64 process """
        if self.vice:
            self.vice.kill()
