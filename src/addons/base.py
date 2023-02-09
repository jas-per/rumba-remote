import logging
import sys
import os


class BaseAddon():
    """ Base Class for all addons:
        Provides default methods to get confirm messages,
        icons and function calls
    """
    CONFIRM = {}

    def __init__(self, config, controller):
        """ addon-config a reference to the controller
            and initialized logging for all addons
        """
        self.config = config
        self.controller = controller
        self.name = type(self).__name__
        self.log = logging.getLogger(f'{self.name}')
        self.log.debug('init addon')

    def do(self, func, val=None):
        """ Calls the addon functions
            Override to react to addon-state if needed
        """
        func = getattr(self, func.lower())
        return func(val) if val else func()

    def needsConfirm(self, func):
        """ The easy way to configure if confimation is needed
            is to override CONFIRM in the addon (see eg "system"-addon)
            Manual config is possible by overriding this function
        """
        return func in self.CONFIRM

    def getConfirmText(self, func):
        """ The easy way to configure the confimation text
            is to override CONFIRM in the addon (see eg "system"-addon)
            Manual config is possible by overriding this function
        """
        if self.needsConfirm(func):
            if func in self.CONFIRM:
                return self.CONFIRM[func]
            return f'Confirm {self.name}: {func} ?'
        return None  # no confirmation needed

    def getIcon(self, func):
        """ This enables selecting icons based on addon-state if needed
        """
        return f'{self.name.upper()}.{func}'

    def getBackgroundImage(self):
        """ Override to enable modal addons with a differently named
            background image or a background that changes with
            the addons internal state
            If None gets returned the default image will be shown
        """
        return os.path.join(
            os.path.dirname(os.path.realpath(sys.modules[self.__module__].__file__)),
            'res',
            'background.jpg')

    def getMenuItems(self):
        """ Just returns func to stop module
            Needs override for modal addons
        """
        return ['RUMBA.ENABLE']
