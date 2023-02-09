import asyncio
import os
import subprocess
import pluggy
from addons.base import BaseAddon

hookimpl = pluggy.HookimplMarker("rumba-remote")

# untested atm because there is no bullseye/x64 version of retropie yet
# XXX: check after retropie 4.9 gets released!


class Retropie(BaseAddon):
    """ Provides buttons: 'RETROPIE.ENABLE' and 'RETROPIE.RESETEMU'
        to start emulationstation and reset the running emulator (or es)
        https://retropie.org.uk/

        The addon is modal - the jukebox gets suspended when starting Retropie
        and resumed again after exiting Retropie

        Retropie gets started with run-emulationstation.sh from the sys dir,
        multi_switch.sh takes care of resetting emulationstation/running emulator
    """

    CONFIRM = {
        'ENABLE': 'start emulationstation ?',
        'RESETEMU': 'reset emulator ?'
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.running = False
        sysDir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'sys')
        self.multiSwitch = os.path.join(sysDir, 'multi_switch.sh')
        self.cmd = f'sudo /bin/openvt {os.path.join(sysDir, "run-emulationstation.sh")}'
        # alt control emulationstation via service / systemd: 'sudo service emulation start'
        self.es = None  # emulationstation process

    async def do(self, func, val=None):
        """ Calls the addon functions """
        self.log.debug(f'Calling emulationstation: {func}')
        if func == 'ENABLE':
            await self.controller.changeMode(self)
        elif self.running and func == 'RESETEMU':
            await self.resetEmulator()
        else:
            self.log.warning(f'Method {func} not defined in RETROPIE!')

    def getIcon(self, func):
        """ selecting on/off-icon based on addon-state, use generic func for RESETEMU """
        if func == 'ENABLE':
            return 'RUMBA.ENABLE' if self.running else 'RETROPIE.ENABLE'
        return super().getIcon(func)

    def getMenuItems(self):
        """ use emulationstation hotkeys """
        return ['KEY.LEFTSHIFT+ESC.ESC', 'KEY.1', 'KEY.2', 'RETROPIE.RESETEMU']

    async def start(self):
        """ starts emulationstation """
        self.log.debug('starting emulationstation')
        self.es = subprocess.Popen(self.cmd, shell=True)
        await asyncio.sleep(5)  # approx emulationstation startup time on rpi4 (no feedback on startup available)
        self.running = True
        self.log.info('emulationstation started!')

    async def stop(self):
        """ stops emulationstation """
        self.log.debug('stopping emulationstation')
        if self.es:
            self.es.kill()
            await asyncio.sleep(1)
        self.running = False
        self.log.info('emulationstation stopped!')

    async def resetEmulator(self):
        """ resets running emulator if any, restarts emulationstation otherwise """
        if not self.controller.state.requestRunning:
            self.controller.changeRequestRunning(True)
            self.log.debug('reseting emulation')
            esPid = int(subprocess.check_output([f'{self.multiSwitch}', '--es-pid']))
            emuPid = int(subprocess.check_output([f'{self.multiSwitch}', '--rc-pid']))
            if emuPid:
                os.system(f"{self.multiSwitch} --closeemu")
                self.log.info('running emulator reset!')
            elif esPid:
                os.system(f"{self.multiSwitch} --es-restart")
                self.log.info('emulationstation reset!')
            self.controller.changeRequestRunning()

    @hookimpl
    def onClose(self):
        """ kill emulationstation process """
        if self.es:
            self.es.kill()
