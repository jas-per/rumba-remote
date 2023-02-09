import asyncio
import subprocess
import pluggy
from addons.base import BaseAddon

hookimpl = pluggy.HookimplMarker("rumba-remote")


class Projectm(BaseAddon):
    """ Integrates projectm-visualizer (https://github.com/projectM-visualizer/projectm)
        Provides enable/disable buttons: 'PROJECTM.MILKDROP' and 'PROJECTM.MUSIC'
        and listens to disconnect/video-out events to automatically disable the visualizer if needed

        ProjectM gets started/stopped as a service, use "projectM.service" from the sys dir
    """

    CONFIRM = {
        'MILKDROP': 'start visualizer?',
        'MUSIC': 'stop visualizer?'
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # projectm might take way!! longer to start if lots of presets need to be loaded
        # you can manually adjust this value via config
        if self.config:
            self.startupTime = self.config.getfloat('startupTime', 5.0)
        else:
            self.startupTime = 5
        self.running = False

    def do(self, func, val=None):
        """ Only one function: toggle the visualizer """
        return self.toggleViz()

    def getIcon(self, func):
        """ selecting on/off-icon based on addon-state """
        return f"PROJECTM.{'MUSIC' if self.running else 'MILKDROP'}"

    async def toggleViz(self):
        """ Stops running visualizer or starts new viz if jukebox running and video output enabled
        """
        if not self.controller.state.requestRunning:
            self.controller.changeRequestRunning(True)
            if self.running:
                self.log.debug('Stopping visualizer')
                await (await asyncio.create_subprocess_exec(
                    'sudo', 'service', 'projectM', 'stop',
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                ).wait()
                if self.controller.videoEnabled:
                    await self.controller.rumba('toggleVideoOut', enabled=1, syncronized=False)
                self.running = False
            else:
                if not self.controller.videoEnabled:
                    self.log.warn('Not starting visualizer, video out is disabled')
                elif not self.controller.state.rumbaActive:
                    self.log.warn('Not starting visualizer, jukebox is not running')
                else:
                    self.log.debug('Starting visualizer')
                    await self.controller.rumba('toggleVideoOut', enabled=0, syncronized=False)
                    await (await asyncio.create_subprocess_exec(
                        'sudo', 'service', 'projectM', 'start',
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    ).wait()
                    await asyncio.sleep(self.startupTime)
                    self.log.info('Visualizer started!')
                    self.running = True
            # if menu shown 'force' update (by changing to None and back again)
            curMenu = self.controller.state.menuPage
            if curMenu is not None:
                self.controller.updateMenuState()
                self.controller.updateMenuState(curMenu)
            self.controller.changeRequestRunning()

    @hookimpl
    def onServerConnect(self, connected):
        """ stop visualizer if jukebox gets turned off """
        if self.running and not connected:
            self.log.debug('Server disconnect, turning visualizer off')
            asyncio.ensure_future(self.toggleViz())

    @hookimpl
    def onToggleVideo(self, videoOut):
        """ stop visualizer if video output gets disabled """
        if self.running and not videoOut:
            self.log.debug('Video toggled off, turning visualizer off as well!')
            asyncio.ensure_future(self.toggleViz())

    @hookimpl
    def onClose(self):
        """ stop visualizer """
        if self.running:
            asyncio.ensure_future(self.toggleViz())
