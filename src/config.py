import configparser
from collections import OrderedDict
import os
import sys
import shutil
import logging


class MultiOrderedDict(OrderedDict):
    """ Used for multi value options, eg:
        input = MENU.TOGGLE, KEY_ENTER
        input = MENU.1, KEY_LEFTCTRL
        input = MENU.2, KEY_SPACE
        ...
        defines multiple keys for input
        https://stackoverflow.com/questions/15848674/how-to-configparse-a-file-keeping-multiple-values-for-identical-keys
    """
    def __setitem__(self, key, value):
        if isinstance(value, list) and key in self:
            self[key].extend(value)
        else:
            super().__setitem__(key, value)


class ConfigError(Exception):
    """ Exception: Error in user supplied config file """


def readConfig(configFile=None):
    """ get config from file or create default config """
    config = configparser.RawConfigParser(dict_type=MultiOrderedDict, strict=False)

    appDir = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..')

    defaultFile = os.path.join(os.path.expanduser('~'), '.config', 'rumba-remote', 'rumba-remote.conf')

    if configFile is not None and os.path.isfile(configFile):
        config.read(configFile, encoding='utf-8')
        configDir = os.path.dirname(configFile)
    elif os.path.isfile(defaultFile):
        config.read(defaultFile, encoding='utf-8')
        configDir = os.path.dirname(defaultFile)
    else:
        from shutil import copyfile

        saveFile = defaultFile if configFile is None else configFile
        print(f'No config file found, creating {saveFile}', file=sys.stderr)
        os.makedirs(os.path.dirname(saveFile), exist_ok=True)
        copyfile(os.path.join(appDir, 'sys', 'rumba-remote.conf'), saveFile)
        config.read(saveFile, encoding='utf-8')
        configDir = os.path.dirname(saveFile)

    # init/clear cache dir
    cacheDir = os.path.join(os.path.expanduser('~'), '.cache', 'rumba-remote')
    try:
        shutil.rmtree(cacheDir)
    except FileNotFoundError:
        pass
    os.makedirs(cacheDir)

    # init logging (uses %s printf style logging for deferred format and log-aggregation)
    logLevel = getattr(logging, config.get('logging', 'logLevel', fallback='WARNING'))
    logging.basicConfig(filename=config.get('logging', 'logFile', fallback=os.path.join(configDir, 'status.log')),
                        level=logLevel,
                        format="%(asctime)s %(name)-8s %(levelname)-8s %(message)s",
                        datefmt='[%H:%M:%S]')

    # initialize config and local module path for devices and addons
    userModulePath = os.path.join(os.path.expanduser('~'), '.local', 'share', 'rumba-remote')
    for modDir in ['addons', 'devices']:
        os.makedirs(os.path.join(userModulePath, modDir), exist_ok=True)
    sys.path.append(userModulePath)

    iodevices, addons = _initPlugins(config)
    if not iodevices:
        cfgPath = defaultFile if configFile is None else configFile
        raise ConfigError(f'"io.devices" not found, please define input/output devices in your config file: {cfgPath}')

    initAddons = config.get('controller', 'initAddons', fallback=None)
    if initAddons:
        initAddons = [addon.strip() for addon in initAddons.split(',')]
    else:
        initAddons = []

    # init menu
    menuRows = config.get('controller', 'menuRow', fallback=None)
    if menuRows:
        menuRows = menuRows.split('\n')
        for idx, menuRow in enumerate(menuRows):
            menuRows[idx] = [menuItem.strip() for menuItem in menuRow.split(',')]
    else:
        # XXX: make useable without menu configured
        # for now: just quit!
        cfgPath = defaultFile if configFile is None else configFile
        raise ModuleNotFoundError(f'No menuRow defined\nin the [controller]-section of your config file:\n{cfgPath}')

    return {
        'io': {
            'devices': iodevices
        },
        'controller': {
            'appDir': appDir,
            'configDir': configDir,
            'menuRows': menuRows,
            'menuTimeout': config.getint('controller', 'menuTimeout', fallback=10),
            'enableVideo': config.getboolean('controller', 'enableVideo', fallback=None),
            'addons': addons,
            'initAddons': initAddons,
        },
        'jukebox': {
            'url': config.get('jukebox', 'url', fallback='http://127.0.0.1:23232/rest/'),
            'username': config.get('jukebox', 'username', fallback='admin'),
            'password': config.get('jukebox', 'password', fallback='admin'),
            'exclude': [int(id) for id in config.get('jukebox', 'excludeFolders', fallback='').split(',') if len(id)],
            'cacheDir': cacheDir,
            'logLevel': config.get('logging', 'logLevelServer', fallback=logLevel)
        },
    }


def _initPlugins(config):
    iodevices = []
    addons = {}
    # sort to get specific ones first (eg 'keyboard.Cherry' before generic 'keyboard')
    for sectionName in sorted(config.sections(), reverse=True):
        if sectionName.startswith('io.'):
            deviceName = sectionName.split('.', 1)[1].strip()
            device = config[f'io.{deviceName}']
            device['type'] = deviceName.split('.')[0]
            # get name for specific device if defined
            try:
                device['name'] = deviceName.split('.')[1]
            except IndexError:
                pass
            # add to list
            iodevices.append(device)
        elif sectionName.startswith('addons.'):
            addonName = sectionName.split('.', 1)[1].strip()
            # add to dict
            addons[addonName.lower()] = config[f'addons.{addonName}']
    return (iodevices, addons)
