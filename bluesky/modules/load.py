"""bluesky.modules.load

Example configuration:

    {
        "config":{
            "load": {
                "sources": [
                    {
                        "name": "firespider",
                        "format": "JSON",
                        "type": "API",
                        "endpoint": "https://haze.airfire.org/fire-spider/fires/goes16/archive/fire-spider-goes16-fires-{today:%Y-%m-%d}.json",
                        "saved_copy_file": "/path/to/log/dir/fire-spider-goes16-fires-{today:%Y-%m-%d}.json"
                    }
                ]
            }
        }
    }

or, on the command line:

    bsp --no-input -B skip_failed_fires=True -J load.sources='[{
        "name":"firespider",
        "format":"JSON",
        "type":"API",
        "endpoint": "https://haze.airfire.org/fire-spider/fires/goes16/archive/fire-spider-goes16-fires-{today:%Y-%m-%d}.json",
        "saved_copy_file": "/path/to/log/dir/fire-spider-goes16-fires-{today:%Y-%m-%d}.json"
    }]' load -o out.json

Currently supported sources:  FireSpider
Currently supported types: file, API
Currently supported formats: JSON, CSV
"""

import importlib
import logging

from bluesky import io
from bluesky import datautils
from bluesky.config import Config
from bluesky.exceptions import BlueSkyConfigurationError

__author__ = "Joel Dubowy"

__all__ = [
    'run'
]

__version__ = "0.1.0"

def run(fires_manager):
    """Loads fire data from one or more sources

    Args:
     - fires_manager -- bluesky.models.fires.FiresManager object
    """
    successfully_loaded_sources = []
    sources = Config().get('load', 'sources')
    if not sources:
        raise BlueSkyConfigurationError("No sources specified for load module")
    try:
        for source in sources:
            # TODO: use something like with fires_manager.fire_failure_handler(fire)
            #   to optionally skip invalid sources (sources that are insufficiently
            #   configured, don't have corresponding loader class, etc.) and source
            #   that fail to load
            try:
                loaded_fires = _load_source(source)
                fires_manager.add_fires(loaded_fires)
                # TODO: add fires to fires_manager
                if source.get("name").lower() == "bsf":
                    if source.get("load_consumption"):
                        datautils.summarize_all_levels(fires_manager, 'consumption')
                    if source.get("load_emissions"):
                        datautils.summarize_all_levels(fires_manager, 'emissions')
                successfully_loaded_sources.append(source)
            except:
                # Let skip_failed_sources be defined at top level
                # or under 'load' in the config
                if not (Config().get('skip_failed_sources')
                        or Config().get('load', 'skip_failed_sources', allow_missing=True)):
                    raise
    finally:
        fires_manager.processed(__name__, __version__,
            successfully_loaded_sources=successfully_loaded_sources)

def _load_source(source):
    # File loaders raise BlueSkyUnavailableResourceError in the
    # constructor, while API loaders raise it in 'load'.  So,
    # we need to decorate both the construction and load with
    # 'io.wait_for_availability'
    wait_dec = io.wait_for_availability(source.get('wait'))
    loader = wait_dec(_import_loader(source))(**source)
    return wait_dec(loader.load)()

def _import_loader(source):
    if any([not source.get(k) for k in ['name', 'format', 'type']]):
        raise BlueSkyConfigurationError(
            "Specify 'name', 'format', and 'type' for each source of fire data")

    try:
        loader_module = importlib.import_module(
            'bluesky.loaders.{}'.format(source['name'].lower()))
    except ImportError as e:
        raise BlueSkyConfigurationError(
            "Invalid source: {}".format(source['name']))

    loader = getattr(loader_module, '{}{}Loader'.format(
        source['format'].capitalize(), source['type'].capitalize()))
    if not loader:
        raise BlueSkyConfigurationError(
            "Invalid source format or type: {},{},{}".format(
            source['name'], source['format'], source['type']))

    return loader

