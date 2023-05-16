import os
import pygame
from . import pygameTxt


class ImageCache():
    """ Images for menu, icons and static backgrounds
        are needed quite often and have to be scaled
        in relation to the display size - the ImageCache
        loads/edits these on demand and keeps them cached
        in the right size for display compositions
    """
    def __init__(self, appDir, displaySize, iconSize):
        self.appDir = appDir
        self.localDir = os.path.join(os.path.expanduser('~'), '.local', 'share', 'rumba-remote', 'addons')
        self.displaySize = displaySize
        self.iconSize = iconSize
        self.cachedIcons = {}
        self.cachedImages = {}

    def getIcon(self, iconType):
        """ Tries loading icon images from app/addon resource paths
            or creates icon for key-shortcuts by using the letter
            and a keycap background. If no image can be found the icon
            will be created with just the shortened module/function name
        """
        if iconType not in self.cachedIcons:
            mod, func = iconType.split('.', 1)
            try:
                if mod in ('RUMBA', 'MENU'):
                    img = pygame.image.load(os.path.join(self.appDir, 'res', 'icons', f'{func}.png'))
                elif mod == 'KEY':  # backdrop keyboard cap
                    img = pygame.image.load(os.path.join(self.appDir, 'res', 'icons', 'KEY.png'))
                else:
                    # check addons installed in .local first
                    if os.path.isfile(os.path.join(self.localDir, mod.lower(), 'res', f'{func}.png')):
                        img = pygame.image.load(os.path.join(
                            self.localDir, mod.lower(), 'res', f'{func}.png'))
                    else:
                        img = pygame.image.load(os.path.join(
                            self.appDir, 'src', 'addons', mod.lower(), 'res', f'{func}.png'))
                self.cachedIcons[iconType] = pygame.transform.scale(img, self.iconSize)

                # add text with key name
                if mod == 'KEY':
                    # use abbreviation if supplied eg KEY.LEFTCTRL+C.CPY
                    if len(func.split('.')) > 1:
                        _, func = func.split('.', 1)
                    # shorten key name if it is too long to proper fit inside the icon
                    if len(func) > 3:
                        func = f'{func[0:3]}'
                    pygameTxt.drawbox(
                        f'{func}',
                        ((int(self.iconSize[1] * 0.52), int(self.iconSize[1] * 0.1)),
                         (self.iconSize[0] * 0.3, int(self.iconSize[1] * 0.75))),
                        surf=self.cachedIcons[iconType],
                        sysfontname="DejaVuSans"
                    )
            except FileNotFoundError:
                # fallback if no icon is found:
                # draw function name as plain text
                img = pygame.Surface(self.iconSize).convert_alpha()
                img.fill((0, 0, 0, 0))
                # shorten function name and add module name
                # if it is too long to proper fit the icon size
                if len(func) > 7:
                    func = f'{mod[0:7]}\n{func[0:5]}..'
                pygameTxt.drawbox(
                    f'{func}',
                    ((0, 0), self.iconSize), surf=img,
                    sysfontname="DejaVuSans"
                )
                self.cachedIcons[iconType] = img

        return self.cachedIcons[iconType]

    def getBackground(self, path=None, cached=False):
        """ Caching makes sense only for a few static background images
            anything dynamic (like album covers) should get loaded every time
            - not so much a problem since the album covers get created with
            the right size for the display and are cached by the jukebox itself.

            Make sure to use with cached=True only for a few images!
            (or implement proper cleanup for this cache ;)
        """
        if path is None:
            path = os.path.join(self.appDir, 'res', 'default.jpg')
            cached = True

        if cached:
            # in memory cache only for few images that are often needed, like the background images
            if path not in self.cachedImages:
                self.cachedImages[path] = pygame.transform.scale(pygame.image.load(path), self.displaySize)
            return self.cachedImages[path]

        # dont cache fetched cover images etc in memory, these get cached on disk
        return pygame.image.load(path)
