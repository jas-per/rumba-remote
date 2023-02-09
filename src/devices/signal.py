import asyncio
import signal
import os
import logging


class Handler():
    """
        This is an example of a very basic stateless device plugin utilizing simple linux signals
        use eg "kill -s SIGUSR1 $PID_RUMBA_REMOTE" to trigger a signal handler configured here
        see sys/kanshi* as an example to detect displays connected and toggle video-out of the rumba jukebox

        -> use for quick&easy messages from inputs that don't need full ipc
    """
    def __init__(self, config, controller, loop):

        self.log = logging.getLogger('signal')
        self.log.debug('signal init started')

        self.ctrl = controller
        self.signalType = config.get('signalType', fallback='SIGUSR1')

        self.action = config.get('ctrlAction', fallback=None)
        if not self.action:
            self.log.error("set signal handler %s failed, missing 'ctrlAction' in config", self.signalType)
            return

        self.argsFile = config.get('argsFile', fallback=None)

        loop.add_signal_handler(getattr(signal, self.signalType), self.callAsync)
        self.log.debug('set signal handler for %s: %s(%s)', self.signalType, self.action, self.argsFile)

    def callAsync(self):
        """ reads file to use as arguments if configured and call input function on controller """
        args = None
        self.log.debug('got signal %s', self.signalType)
        if self.argsFile and os.path.isfile(self.argsFile):
            with open(self.argsFile, 'r') as file:
                import json
                try:
                    args = json.load(file)
                except (IOError, ValueError) as reason:
                    self.log.warning('Parsing %s failed: %s', self.argsFile, reason)
        self.log.debug('calling %s(%s)', self.action, args)
        asyncio.ensure_future(self.ctrl.onInput(self.action, args))
