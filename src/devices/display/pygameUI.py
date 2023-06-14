import os
import datetime
import random
import logging
from html import unescape
import pygame
from . import pygameTxt
from . import pygameUtil
from .imageCache import ImageCache

# basic pygame color constants
BLACK = (0, 0, 0)
WHITE = (223, 223, 223)


class Display():
    """ The ui is build with pygame/sdl2 without using a gui-toolkit,
        because its intended to be quite basic - background, some text,
        a simple menu to display a few functions and a confirmation dialog
        - nothing that would justify the overhead of a gui-toolkit.

        The ui can be partially updated, because the app was originally
        meant to be used with an e-ink display - keeping this although
        it complicates the code a bit, in case some affordable AND
        good quality e-ink displays become available for tinkering.

        Its also possible to directly rotate the ui without relying upon
        hardware rotation from drm/kms or in software by a wayland compositor.
        This enables more flexibility eg for using mobile phone displays
        with fixed portrait orientation, but combined with the partial updates
        further complicates the code a little.

        Although pygame/sdl is used for drawing, its eventloop is not - instead
        of the usual update every x milliseconds, the display is only updated
        when changes occur (again, better for e-ink & reduced power consumption)
    """
    def __init__(self, config, appDir, slideShowImgs=None):
        self.log = logging.getLogger('sdl')
        if config.get('logLevel') is not None:  # can be different for ui code than general logLevel
            self.log.setLevel(config.get('logLevel'))
        self.log.debug('Display init SDL')
        self.displaySize = None
        self.screen = None
        self.imageCache = None
        # loader
        self.loadingImgs = []
        self.curlImg = 0
        # slideshow
        self.slides = []
        self.curSlide = None
        # display resolution / orientation
        self.rotate = config.getint('rotation', fallback='auto')
        if config.get('resolution', fallback=None) is not None:
            res = config.get('resolution').split('x')
            if len(res) == 2:
                self.displaySize = (res[0], res[1])
                self.log.info('Using screen resolution from config: %s', self.displaySize)
        self.toggleAlignLeft = config.getboolean('toggleAlignLeft', fallback=True)
        # init display & GUI
        if config.get('envSDL') is not None:
            os.environ["SDL_VIDEODRIVER"] = config.get('envSDL')
        self.initScreen(appDir, slideShowImgs)

    def initScreen(self, appDir, slideShowImgs=None):
        """ init app/display/images via pygame """
        try:
            pygame.display.init()
            pygame.display.set_caption('rumba-remote')
            pygame.font.init()
            pygame.mouse.set_visible(False)
        except pygame.error as pge:
            self.log.error('SDL init failed! %s', pge)
            raise

        if self.displaySize is None:
            self.displaySize = (pygame.display.Info().current_w, pygame.display.Info().current_h)
            self.log.info('Using detected screen size: %s', self.displaySize)

        if self.rotate == 'auto':
            # if vertical resolution > horizontal and rotation has not been explicitly configured
            # rotate screen by 270° (bc that fits my pinephone with keyboard - should use orientation from sensors..)
            if self.displaySize[0] < self.displaySize[1]:
                self.rotate = 3
            else:
                self.rotate = 0

        if self.rotate == 1 or self.rotate == 3:
            self.screen = pygame.display.set_mode(self.displaySize, pygame.FULLSCREEN)
            self.displaySize = (self.displaySize[1], self.displaySize[0])
        else:
            self.screen = pygame.display.set_mode(self.displaySize, pygame.FULLSCREEN)

        # init ImageCache now that the display resolution is known
        self.imageCache = ImageCache(appDir, self.displaySize, (self.pxW(12), self.pxH(14)))

        # init loader animation
        loaderImage = pygameUtil.aspectScale(pygame.image.load(
            os.path.join(appDir, 'res', 'loading.png')),
            (self.pxW(8), self.pxH(8)),
            background=False)
        for i in range(0, 60):
            self.loadingImgs.append(pygame.transform.rotate(loaderImage, i * 6))
        # init slideshow images
        if slideShowImgs is not None and len(slideShowImgs) > 0:
            random.shuffle(slideShowImgs)
            for path in slideShowImgs:
                self.slides.append({
                    'img': None,
                    'path': path.as_posix(),
                    'caption': path.stem
                })
        if len(self.slides) > 0:
            self.curSlide = -1
        else:
            self.update()
        self.log.debug('SDL UI init done!')

    def pxW(self, percent):
        """ returns the number of pixels for a percentage of the display width
            ..sloppy rounding with no need for neg percent..
        """
        return int((self.displaySize[0] / 100 * percent) + 0.5)

    def pxH(self, percent):
        """ returns the number of pixels for a percentage a the display height
            ..sloppy rounding with no need for neg percent..
        """
        return int((self.displaySize[1] / 100 * percent) + 0.5)

    def animateLoader(self):
        """ advances loader animation one frame and blits to screen surface """
        loaderImg = self.loadingImgs[self.curlImg].get_rect(center=(self.pxW(5), self.pxH(5)))
        if self.rotate:
            if self.rotate == 1:
                pos = loaderImg.bottomleft
                surf = self.screen.blit(
                    self.loadingImgs[self.curlImg],
                    (pos[0] - self.pxW(1), self.displaySize[0] - pos[1] - self.pxH(2))
                )
            elif self.rotate == 2:
                pos = loaderImg.bottomright
                surf = self.screen.blit(
                    self.loadingImgs[self.curlImg],
                    (self.displaySize[0] - pos[0] - self.pxW(1), self.displaySize[1] - pos[1] - self.pxH(2))
                )
            elif self.rotate == 3:
                pos = loaderImg.topright
                surf = self.screen.blit(
                    self.loadingImgs[self.curlImg],
                    (self.displaySize[1] - pos[0] + self.pxW(1), pos[1] + self.pxH(6))
                )
        else:
            pos = loaderImg.topleft
            surf = self.screen.blit(self.loadingImgs[self.curlImg], (pos[0] + self.pxW(1), pos[1] + self.pxH(2)))

        if self.curlImg < 59:
            self.curlImg += 1
        else:
            self.curlImg = 0
        pygame.display.update(surf)

    def updateMenu(self, menu, toggleAction, confirmModal):
        """ creates new menu pane and rotates/blits to screen surface """
        if menu is not None:
            self.log.debug('Update: menu changed')
            btnBG = self.drawMenu(menu, toggleAction, confirmModal)
            if self.rotate == 0:
                surf = self.screen.blit(btnBG, (0, self.displaySize[1] - self.pxH(20)))
            elif self.rotate == 1:
                surf = self.screen.blit(pygame.transform.rotate(btnBG, 90), (self.displaySize[1] - self.pxH(20), 0))
            elif self.rotate == 2:
                surf = self.screen.blit(pygame.transform.rotate(btnBG, 180), (0, 0))
            elif self.rotate == 3:
                surf = self.screen.blit(pygame.transform.rotate(btnBG, 270), (0, 0))
            pygame.display.update(surf)
            pygame.display.flip()  # needed to display immediately
        else:
            # unable to perform redraw without screensaver state
            # this should have been taken care of by the display handler
            self.log.error('ui.updateMenu() called without menu!')

    def drawMenu(self, menu, toggleAction, confirmModal=None, target=None):
        """ creates new menu pane """
        btnBG = pygameUtil.roundRect(
            (self.displaySize[0], self.pxH(20)),
            WHITE, rad=self.pxH(2),
            corners=["topleft", "topright"]
        )
        # works fine for menus with 3 to 8 menuitems on common sized displays
        # XXX: add a check and feedback when parsing config?
        iconWidth = 100 // (len(menu) + 1)
        if confirmModal is None:
            fullMenu = menu.copy()
            if self.toggleAlignLeft:
                fullMenu.insert(0, toggleAction)  # prepend toggle button
            else:
                fullMenu.append(toggleAction)
            for idx, action in enumerate(fullMenu):
                icon = self.imageCache.getIcon(action)
                btnBG.blit(icon, (self.pxW(3) + (idx * self.pxW(iconWidth)), self.pxH(3)))
        else:
            icon = self.imageCache.getIcon('MENU.CANCEL')
            btnBG.blit(icon, (self.pxW(3) if self.toggleAlignLeft else (4 * self.pxW(iconWidth)), self.pxH(3)))
            pygameTxt.drawbox(
                'Press any key to confirm',
                (self.pxW(iconWidth) if self.toggleAlignLeft else self.pxW(1), self.pxH(4),
                 (4 * self.pxW(iconWidth)), self.pxH(12)),
                sysfontname="DejaVuSans", surf=btnBG
            )
        if target is not None:
            target.blit(btnBG, (0, self.displaySize[1] - self.pxH(20)))
        return btnBG

    def update(self, state=None, bgImage=None, caption=None):
        """ perform full ui update """
        self.log.debug('Full ui update!')
        newScreen = pygame.Surface(self.displaySize)

        if state is None:
            newScreen.blit(self.imageCache.getBackground(), (0, 0))  # show default image
        else:
            # background image
            if bgImage is not None:
                # use image provided (screensaver call from display handler)
                newScreen.blit(bgImage, (0, 0))
            else:
                newScreen.blit(
                    self.imageCache.getBackground(
                        state.bgImage,  # gets path from active module
                        cached=(not state.rumbaActive)  # folder images are fetched with the right dim from jukebox
                    ), (0, 0)
                )
            # track
            song = None
            if state.jukebox.curSong is not None and bgImage is None and state.rumbaActive:
                song = state.jukebox.curSong
                self.drawTrack(song, target=newScreen)
            # clock
            self.drawClock(target=newScreen)
            # dialog
            if state.confirmTarget is not None or (state.alert != '' and state.rumbaActive):
                self.drawDialog(state, target=newScreen)
            # menu
            if state.menuPage is not None or state.confirmState is not None:
                self.drawMenu(state.menu, state.toggleAction, state.confirmState, target=newScreen)
            else:  # no menu - maybe slide-caption or position?
                if caption is not None and bgImage is not None:
                    self.drawCaption(caption, target=newScreen)
                elif song is not None and state.rumbaActive:
                    self.drawPos(state.jukebox.curPos, song['duration'], target=newScreen)

        if self.rotate:
            self.screen.blit(pygame.transform.rotate(newScreen, self.rotate * 90), (0, 0))
        else:
            self.screen.blit(newScreen, (0, 0))

        pygame.display.update()
        pygame.display.flip()  # needed to display immediately

    def drawDialog(self, state, target):
        """ creates modal dialog pane and blits to target """
        if state.alert != '':
            self.drawModal(state.alert, target, self.imageCache.getIcon('RUMBA.ALERT'))
        if state.confirmTarget is not None:
            action = state.confirmTarget
            self.drawModal(state.confirmText, target, self.imageCache.getIcon(action))

    def drawModal(self, text, target, icon=None):
        """ modal dialog pane with text & icon """
        if len(text) < 12:  # automatic resize to fit text better
            boxSize = (self.pxW(52), self.pxH(20))
            boxPos = (self.pxW(24), self.pxH(30))
        else:
            boxSize = (self.pxW(60), self.pxH(32))
            boxPos = (self.pxW(20), self.pxH(25))
        # dialog background
        target.blit(pygameUtil.roundRect(boxSize, WHITE, rad=self.pxH(2), border=1), boxPos)
        # text & icon
        pygameTxt.drawbox(
            text,
            ((boxPos[0] + self.pxW(2)),
             (boxPos[1] + self.pxH(1)),
             (boxSize[0] - self.pxW(20)),
             (boxSize[1] - self.pxH(3))),
            sysfontname="DejaVuSans", surf=target
        )
        if icon is not None:
            target.blit(
                icon,
                (int(boxPos[0] + boxSize[0] - icon.get_rect().size[0] - self.pxW(2)),
                 int(boxPos[1] + ((boxSize[1] - icon.get_rect().size[1]) / 2)))
            )

    def updateSlide(self, state):
        """ display slide, scale to screen dim """
        if len(self.slides) > 0:
            if self.slides[self.curSlide]['img'] is None:
                self.slides[self.curSlide]['img'] = pygameUtil.aspectScale(
                    pygame.image.load(self.slides[self.curSlide]['path']), self.displaySize
                )
            self.update(state,
                        bgImage=self.slides[self.curSlide]['img'],
                        caption=self.slides[self.curSlide]['caption'])

    def nextSlide(self, state):
        """ display next slide """
        if len(self.slides) > 0:  # set next slide
            self.curSlide += 1
            if self.curSlide == len(self.slides):
                self.curSlide = 0
        self.updateSlide(state)

    def drawTrack(self, song, target):
        """ display track information """
        artist = unescape(song.get('artist', ''))
        title = unescape(song.get('title', ''))
        album = unescape(song.get('album', ''))
        year = f"({song.get('year')})" if song.get('year', None) is not None else ""

        pygameTxt.drawbox(
            f"{artist}\n\n{title}\n\n{album}\n{year}",
            ((self.pxW(2), self.pxH(14)),
             (self.pxW(46), self.pxH(60))),
            sysfontname="DejaVuSans", align="left", surf=target
        )
        if song.get('starred', False):
            target.blit(self.imageCache.getIcon('RUMBA.STAR'), (self.pxW(15), self.pxH(0.4)))

    def drawClock(self, target):
        """ display clock """
        pygameTxt.draw(
            datetime.datetime.today().strftime('%H:%M'),
            (self.pxW(80), self.pxH(1)), surf=target,
            sysfontname="freesans", fontsize=self.pxH(10)
        )
        pygameTxt.draw(
            "★  rum.ba  ☯",
            (self.pxW(38), self.pxH(4)), surf=target,
            sysfontname="DejaVuSans", fontsize=self.pxH(4)
        )

    def updatePos(self, curPos=None, duration=None):
        """ creates timeslider and rotates/blits to screen surface """
        self.log.debug('updating position')
        posBG = self.drawPos(curPos, duration)
        if self.rotate == 0:
            surf = self.screen.blit(posBG, (self.pxW(1), self.pxH(90)))
        elif self.rotate == 1:
            surf = self.screen.blit(pygame.transform.rotate(posBG, 90), (self.pxH(90), self.pxW(1)))
        elif self.rotate == 2:
            surf = self.screen.blit(pygame.transform.rotate(posBG, 180), (self.pxW(1), self.pxH(1)))
        elif self.rotate == 3:
            surf = self.screen.blit(pygame.transform.rotate(posBG, 270), (self.pxW(1), self.pxH(1)))
        pygame.display.update(surf)

    def drawPos(self, curPos=None, duration=None, target=None):
        """ creates timeslider pane """
        # timeslider background
        posBG = pygameUtil.roundRect((self.pxW(98), self.pxH(9)), BLACK, rad=self.pxH(2))
        # timeslide
        posBG.blit(pygameUtil.roundRect(
            (self.pxW(68), self.pxH(1)),
            WHITE, rad=self.pxH(0.4)),
            (self.pxW(15), self.pxH(4))
        )
        if curPos is None or duration is None or duration == 0:
            curPos = '--:--'
            duration = '--:--'
        else:
            # timeslider handle
            pygame.draw.circle(posBG, WHITE,
                               (self.pxW(15 + (68 * min((curPos / duration), 1))), self.pxH(4.5)),
                               self.pxH(2))
            curPos = f'{curPos // 60 :02d}:{curPos % 60 :02d}'
            duration = f'{duration // 60 :02d}:{duration % 60 :02d}'
        # pos/dur text
        pygameTxt.draw(
            curPos,
            (self.pxW(4), self.pxH(2)), surf=posBG,
            sysfontname="freesans", fontsize=self.pxH(3.5), bold=True
        )
        pygameTxt.draw(
            duration,
            (self.pxW(88), self.pxH(2)), surf=posBG,
            sysfontname="freesans", fontsize=self.pxH(3.5), bold=True
        )
        if target is not None:
            target.blit(posBG, (self.pxW(1), self.pxH(90)))
        return posBG

    def drawCaption(self, caption, target):
        """ display caption/title of current screensaver slide """
        pygameTxt.draw(
            caption,
            (self.pxW(2), self.pxH(92)), surf=target,
            sysfontname="freesans", fontsize=self.pxH(5)
        )

    def getDisplayResolution(self):
        """ Return WxH-formatted string with current display resolution
            for getting cover images from the jukebox in the right dimensions
        """
        return f'{self.displaySize[0]}x{self.displaySize[1]}'
