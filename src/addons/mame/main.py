import asyncio
import subprocess
import pluggy
from addons.base import BaseAddon

hookimpl = pluggy.HookimplMarker("rumba-remote")


class Mame(BaseAddon):
    """ Provides 3 buttons: 'MAME.ENABLE', 'MAME.RESETEMU' and 'MAME.COIN'
        to start/reset the mame emulator and add credits while playing
        https://www.mamedev.org/

        The addon is modal - the jukebox gets suspended
        when starting mame and resumed again after exiting mame

        The default start command can be changed with the cmd config option eg
        exec mame frogger -autoframeskip -video accel -prescale 1 -nowindow -nofilter
        to select a game on startup or change audio settings
        exec mame -sound portaudio -pa_api ALSA -pa_device "USB Advanced Audio Device: Audio (hw:3,0)"
        > to get a list of available audio devices use
        'mame -verbose -sound portaudio -pa_api ALSA | grep ALSA'

        To use multiple instances of mame game loaders
        (eg for starting multiple games directly)
        see addons.bubblem!
    """

    CONFIRM = {
        'ENABLE': 'start mame?',
        'RESETEMU': 'reset mame?'
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.running = False
        self.cmd = "exec mame -autoframeskip -video accel -prescale 1 -nowindow -nofilter"
        if self.config and self.config.get('cmd', False):
            self.cmd = self.config.get('cmd')
        self.mame = None  # emulator process

    async def do(self, func, val=None):
        """ Calls the addon functions """
        self.log.debug(f'Calling Mame: {func}')
        if func == 'ENABLE':
            await self.controller.changeMode(self)
        elif func == 'RESETEMU':
            await self.controller.resetMode()
        elif func == 'COIN':
            await self.controller.pressKey('9')
        else:
            self.log.warning(f'Method {func} not defined in MAME!')

    def getMenuItems(self):
        """ COIN adds credits while playing, KEY.1/2 start single-/multiplayer game """
        return ['KEY.1', 'KEY.2', 'MAME.COIN', 'MAME.RESETEMU']

    async def start(self):
        """ starts Mame emulation! """
        self.log.debug('starting Mame emulation')
        self.mame = subprocess.Popen(self.cmd, shell=True)
        await asyncio.sleep(5)  # approx mame startup time on rpi4 (no feedback on startup available)
        self.running = True
        self.log.info('Mame emulation started!')

    async def stop(self):
        """ stops Mame emulation """
        self.log.debug('stopping Mame emulation')
        if self.mame:
            self.mame.kill()
            await asyncio.sleep(1)
        self.running = False
        self.log.info('Mame emulation stopped!')

    @hookimpl
    def onClose(self):
        """ kill mame process """
        if self.mame:
            self.mame.kill()
