from addons.c64 import C64


# To quickly use multiple instances of c64 game loaders
# copy this module to <home>/.local/share/rumba-remote/addons/
# change class-/directory-name, icons/background images
# and finally the x64 command in your config
#
class Bublbobl(C64):
    """ Start bubblebobble game with vice c64 emulator: BUBLBOBL.ENABLE
        (see parent c64-module and section in cfg-file)
    """
    CONFIRM = {
        'ENABLE': 'Start Bubble Bobble?'
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # cmd HAS to be supplied: x64 needs absolute path to rom/snapshot
        if not self.config or not self.config.get('cmd', False):
            raise ModuleNotFoundError('Config for addon "bublbobl" missing or incomplete')
        self.cmd = self.config.get('cmd').split(' ')

    def getMenuItems(self):
        """ Keys 1 and 2 are needed to select a 1 or 2 player game at the start
            so these replace the normal quicksave/-load buttons of the c64 addon
        """
        return ['KEY.LEFTALT+P.P', 'KEY.1', 'KEY.2', 'C64.RESETEMU']
