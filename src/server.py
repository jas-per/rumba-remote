import asyncio
import logging
import os.path
from collections import namedtuple
from dataclasses import dataclass, field
from typing import Any, List
from multidict import MultiDict
import aiohttp

# feedback for ui-updates, immutable 'constants' via namedtuple
CHANGES = ['POS', 'TRACK', 'PLAY', 'PLS']
CHANGE = namedtuple('changeConstants', CHANGES)._make(range(len(CHANGES)))


@dataclass
class JukeboxState:
    """ synchronized local copy of the relevant jukebox server state """
    playing: bool = False
    curSongs: List[Any] = field(default_factory=list)  # PLS running on jukebox (..List[Song])
    curIndex: int = -1
    curSong: Any = None  # ..Optional[Song]
    curPos: int = 0
    lastModPLS: int = 0

    def reset(self):
        """ Set all values back to def eg on server disconnect
            (no new object because it is shared with the controller)
        """
        self.__dict__.update(
            {'playing': False, 'curSongs': [], 'curSong': None, 'curIndex': -1, 'curPos': 0, 'lastModPLS': 0})


class JukeboxError(Exception):
    """ Exception: Error message in jukebox response """


class NotFoundError(Exception):
    """ Exception: No connection to jukebox """


class Connector():
    """ Connection to jukebox server
        keeps a synchronized local copy of the relevant jukebox state,
        wraps all jukebox actions and passes back state-changes
        to the controller that trigger corresponding UI-updates
    """
    def __init__(self, config, callback):
        self.displayRes = None
        self.serverCallback = callback  # trigger controller async for ui-updates
        self.baseurl = config['url']
        self.localServer = ('localhost' in self.baseurl or '://127.' in self.baseurl or self.baseurl.startswith('127.'))
        self.cacheDir = config['cacheDir']
        self.username = config['username']
        self.password = config['password']
        self.excludeFolders = config['exclude']  # exclude parts of jukebox library (getRandomSongs)
        # cached jukebox state
        self.jukebox = JukeboxState()

        self.savedState = None  # restore jukebox state if server gets stopped (eg for a emulator session)
        self.http = None  # connection via aiohttp-session
        self.log = logging.getLogger('serv')
        self.log.setLevel(config['logLevel'])  # can be different than general logLevel

    def initSession(self):
        """ async init of http session """
        self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(20))

    def saveState(self):
        """ save current state before stopping jukebox service """
        self.savedState = {'songs': [int(song['id']) for song in self.jukebox.curSongs],
                           'index': self.jukebox.curIndex,
                           'pos': self.jukebox.curPos}
        self.log.debug('Jukebox state saved!')

    async def restoreState(self):
        """ restore jukebox state if server gets stopped (eg for a retropie session) """
        if self.savedState is not None and self.savedState['songs']:
            await self._setPLS(self.savedState['songs'], self.savedState['index'], self.savedState['pos'])
            self.serverCallback(CHANGE.PLS)
            self.log.debug('Jukebox state restored!')
        self.savedState = None

    async def call(self, action, **kwargs):
        """ wraps all jukebox actions to be able to determine state changes
            after the jukebox calls are done. the state-change gets passed back
            to the controller to trigger corresponding UI-updates """
        self.log.debug('Jukebox call %s(%s)', action, kwargs)
        change = None
        resp = await getattr(self, f'_{action}')(**kwargs)
        if resp is None:  # all actions return a response on success -> update status if action failed
            resp = await self._getStatus()
        if resp['subsonic-response'].get('jukeboxStatus', False):
            if self.jukebox.curPos != resp['subsonic-response']['jukeboxStatus']['position']:
                self.jukebox.curPos = resp['subsonic-response']['jukeboxStatus']['position']
                change = CHANGE.POS
            if self.jukebox.curIndex != resp['subsonic-response']['jukeboxStatus']['currentIndex']:
                self.jukebox.curIndex = resp['subsonic-response']['jukeboxStatus']['currentIndex']
                self.setCurSong()
                change = CHANGE.TRACK
            if self.jukebox.playing != resp['subsonic-response']['jukeboxStatus']['playing']:
                self.jukebox.playing = resp['subsonic-response']['jukeboxStatus']['playing']
                change = CHANGE.PLAY
            # jukebox signals playlist changes by updating lastMod timestamp
            # updates of the local playlist (self.jukebox.curSongs) are all triggered by this
            if resp['subsonic-response']['jukeboxStatus']['lastMod'] > self.jukebox.lastModPLS:
                resp = await self._fetch('jukeboxControl', {'action': 'get'})  # get new playlist data
                if resp['subsonic-response']['jukeboxPlaylist']['lastMod'] > self.jukebox.lastModPLS:
                    # use changes from getPlaylist() response to avoid getting out of sync
                    self.jukebox.lastModPLS = resp['subsonic-response']['jukeboxPlaylist']['lastMod']
                    self.jukebox.curIndex = resp['subsonic-response']['jukeboxPlaylist']['currentIndex']
                    self.jukebox.curPos = resp['subsonic-response']['jukeboxPlaylist']['position']
                    self.jukebox.playing = resp['subsonic-response']['jukeboxPlaylist']['playing']
                    self.jukebox.curSongs = resp['subsonic-response']['jukeboxPlaylist']['entry']
                    self.setCurSong()
                    change = CHANGE.PLS
        elif action == 'star':  # star returns empty 'subsonic-response' on success
            change = CHANGE.TRACK
        self.log.debug('Change result of jukebox action: %s', change)
        return change

    def setCurSong(self):
        """ sets currently playing track on track-change and
            starts async request of folder image if not present """
        curSong = None
        if len(self.jukebox.curSongs) > 0 and len(self.jukebox.curSongs) > self.jukebox.curIndex:
            if self.jukebox.curIndex > -1:
                curSong = self.jukebox.curSongs[self.jukebox.curIndex]
            else:
                curSong = self.jukebox.curSongs[0]
            if self.displayRes is not None:
                try:  # check if cover has already been requested
                    _ = curSong['coverScreenPath']
                except KeyError:
                    self.log.debug('Cover path not present - fetching (id: %s)', curSong['coverArt'])
                    asyncio.ensure_future(
                        self._getCover(curSong['coverArt'], self.jukebox.curIndex, self.jukebox.lastModPLS)
                    )
                    curSong['coverScreenPath'] = None
        self.jukebox.curSong = curSong
        # return curSong

    async def _getCover(self, covId, plsIndex, lastModRequest):
        """ fetches path to scaled cover art from jukebox (might take a while if it has to be created) """
        if self.localServer:
            resp = await self._fetch('getCoverScreen', {'id': covId, 'res': self.displayRes, 'returnPath': 'true'})
            imgPath = resp['subsonic-response']['imgPath']
        else:
            # remote server: cache img on device
            imgPath = f'{self.cacheDir}/{covId}-screen{self.displayRes}.jpg'
            if not os.path.isfile(imgPath):
                img = await self._fetch('getCoverScreen2', {'id': covId, 'res': self.displayRes, 'returnPath': 'false'})
                with open(imgPath, "wb") as f:
                    f.write(img)
                # XXX: do async?
                # async with aiofiles.open(imgPath, "wb") as f:
                #     await f.write(img)

        self.log.debug('Cover path fetched (path: %s)', imgPath)
        if self.jukebox.lastModPLS == lastModRequest:  # guard against possible PLS changes while waiting for response
            self.jukebox.curSongs[plsIndex]['coverScreenPath'] = imgPath
            self.serverCallback(CHANGE.TRACK)

    async def _setPLS(self, songIds, index=None, pos=None):
        """ set jukebox playlist, resume playback on track/position if supplied """
        reqParams = MultiDict(action='set')
        for songId in songIds:
            reqParams.add('id', songId)
        if index is None or pos is None:  # just set new pls (and probably keep playing)
            resp = await self._fetch('jukeboxControl', reqParams)
        else:  # set pls and resume on track/pos
            resp = await self._fetch('jukeboxControl', {'action': 'stop'})
            resp = await self._fetch('jukeboxControl', reqParams)
            resp = await self._fetch('jukeboxControl', {'action': 'skip', 'index': index, 'position': pos})
        self.log.debug('PLS changed, resume: %s', (index is not None and pos is not None))
        return resp

    async def _insertRandom(self):
        """ clear jukebox pls and insert 100 random tracks """
        reqParams = MultiDict(size=100)
        for folderID in self.excludeFolders:
            reqParams.add('excludeFolderIds', folderID)
        resp = await self._fetch('getRandomSongs', reqParams)
        # although resp contains all metadata just use IDs to set new PLS on jukebox (avoid inconsistency)
        newIDs = [song['id'] for song in resp['subsonic-response']['randomSongs']['song']]
        resp = await self._setPLS(newIDs)
        if resp['subsonic-response']['jukeboxStatus']['playing']:
            return resp
        return await self._fetch('jukeboxControl', {'action': 'skip', 'index': 0, 'position': 0})

    async def _insertSimilar(self):
        """ add full album around currently playing track or 20 random songs from the same artist """
        if self.jukebox.curIndex > -1 and len(self.jukebox.curSongs) > self.jukebox.curIndex:
            curIndex = self.jukebox.curIndex
            curSongIDs = [song.get('id') for song in self.jukebox.curSongs]
            # add album if not currently playing
            albumPlaying = False
            curAlbumID = self.jukebox.curSongs[curIndex].get('albumId', 0)
            if curAlbumID > 0:
                for index in [curIndex - 1, curIndex + 1]:
                    try:
                        if curAlbumID == self.jukebox.curSongs[index].get('albumId', 0):
                            albumPlaying = True
                            break
                    except IndexError:
                        pass
            # fetch new songs
            newSongIDs = []
            if curAlbumID > 0 and not albumPlaying:
                self.log.debug('Add similar: full album')
                resp = await self._fetch('getMusicDirectory', {'id': self.jukebox.curSongs[curIndex]['parent']})
                newSongIDs = [song['id'] for song in resp['subsonic-response']['directory']['child']]
                if newSongIDs:
                    curSongIDs[curIndex:curIndex + 1] = newSongIDs  # replace current track with album
            else:  # add more songs from artist if album already playing
                self.log.debug('Add similar: 20 random tracks')
                resp = await self._fetch(
                    'getSimilarSongs',
                    {'id': f'ar-{self.jukebox.curSongs[curIndex]["artistId"]}', 'count': 20}
                )
                newSongIDs = [song['id'] for song in resp['subsonic-response']['similarSongs']['song']]
                if newSongIDs:
                    curSongIDs[curIndex + 1:curIndex + 1] = newSongIDs  # insert after current track
            # set new playlist
            if newSongIDs:
                return await self._setPLS(curSongIDs)

    async def _prevSong(self):
        """ restart playback of current track or play previous track if already at the beginning """
        newIndex = self.jukebox.curIndex
        if self.jukebox.curPos < 10 and self.jukebox.curIndex > 0:
            newIndex -= 1
        if self.jukebox.playing:
            await self._fetch('jukeboxControl', {'action': 'skip', 'index': newIndex, 'offset': 0})
        else:
            await self._fetch('jukeboxControl', {'action': 'skip', 'index': newIndex, 'offset': 0})
            # a skip is always followed by a play in SubSonic
            # we don't want this here to be able to skip through a playlist without playback
            return await self._fetch('jukeboxControl', {'action': 'stop'})

    async def _startStop(self):
        """ start/stop toggle playback """
        return await self._fetch('jukeboxControl', {'action': ('stop' if self.jukebox.playing else 'start')})

    async def _nextSong(self):
        """ play next track or restart playback with first track at end of playlist """
        newIndex = 0
        if self.jukebox.curIndex + 1 < len(self.jukebox.curSongs):
            newIndex = self.jukebox.curIndex + 1
        if self.jukebox.playing:
            return await self._fetch('jukeboxControl', {'action': 'skip', 'index': newIndex, 'offset': 0})
        # skip through playlist without playback
        await self._fetch('jukeboxControl', {'action': 'skip', 'index': newIndex, 'offset': 0})
        return await self._fetch('jukeboxControl', {'action': 'stop'})

    async def _skip(self, index, offset):
        if len(self.jukebox.curSongs) > index:
            return await self._fetch('jukeboxControl', {'action': 'skip', 'index': index, 'offset': offset})

    async def _star(self, starred):
        """ star/unstar currently playing track """
        if self.jukebox.curIndex > -1 and len(self.jukebox.curSongs) > self.jukebox.curIndex:
            song = self.jukebox.curSongs[self.jukebox.curIndex]
            resp = await self._fetch('star' if starred else 'unstar', {'id': song['id']})
            song['starred'] = starred
            return resp

    async def _toggleSubs(self):
        """ select subtitle track of video """
        return await self._fetch('jukeboxControl', {'action': 'toggleSubs'})

    async def _toggleLang(self):
        """ select language/audio track of video """
        return await self._fetch('jukeboxControl', {'action': 'toggleLang'})

    async def _toggleVideoOut(self, enabled):
        """ on/off switch video out """
        return await self._fetch('jukeboxControl', {'action': 'toggleVideoOut', 'enabled': enabled})

    async def _getStatus(self):
        """ get current state from jukebox - does not include playlist/track metadata """
        return await self._fetch('jukeboxControl', {'action': 'status'})

    async def _fetch(self, endpoint, params):
        """ communication with jukebox server - errors in response will result in exceptions """
        params.update({'u': self.username, 'p': self.password, 'v': '1.9.23', 'c': 'rumba-remote', 'f': 'json'})
        try:
            url = f'{self.baseurl}{endpoint}.view'
            self.log.debug('GET %s / %s', url, params)
            async with self.http.get(url, params=params) as response:
                if response.headers['Content-Type'] == 'image/jpeg':
                    return await response.content.read()
                # XXX: non-json-resp (error-) handling
                resp = await response.json()
                self.log.debug('RESP: %s', resp)
                try:
                    status = resp['subsonic-response']['status']
                    if status != 'ok':  # standard error msg from server
                        raise JukeboxError(f"Jukebox Error: {resp['subsonic-response']['error']['message']}")
                except KeyError:
                    self.log.critical('Invalid response from server: %s', resp)
                    raise JukeboxError('Invalid response, could not parse!')
                return resp
        except asyncio.CancelledError:
            return  # task cancelled -> shutdown etc, just return
        except asyncio.exceptions.TimeoutError:
            raise NotFoundError(f'Server error please try again:\n{self.baseurl}')
        except aiohttp.client_exceptions.ClientConnectorError:
            raise NotFoundError(f'Server not found:\n{self.baseurl}')
