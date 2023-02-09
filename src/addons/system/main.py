import asyncio
import subprocess
from addons.base import BaseAddon


class System(BaseAddon):
    """ Provides buttons: 'SYSTEM.RESTART' and 'SYSTEM.SHUTDOWN'
        to restart the jukebox or shutdown the system
    """

    CONFIRM = {
        'RESTART': 'restart jukebox ?',
        'SHUTDOWN': 'shutdown server ?'
    }

    def needsConfirm(self, func):
        """ all sys methods need confirmation """
        return True

    async def shutdown(self):
        """ shuts down computer """
        self.log.info('shutdown initiated!')
        self.controller.changeConfirm('RUMBA.OK')
        subprocess.call(['sudo', 'shutdown', '-h', 'now'], shell=False)

    async def restart(self):
        """ restarts jukebox service """
        self.log.info('restart rumba initiated!')
        self.controller.changeConfirm('RUMBA.OK')
        await (await asyncio.create_subprocess_exec(
            'sudo', 'service', 'rumba-server', 'restart',
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ).wait()
