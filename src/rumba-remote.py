#!/usr/bin/python3
# pylint: disable=invalid-name
import asyncio
import logging
import signal
import argparse
import sys
import pluggy
import config
import controller


async def wait4close():
    """ clean shutdown, waits for closing tasks """
    await asyncio.gather(*asyncio.all_tasks() - {asyncio.current_task()})


if __name__ == "__main__":
    # get settings
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--configFile", help="Path to the config file")
    args = parser.parse_args()

    # config currently only features things I needed so far to configure my own collection of devices,
    # but should be extensible enough to expand to other usecases - PRs welcome!
    try:
        conf = config.readConfig(args.configFile)
    except config.ConfigError as ce:
        sys.exit(ce)

    # setup loop & controller
    loop = asyncio.get_event_loop()
    pm = pluggy.PluginManager("rumba-remote")
    pm.add_hookspecs(controller.InputHandler)
    inputHandler = controller.InputHandler(conf, pm)

    # term handler
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, inputHandler.onClose)

    # register device handler
    import importlib
    log = logging.getLogger('startup')
    for device in conf['io']['devices']:
        log.debug('Initializing %s', device['type'])
        if device['type'] in ['display', 'keyboard', 'gpio', 'touch', 'signal']:
            try:
                dev = importlib.import_module(f"devices.{device['type']}")
                pm.register(dev.Handler(device, inputHandler, loop))
            except config.ConfigError as ce:
                log.warning(ce)
            except ModuleNotFoundError as me:
                log.error(me)
                log.error("Please review your config")
                sys.exit(f"Please review your config\n{me}")
        else:
            log.warning('unknown device type: %s', device['type'])

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:  # also called when loop stops on SIGTERM
        # give canceled tasks the last chance to run
        loop.run_until_complete(wait4close())
        loop.close()
