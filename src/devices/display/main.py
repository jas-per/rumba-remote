import asyncio
import logging
import datetime
from pathlib import Path
import pluggy
from . import pygameUI

# needs pygame package installed
# implements onRequestRunning, onToggleAlert, onToggleConfirm, onToggleMenu,
# onTrackChange, onPosChange, onTogglePlaying and onClose
hookimpl = pluggy.HookimplMarker("rumba-remote")


class Handler():
    """ Handles display devices with or without touch input

        Listens to most of the controller events because almost every
        info should get rendered on the display - the handler decides
        if a full redraw of the display is necessary and does partial
        updates when possible.

        The handler also controls a screen saver that can display slides
        while the jukebox is paused and updates a clock shown on the
        display all the time
    """
    def __init__(self, config, controller, loop):

        self.device = config['type']
        # setup logging
        self.log = logging.getLogger('display')
        if config.get('logLevel') is not None:
            self.log.setLevel(config.get('logLevel'))  # can be different for ui code than general logLevel
        self.log.debug('Display init started')

        # direct access to controller state: needed for ui-redraw on internal trigger (screensaver/clock)
        self.ctrlState = controller.state

        # activate screensaver only if slides found
        self.scrnsvrActivated = False  # screensaver in use
        self.scrnsvrRunning = False  # screensaver showing slides
        self.scrnsvrTimer = None  # next slide timeout running

        slideShowImgs = []
        if config.get('slideshowDir') is not None:
            self.log.debug('Initializing slideshow')
            slideShowImgs = list(Path(config.get('slideshowDir')).glob("**/*.jpg"))
            if len(slideShowImgs) > 0:
                self.scrnsvrTimeout = config.getint('slideshowTimeout', fallback=30)
                self.scrnsvrActivated = True
                self.log.info('%s slideshow images found in %s', len(slideShowImgs), config.get('slideshowDir'))
            else:
                self.log.warning('Not starting slidehow because no images found in %s', config.get('slideshowDir'))
        else:
            self.log.info("Not initializing slideshow, 'slideshowDir' not set in config")

        # init ui
        self.ui = pygameUI.Display(config, controller.appDir, slideShowImgs)
        controller.setDisplayResolution(self.ui.getDisplayResolution())
        if self.scrnsvrActivated:
            self.scrnsvrTimer = asyncio.get_event_loop().call_later(0.01, self.updateSlide)

        # XXX: init touch here (because of its shared state with the display)
        # config.getboolean('touch', fallback=False)

        # start tasks for clock and animations
        asyncio.ensure_future(self.initTasks())
        self.requestRunning = asyncio.Event()

    async def initTasks(self):
        """ startup tasks """
        self.clockTask = asyncio.ensure_future(self.clockTimer())  # updates clock every 60 seconds
        self.loaderTask = asyncio.ensure_future(self.loaderAnimation())  # shows loading animation

    async def loaderAnimation(self):
        """ Task: waits for event to start animation until stopped """
        while True:
            await self.requestRunning.wait()  # blocks
            # partial update possible bc animated part fully covers the previous one
            self.ui.animateLoader()
            await asyncio.sleep(.05)

    async def clockTimer(self):
        """ Task: update clock display every 60 seconds """
        while True:
            # full ui update needed
            self.redrawUI(self.ctrlState)
            # kinda self adjusting - no need for accuracy here
            await asyncio.sleep(int(60 - datetime.datetime.now().second))

    def updateSlide(self):
        """ Show next slide and restart slideshow update task """
        self.log.debug('updating background with next slide')
        self.scrnsvrRunning = True
        # full ui update needed
        self.ui.nextSlide(self.ctrlState)
        self.startScrnsvrTimeout()

    def startScrnsvrTimeout(self):
        """ start/reset timeout to show next slide """
        if self.scrnsvrTimer is not None:
            self.scrnsvrTimer.cancel()
        if self.ctrlState.rumbaActive and not self.ctrlState.jukebox.playing:
            self.scrnsvrTimer = asyncio.get_event_loop().call_later(self.scrnsvrTimeout, self.updateSlide)
            self.log.debug('next slide timer started')
        else:
            self.scrnsvrRunning = False
            self.log.debug('screensaver stopped')

    def stopScrnsvr(self):
        """ stop screensaver timer """
        if self.scrnsvrTimer is not None:
            self.log.debug('stopping screensaver')
            self.scrnsvrTimer.cancel()
        self.scrnsvrRunning = False

    def redrawUI(self, state):
        """ update jukebox state or slideshow image """
        if self.scrnsvrRunning:
            self.log.debug('redraw UI (slideshow)')
            self.ui.updateSlide(state)
        else:
            self.log.debug('redraw UI')
            self.ui.update(state)

    @hookimpl
    def onRequestRunning(self, started, state):
        """ A request to the server starts or stops """
        if started:
            self.log.debug('starting loader animation')
            self.requestRunning.set()
        else:
            self.log.debug('stopping loader animation')
            self.requestRunning.clear()
            self.redrawUI(state)

    @hookimpl
    def onServerConnect(self, connected, state):
        """ Connection to the jukebox server is available/lost """
        if connected:
            self.log.debug('rumba started, enable screensaver')
            self.redrawUI(state)
            self.startScrnsvrTimeout()
        else:
            self.log.debug('external module started, disable screensaver')
            self.stopScrnsvr()
        self.redrawUI(state)

    @hookimpl
    def onModeChange(self, newModule, state):
        """ An addon takes or returns exclusive control
            Screensaver is currently used only
            while the jukebox is running
        """
        if self.scrnsvrActivated:
            if newModule.name != 'rumba':
                self.stopScrnsvr()
            else:
                self.startScrnsvrTimeout()
        self.redrawUI(state)

    @hookimpl
    def onTrackChange(self, curPos, curSong, state):
        """ Played track changes """
        self.redrawUI(state)

    @hookimpl
    def onPosChange(self, curPos, curSong, state):
        """ Playback position changes (partial update) """
        self.ui.updatePos(curPos, curSong['duration'])

    @hookimpl
    def onTogglePlaying(self, playing, state):
        """ Playback changes (play/pause) """
        if self.scrnsvrActivated:
            if playing:
                self.stopScrnsvr()
            else:
                self.log.debug('starting screensaver')
                self.startScrnsvrTimeout()

    @hookimpl
    def onUserInput(self, state):
        """ Screensaver gets restarted on every user input """
        if self.scrnsvrActivated and not state.jukebox.playing and state.jukebox.curSongs:
            self.log.debug('restarting screensaver')
            self.stopScrnsvr()
            self.redrawUI(state)
            self.startScrnsvrTimeout()

    @hookimpl
    def onToggleMenu(self, menuPage, menu, state):
        """ The menu is shown/hidden or menu page changes """
        self.log.debug('toggle menu: %s - no %s', menu, menuPage)
        if menuPage is None:
            self.redrawUI(state)
        else:
            self.ui.updateMenu(menu)
        if self.scrnsvrActivated:
            self.startScrnsvrTimeout()

    @hookimpl
    def onToggleAlert(self, text, state):
        """ An alert needs to be shown or ends (eg server not found) """
        self.redrawUI(state)

    @hookimpl
    def onToggleConfirm(self, action, confirmText, state):
        """ Confirmation needs to be shown or ends ('doublecklick') """
        self.redrawUI(state)

    @hookimpl
    def onClose(self):
        """ shutdown, stop running tasks """
        self.clockTask.cancel()
        self.loaderTask.cancel()
        if self.scrnsvrTimer is not None:
            self.scrnsvrTimer.cancel()
