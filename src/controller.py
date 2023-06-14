import asyncio
import subprocess
import importlib
import logging
from dataclasses import dataclass
from typing import List, Optional, Any
import pluggy
import evdev
import server as jukebox

hookspec = pluggy.HookspecMarker("rumba-remote")


@dataclass
class State:
    """ All internal state that can be shared with addons (eg display) """
    jukebox: jukebox.JukeboxState
    menu: Optional[List[int]] = None  # actions currently shown in menu List[int]
    menuPage: Optional[int] = None  # currently shown menu page
    activeModule: Optional[Any] = None  # Optional[Module]
    requestRunning: bool = False  # synchronizes user interaction with the Jukebox
    confirmState: Optional[bool] = None  # modal confirmation dialog
    confirmTarget: Optional[int] = None  # for user input that has to be confirmed with dialog
    confirmText: str = ''  # text for confirmation dialog
    alert: str = ''  # text for alert dialog

    @property
    def bgImage(self):
        """ Optional path to current background image, None gets default image """
        if self.activeModule is not None:
            return self.activeModule.getBackgroundImage()
        return None  # use default image

    @property
    def rumbaActive(self):
        """ Info about toggle between rumba jukebox and modal addons """
        return self.activeModule.name == 'rumba'

    @property
    def toggleAction(self):
        """ Action for toggle button """
        return 'MENU.TOGGLE' if self.activeModule.name == 'rumba' else 'RUMBA.ENABLE'


# lots of additional methods bc all pluggy-hooks are directly defined here..
# pylint: disable=too-many-public-methods, too-many-instance-attributes
class InputHandler():
    """ Controller with connection to jukebox. User input from various devices
        is forwarded and state changes on the jukebox are converted to events
        output devices like displays or leds can subscribe to.
        State for event updates is kept in the controller, all jukebox state
        is handled in the connector. ッ
    """
    CONFIRM = {
        'STAR': 'star ?',
        'UNSTAR': 'unstar ?',
        'RANDOM': 'random tracks ?',
        'APPROX': 'add similar tracks ?',
        'ENABLE': 'start rumba ?',
        'BANANAS': 'go bananas ?',
        'OK': 'ay, captain !'
    }

    def __init__(self, config, pluginManager):
        self.log = logging.getLogger('ctrl')
        self.appDir = config['controller']['appDir']  # app base directory
        self.configDir = config['controller']['configDir']  # base directory for config files

        self.menuRows = config['controller']['menuRows']
        self.menuTimeout = config['controller']['menuTimeout']
        self.menuTimer = None  # schedules call to menu hide()
        self.confirmModal = None  # synchronizes feedback for direct confirmation
        self.videoEnabled = config['controller']['enableVideo']
        self.config = config['controller']  # ref for delayed init of addons

        # init connection to Jukebox and internal state
        self.server = jukebox.Connector(config['jukebox'], self.serverCallback)
        self.state = State(self.server.jukebox)

        self.modules = {}
        self.modules['RUMBA'] = self.modules['KEY'] = self
        self.keyInjector = self.initKeyboard()
        self.state.activeModule = self
        self.name = 'rumba'

        self.pm = pluginManager

        # load addons configured explicitly for startup init (lazy loading for all others)
        for addon in config['controller']['initAddons']:
            self.getModule(addon)

        self.updateMenuState()  # init menu

        # async init (after loop is running) for tasks
        asyncio.ensure_future(self.initTasks())

    def initKeyboard(self):
        """ To map (gpio-)keypress, touch input etc to shortcuts/hotkeys inside
            running applications a virtual keyboard is used. When using X11 this
            is straightforward because every app thats running can receive all
            user input (which is part of the security problems with X11)

            On wayland user input normally gets forwarded to the currently focused window,
            to change that a central dispatcher is needed. A protocol to adress these reqs
            has recently (2022.12) been finalized as part of the XDG desktop portal project:
            https://github.com/flatpak/xdg-desktop-portal/releases/tag/1.16.0

            Until this gets implemented in the wayland compositors keyboard inputs have to be
            directly injected into evdev at the lower (kernel) level. This requires root access
            so a udev rule is needed to enable users in the 'input' group to inject keys globally:
>>>
/etc/udev/rules.d/10-evdev-uinput.rules

KERNEL=="uinput", SUBSYSTEM=="misc", OPTIONS+="static_node=uinput", TAG+="uaccess", GROUP="input", MODE="0660"
>>>
            XXX: use proper wayland library, probably via https://gitlab.freedesktop.org/libinput/libei
        """
        # create virtual uinput keyboard with all available keys
        allKeys = [
            key for key in evdev.ecodes.keys
            if isinstance(evdev.ecodes.keys[key], str) and evdev.ecodes.keys[key].startswith('KEY')
        ]
        return evdev.UInput({evdev.ecodes.EV_KEY: allKeys}, name='rumba-remote', version=0x3)

    async def initTasks(self):
        """ startup tasks """
        self.server.initSession()  # connection to jukebox via aiohttp
        self.statusTask = asyncio.ensure_future(self.statusUpdate())  # also performs initial getStatus()

    async def statusUpdate(self):
        """ Task: polling Jukebox status """
        connected = False
        resp = False
        try:
            while True:
                resp = await self.rumba('getStatus', syncronized=False)
                if not resp:
                    if connected:  # connection lost
                        self.changeServerRunning(False)
                    connected = False
                elif not connected:
                    # connection restored
                    connected = True
                    self.changeServerRunning(True)
                    if self.videoEnabled is not None:
                        self.toggleVideoOut(self.videoEnabled)
                if self.state.rumbaActive and self.state.jukebox.playing:
                    await asyncio.sleep(1)
                else:
                    await asyncio.sleep(5)
        except asyncio.CancelledError:
            return
        except Exception as e:  # pylint: disable=broad-except
            # catchall - keep running unless task gets cancelled
            self.log.exception('Exception during status update: %s', e)

    async def do(self, action, val=None):
        """ Maps RUMBA.* action 'constants' from menu or input devices
            and calls the requested methods
        """
        if action == 'PREV':
            await self.rumba('prevSong')
        elif action == 'PLAYPAUSE':
            await self.rumba('startStop')
        elif action == 'NEXT':
            await self.rumba('nextSong')
        elif action == 'SKIP':
            await self.rumba('skip', offset=val)
        elif action == 'STAR':
            await self.rumba('star', starred=True)
            self.updateMenuState(self.state.menuPage)  # redraw menu
        elif action == 'UNSTAR':
            await self.rumba('star', starred=False)
            self.updateMenuState(self.state.menuPage)
        elif action == 'RANDOM':
            await self.rumba('insertRandom')
            self.updateMenuState(0)
        elif action == 'APPROX':
            await self.rumba('insertSimilar')
            self.updateMenuState(0)
        elif action == 'SUBS':
            await self.rumba('toggleSubs')
        elif action == 'LANG':
            await self.rumba('toggleLang')
        elif action == 'ENABLE':
            await self.changeMode()
        elif action == 'BANANAS':  # noop
            self.changeConfirm('RUMBA.OK')
        elif action == 'VIDEO':
            self.toggleVideoOut(val)
        else:
            self.log.exception('Unknown action in key handler: %s', action)

    async def pressKey(self, key):
        """ This is really ugly but hey, at least it is working at all!
            See initKeyboard() why direct evdev-input is a problem with wayland,
            even more so with py-evdevs async input path. While these settings
            do work with everything tested so far, hopefully a proper
            wayland lib can replace all this pretty soon..
        """
        self.changeConfirm()

        # remove abbreviation if present (eg KEY.LEFTCTRL+C.CPY)
        if len(key.split('.')) > 1:
            key = key.split('.')[0]

        # press meta key first if requested
        meta = None
        if len(key.split('+')) > 1:
            meta, key = key.split('+')
            self.log.debug('Injecting with meta key: KEY_%s', meta)
            meta = getattr(evdev.ecodes, f'KEY_{meta}')
            self.keyInjector.write(evdev.ecodes.EV_KEY, meta, 1)  # meta key down
            await asyncio.sleep(0.2)

        self.log.debug('Injecting key: KEY_%s', key)
        key = getattr(evdev.ecodes, f'KEY_{key}')
        self.keyInjector.write(evdev.ecodes.EV_KEY, key, 1)  # key down
        await asyncio.sleep(0.5)
        self.keyInjector.write(evdev.ecodes.EV_KEY, key, 0)  # key up
        await asyncio.sleep(0.4)

        if meta is not None:
            self.keyInjector.write(evdev.ecodes.EV_KEY, meta, 0)  # meta key up
            await asyncio.sleep(0.2)

        self.keyInjector.syn()

    async def rumba(self, action, syncronized=True, **kwargs):
        """ wraps all calls to the Jukebox and emits events for UI etc """
        changed = None
        if syncronized:  # show loader and block multiple concurrent requests/user interactions with the server
            if self.state.requestRunning:
                return
            self.changeRequestRunning(True)
        try:
            changed = await self.server.call(action, **kwargs)
            # reconnected to server - hide alert-window if present
            if self.state.alert != '':
                self.state.alert = ''
                self.onToggleAlert('', self.state)
        except jukebox.JukeboxError as je:
            self.log.exception('JukeboxError: %s', je)  # just log and keep running
        except jukebox.NotFoundError as snfe:
            if self.state.rumbaActive:  # only show server not found if jukebox currently active
                if self.state.jukebox.lastModPLS > 0:
                    self.state.jukebox.reset()
                self.state.alert = str(snfe)
                self.onToggleAlert(str(snfe), self.state)
            else:
                self.state.alert = ''
            return False
        finally:
            if syncronized:
                self.changeRequestRunning()
        # update ui on state change jukebox
        if changed is not None:
            if changed == jukebox.CHANGE.POS:
                # update only if menu not shown / pos is seen onscreen
                if self.state.menuPage is None and self.state.jukebox.curSong is not None:
                    self.onPosChange(self.state.jukebox.curPos, self.state.jukebox.curSong, self.state)
            elif changed in [jukebox.CHANGE.PLAY, jukebox.CHANGE.PLS]:
                self.onTogglePlaying(self.state.jukebox.playing, self.state)
                if self.state.jukebox.curSong is not None:  # don't display empty pos-bar
                    self.onTrackChange(self.state.jukebox.curPos, self.state.jukebox.curSong, self.state)
            else:  # track change
                # update menu state because of potential track specific menu items (eg star)
                self.updateMenuState(self.state.menuPage)
                self.onTrackChange(self.state.jukebox.curPos, self.state.jukebox.curSong, self.state)
        # propagate video changes
        if action == 'toggleVideoOut':
            self.onToggleVideo(kwargs.get('enabled'), self.state)
        return True

    async def onInput(self, action, val=None):
        """ Gets called by input devices with either action/keypress or menukey.
            Menukeys get mapped first and the requested action/keypress is called async.
            Actions can be part of the main/rumba controller (self.do()) or from a
            dynamically loaded module/addon
        """
        self.log.debug('onInput: %s(%s)', action, val)
        try:
            # modal confirmation requested
            if self.confirmModal is not None:
                if action in ('MENU.TOGGLE', 'RUMBA.ENABLE'):
                    self.log.debug('Denying confirmation request')
                    self.state.confirmState = False
                else:
                    self.log.debug('Accepting confirmation request')
                    self.state.confirmState = True
                self.confirmModal.set()
                return
            # toggle menu or map menu key to action
            if action.startswith('MENU'):
                index = action.split('.')[1]
                if index == 'TOGGLE':
                    if self.state.rumbaActive:
                        # toggle current menu row
                        if self.state.confirmTarget is None:
                            if self.state.menuPage is None:
                                # start menu with first page..
                                newPage = 0
                            else:
                                newPage = (self.state.menuPage + 1) % len(self.menuRows)
                            self.updateMenuState(newPage)
                        else:  # just clear confirm dlg if displayed
                            self.changeConfirm()
                    else:
                        # modal addon active, toggle button acts as 'RUMBA.ENABLE'
                        action = 'RUMBA.ENABLE'
                else:
                    # take action from current menu row (button index starts at 1)
                    action = self.state.menu[int(index) - 1]
            # call action
            if action.startswith('KEY.'):  # inject key(-combo)
                await self.pressKey(action.split('.', 1)[1])
            elif action not in ('MENU.TOGGLE', 'MENU.NOTOGGLE'):
                if self.checkDoubleclick(action):
                    mod, func = action.split('.')
                    # loads module if not initialized yet
                    await self.getModule(mod).do(func, val)
        except Exception as e:  # pylint: disable=broad-except
            # catchall - keep running even if action fails
            self.log.exception('Exception during key handler: %s', e)
        # hide menu
        if self.state.rumbaActive:  # menu is always displayed during addon sessions (retropie etc)
            self.startMenuTimeout()

    def checkDoubleclick(self, action):
        """ Returns true if action can be executed """
        if self.state.requestRunning:
            return None  # dont start new action while another is still awaited

        if self.state.confirmTarget is not None and self.state.confirmTarget == action:
            self.changeConfirm()
            return True  # doubleclick successful

        mod, func = action.split('.')
        if self.getModule(mod).needsConfirm(func):  # register first click
            self.changeConfirm(action)  # display confirm dialog
            return False

        # action does not require doubleclick
        self.changeConfirm()
        return True

    def getModule(self, moduleName):
        """ Deferred module loader, supplies config and registers with pluginmanager """
        if moduleName not in self.modules:
            # init module
            try:
                module = importlib.import_module(f'addons.{moduleName.lower()}')

                cfg = None
                if moduleName.lower() in self.config['addons']:
                    cfg = self.config['addons'][moduleName.lower()]

                module = getattr(module, moduleName.capitalize())

                self.modules[moduleName] = module(cfg, self)
                self.log.debug('registering module %s!', moduleName)
                self.pm.register(self.modules[moduleName])

            except ModuleNotFoundError as me:
                # Most likely a config error
                self.log.error(me)
                self.log.error('Closing application, please fix your configuration!')
                self.onClose()
                raise SystemExit from me
        return self.modules[moduleName]

    def needsConfirm(self, func):
        """ Module Interface: Confirmation for RUMBA.* methods """
        return func in self.CONFIRM

    def getConfirmText(self, func):
        """ Module Interface: Confirmation text for RUMBA.* methods """
        if self.needsConfirm(func):
            return self.CONFIRM[func]
        return None  # no confirmation needed

    def getBackgroundImage(self):
        """ Module Interface: use song-cover as background image if available """
        if self.state.rumbaActive and self.state.jukebox.curSong is not None:
            return self.state.jukebox.curSong.get('coverScreenPath')
        return None  # use default image

    def toggleVideoOut(self, enableVideo=None):
        """" Calls the jukebox server to enable/disable video output """
        if enableVideo is None:
            # no new state supplied (pushbutton), switch current
            enableVideo = not bool(self.videoEnabled)

        self.videoEnabled = bool(enableVideo)
        self.log.debug('toggleVideoOut called: self.videoEnabled=%s', self.videoEnabled)

        asyncio.ensure_future(self.rumba('toggleVideoOut', enabled=int(enableVideo)))

    async def start(self):
        """ starting jukebox server """
        self.log.info('starting rum.ba jukebox')
        self.changeConfirm()

        await (
            await asyncio.create_subprocess_exec(
                'sudo', 'service', 'rumba-server', 'start',
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ).wait()

        # waiting for server to restore pls
        while not await self.rumba('getStatus', syncronized=False):
            await asyncio.sleep(0.5)
        await self.server.restoreState()
        self.changeServerRunning(True)
        self.updateMenuState()
        self.log.info('rum.ba jukebox started!')

    async def stop(self):
        """ suspending jukebox server """
        self.log.info('suspending rum.ba jukebox')

        self.changeServerRunning()

        # save pls and jukebox state
        if len(self.server.jukebox.curSongs) > 0:
            self.server.saveState()

        await (
            await asyncio.create_subprocess_exec(
                'sudo', 'service', 'rumba-server', 'stop',
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ).wait()
        self.log.info('rum.ba jukebox suspended!')

    def updateMenuState(self, newPage=None):
        """ Uses menupage, jukebox/modules state and song information
            to construct currently active menu items
        """
        if self.state.rumbaActive:
            # While this controller is active the menu will be constructed
            # from the menuRows in the users config file
            if newPage is None:
                self.state.menu = list(self.menuRows[0])
            else:
                self.state.menu = list(self.menuRows[newPage])

            for cnt, menuItem in enumerate(self.state.menu):
                mod, func = menuItem.split('.')
                if mod not in ('RUMBA', 'KEY'):
                    self.state.menu[cnt] = self.getModule(mod).getIcon(func)
                elif func == 'STAR' and self.state.jukebox.curSong and self.state.jukebox.curSong.get('starred', False):
                    self.state.menu[cnt] = 'RUMBA.UNSTAR'

            if self.state.menuPage != newPage:
                self.state.menuPage = newPage
        else:
            # If a module takes control the menu items are supplied from there
            self.state.menu = self.state.activeModule.getMenuItems()
            self.state.menuPage = 0
        self.changeConfirm()  # close confirm dlg if present
        self.onToggleMenu(newPage, self.state.menu, self.state)

    def changeRequestRunning(self, running=False):
        """ Changes connection status """
        self.state.requestRunning = running
        self.onRequestRunning(running, self.state)

    def changeServerRunning(self, running=False):
        """ Changes server state """
        self.changeConfirm()  # close confirm dlg if present
        self.onServerConnect(running, self.state)

    async def changeMode(self, newModule=None):
        """ Changes currently active module """
        if not self.state.requestRunning:
            self.changeRequestRunning(True)

            if self.state.activeModule is not None:
                await self.state.activeModule.stop()
            self.state.activeModule = self if newModule is None else newModule
            self.updateMenuState()
            await self.state.activeModule.start()
            self.updateMenuState()
            self.onModeChange(self.state.activeModule, self.state)

            self.changeRequestRunning()

    async def resetMode(self):
        """ Resets currently active module """
        if not self.state.requestRunning and self.state.activeModule is not None:
            self.changeRequestRunning(True)
            await self.state.activeModule.stop()
            await self.state.activeModule.start()
            self.changeRequestRunning()

    async def getConfirm(self, text, action):
        """ Function for addons to get direct confirmation for a boolean request """
        self.resetMenu()
        self.state.confirmState = False
        self.state.confirmText = text
        self.state.confirmTarget = action
        self.onToggleConfirm(action, self.state.confirmText, True, self.state)
        # TODO:
        # X move 'Press any key to confirm' to menu row (needs adjust in display)
        # X im display nach confirmState is not None schauen und wenn ja 'press any key to confirm' und rotes X auf toggle anzeigen
        # X move menuAlignLeft completely to display (here in updateMenuState & keyInput) and adapt cfg file (controller->display)
        # X add confirm state to touch input
        # X check all todos/change to xxx if necessary
        # X check func/timeouts/menu/usbcontrl
        # X comment new stuff (diese func, onInput handling und WifiD addon)
        # - lint
        # - checkin
        # - deploy capi

        self.confirmModal = asyncio.Event()
        try:
            await asyncio.wait_for(self.confirmModal.wait(), self.menuTimeout)
        except asyncio.TimeoutError:
            pass
        resp = self.state.confirmState
        self.state.confirmState = None
        self.confirmModal = None
        self.resetMenu()
        return resp

    def changeConfirm(self, action=None):
        """ Sets confirm dialog """
        if self.state.confirmTarget != action:
            self.state.confirmTarget = action
            if action is not None:
                mod, func = action.split('.')
                self.state.confirmText = self.getModule(mod).getConfirmText(func)
            else:
                self.state.confirmText = None
            self.onToggleConfirm(action, self.state.confirmText, False, self.state)

    def resetMenu(self):
        """ hides menu && resets confirm/'doublecklick' """
        self.log.debug('hiding menu')
        if self.state.confirmTarget is not None:
            self.changeConfirm()
        self.updateMenuState()

    def startMenuTimeout(self):
        """ start/reset timeout to hide menu """
        if self.menuTimer is not None:
            self.menuTimer.cancel()
        self.menuTimer = asyncio.get_event_loop().call_later(self.menuTimeout, self.resetMenu)
        self.log.debug('hide menu timer started')

    def setDisplayResolution(self, resolution):
        """ Sets album art resolution for img-fetches in server connector """
        self.server.displayRes = resolution
        self.log.debug('Resolution for album art changed (%s)', resolution)

    def serverCallback(self, changed):
        """ ui updates on jukebox state change """
        if changed in (jukebox.CHANGE.PLS, jukebox.CHANGE.TRACK):
            self.log.debug('server callback (change: %s)', changed)
            self.onTrackChange(self.state.jukebox.curPos, self.state.jukebox.curSong, self.state)

    ########################### Events/Plugins ##########################
    # all hooks for output-devices send full controller state
    # to enable simple stateless data rendering
    #
    # the relevant state changes for each event are also passed directly
    #
    # output plugins for minimal devices like status-leds will
    # only need a small selection of these hooks
    #####################################################################

    @hookspec
    def onUserInput(self, state):
        """ Triggers on every user input eg for controlling a screensaver """
        self.pm.hook.onUserInput(state=state)
        self.log.debug('hook triggered: onUserInput()')

    @hookspec
    def onToggleMenu(self, menuPage, menu, state):
        """ Triggers every time the menu page changes """
        self.pm.hook.onToggleMenu(menuPage=menuPage, menu=menu, state=state)
        self.log.debug('hook triggered: onToggleMenu(%s)', menuPage)

    @hookspec
    def onToggleVideo(self, videoOut, state):
        """ Triggers every time video output changes """
        self.pm.hook.onToggleVideo(videoOut=videoOut, state=state)
        self.log.debug('hook triggered: onToggleVideo(%s)', videoOut)

    @hookspec
    def onTrackChange(self, curPos, curSong, state):
        """ Triggers every time the played track changes """
        self.pm.hook.onTrackChange(curPos=curPos, curSong=curSong, state=state)
        self.log.debug('hook triggered: onTrackChange(%s)', curSong)

    @hookspec
    def onPosChange(self, curPos, curSong, state):
        """ Triggers every time the playback position changes (polled with 1 second interval) """
        self.pm.hook.onPosChange(curPos=curPos, curSong=curSong, state=state)
        self.log.debug('hook triggered: onPosChange(%s, %s)', curSong['duration'], curPos)

    @hookspec
    def onRequestRunning(self, started, state):
        """ Triggers every time a request to the server starts or stops """
        self.pm.hook.onRequestRunning(started=started, state=state)
        self.log.debug('hook triggered: onRequestRunning(%s)', started)

    @hookspec
    def onServerConnect(self, connected, state):
        """ Triggers every time the jukebox server is started or stopped """
        self.pm.hook.onServerConnect(connected=connected, state=state)
        self.log.debug('hook triggered: onServerConnect(%s)', connected)

    @hookspec
    def onModeChange(self, newModule, state):
        """ Triggers every time an addon takes or returns exclusive control """
        self.pm.hook.onModeChange(newModule=newModule, state=self.state)
        self.log.debug('hook triggered: onModeChange(%s)', newModule.name)

    @hookspec
    def onTogglePlaying(self, playing, state):
        """ Triggers every time playback changes (play/pause) """
        self.pm.hook.onTogglePlaying(playing=playing, state=state)
        self.log.debug('hook triggered: onTogglePlaying(%s)', playing)

    @hookspec
    def onToggleAlert(self, text, state):
        """ Triggers every time an alert needs to be shown or ends (eg server not found) """
        self.pm.hook.onToggleAlert(text=text, state=state)
        self.log.debug('hook triggered: onToggleAlert(%s)', text)

    @hookspec
    def onToggleConfirm(self, action, confirmText, confirmModal, state):
        """ Triggers every time a confirmation needs to be shown or ends ('doublecklick') """
        self.pm.hook.onToggleConfirm(action=action, confirmText=confirmText, confirmModal=confirmModal, state=state)
        self.log.debug('hook triggered: onToggleConfirm(%s)', action)

    @hookspec
    def onClose(self):
        """ Shutdown triggered, stop running tasks """
        self.log.debug('hook triggered: onClose()')
        self.statusTask.cancel()
        if self.menuTimer is not None:
            self.menuTimer.cancel()
        self.keyInjector.close()
        self.pm.hook.onClose()
        asyncio.get_event_loop().stop()
