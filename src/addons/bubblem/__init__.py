from addons.mame import Mame


# To quickly use multiple instances of mame game loaders
# copy this module to <home>/.local/share/rumba-remote/addons/
# change class-/directory-name, icons/background images or
# override some methods from the base classes and finally
# change the mame command in your config file
#
class Bubblem(Mame):
    """ Start bubblem arcade game with mame: BUBBLEM.ENABLE
        (see parent mame-module and section in cfg-file)
    """
    CONFIRM = {
        'ENABLE': 'Start Bubble Bobble3?'
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # if no cmd supplied: use mame default search paths for rom
        self.cmd = "exec mame bubblem -autoframeskip -video accel -prescale 1 -nowindow -nofilter"
        if self.config and self.config.get('cmd', False):
            self.cmd = self.config.get('cmd')
