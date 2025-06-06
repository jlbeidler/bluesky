"""bluesky.modules.emissions"""

__author__ = "Joel Dubowy"

import abc
import copy
import itertools
import logging
import sys
import os
import pandas as pd

import consume
from emitcalc import __version__ as emitcalc_version
from emitcalc.calculator import EmissionsCalculator
from eflookup import __version__ as eflookup_version
from eflookup.fccs2ef.lookup import Fccs2Ef, Fccs2SeraEf
from eflookup.fepsef import FepsEFLookup
from eflookup.crops2ef import Crops2Ef
from pyairfire import osutils

from bluesky import datautils, datetimeutils
from bluesky.config import Config
from bluesky.exceptions import BlueSkyConfigurationError
from bluesky.io import capture_stdout
from bluesky.emitters.ubcbsffeps import UbcBsfFEPSEmissions

from bluesky.consumeutils import (
    FuelLoadingsManager, FuelConsumptionForEmissions,
    CONSUME_FIELDS, CONSUME_VERSION_STR
)

__all__ = [
    'run'
]
__version__ = "0.1.1"


def run(fires_manager):
    """Runs emissions module

    Args:
     - fires_manager -- bluesky.models.fires.FiresManager object

    Config options:
     - emissions > model -- emissions model to use
     - emissions > species -- inclusion list of species to compute emissions for
     - emissions > include_emissions_details -- whether or not to include
        emissions per fuel category per phase, as opposed to just per phase
     - emissions > fuel_loadings --
     - consumption > fuel_loadings -- considered if fuel loadings aren't
        specified in the emissions config
    """
    model = Config().get('emissions', 'model')

    include_emissions_details = Config().get(
        'emissions', 'include_emissions_details')
    fires_manager.processed(__name__, __version__, model=model,
        emitcalc_version=emitcalc_version, eflookup_version=eflookup_version,
        consume_version=CONSUME_VERSION_STR)

    try:
        klass_name = ''.join([e.capitalize() for e in model.split('-')])
        klass = getattr(sys.modules[__name__], klass_name)
        e = klass(fires_manager.fire_failure_handler)
    except AttributeError:
        msg = "Invalid emissions model: '{}'.".format(model)
        if model == 'urbanski':
            msg += " The urbanski model has be replaced by prichard-oneill"
        raise BlueSkyConfigurationError(msg)

    e.run(fires_manager.fires)

    # fix keys
    for fire in fires_manager.fires:
        with fires_manager.fire_failure_handler(fire):
            for aa in fire.active_areas:
                for loc in aa.locations:
                    for fb in loc['fuelbeds']:
                        _fix_keys(fb['emissions'])
                        if include_emissions_details:
                            _fix_keys(fb['emissions_details'])

    datautils.summarize_all_levels(fires_manager, 'emissions')
    if include_emissions_details:
        datautils.summarize_over_all_fires(fires_manager, 'emissions_details')

def _fix_keys(emissions):
    for k in list(emissions.keys()):
        # in case someone spcifies custom EF's with 'PM25'
        if k == 'PM25':
            emissions['PM2.5'] = emissions.pop('PM25')
        elif k == 'NMOC':
            # Total non-methane VOCs
            emissions['VOC'] = emissions.pop('NMOC')
        elif isinstance(emissions[k], dict):
            _fix_keys(emissions[k])


##
## Emissions base class
##

class EmissionsBase(object, metaclass=abc.ABCMeta):

    def __init__(self, fire_failure_handler):
        self.fire_failure_handler = fire_failure_handler
        self.include_emissions_details = Config().get(
            'emissions', 'include_emissions_details')
        self.include_emissions_factors = Config().get(
            'emissions', 'include_emissions_factors')
        self.species = Config().get('emissions', 'species')

    def run(self, fires):
        logging.info("Running emissions module %s EFs",
            self.__class__.__name__)

        for fire in fires:
            with self.fire_failure_handler(fire):
                self._run_on_fire(fire)


    @abc.abstractmethod
    def _run_on_fire(self, fire):
        pass

##
## Crops
##

class Crops(EmissionsBase):

    def __init__(self, fire_failure_handler):
        super(Crops, self).__init__(fire_failure_handler)

    CONVERSION_FACTOR = 0.0005 # 1.0 ton / 2000.0 lbs

    def _run_on_fire(self, fire):
        if 'activity' not in fire:
            raise ValueError(
                "Missing activity data required for computing emissions")

        for aa in fire.active_areas:
            for loc in aa.locations:
                if 'fuelbeds' not in loc:
                    raise ValueError(
                        "Missing fuelbed data required for computing emissions")
                for fb in loc['fuelbeds']:
                    if 'consumption' not in fb:
                        raise ValueError(
                            "Missing consumption data required for computing emissions")
                    if 'fccs_id' not in fb:
                        raise ValueError(
                            "Missing FCCS Id required for computing emissions")
                    lookup = self._get_lookup_object(fire, fb)
                    calculator = EmissionsCalculator(lookup, species=self.species)
                    _calculate(calculator, fb, self.include_emissions_details,
                        self.include_emissions_factors)
                    datautils.multiply_nested_data(fb['emissions'], self.CONVERSION_FACTOR)
                    if self.include_emissions_details:
                        datautils.multiply_nested_data(fb['emissions_details'], self.CONVERSION_FACTOR)

    def _get_lookup_object(self, fire, fuelbed):
        return Crops2Ef(fuelbed['fccs_id'])

##
## FEPS for Canadian Smartfire
##

class UbcBsfFeps(EmissionsBase):
    # TODO: Add "Included Emissions Details" functionality

    def __init__(self, fire_failure_handler):
        super(UbcBsfFeps, self).__init__(fire_failure_handler)
        model = Config().get('emissions', 'model').lower()
        config = Config().get('emissions', model)
        self.emitter = UbcBsfFEPSEmissions(**config)

    def _get_fire_working_dir(self, fire, working_dir):
        fire_working_dir = os.path.join(working_dir,
            "feps-emissions-{}".format(fire.id))
        if not os.path.exists(fire_working_dir):
            os.makedirs(fire_working_dir)
        return fire_working_dir

    #CONVERSION_FACTOR = 0.0005 # 1.0 ton / 2000.0 lbs

    def _run_on_fire(self, fire):
        working_dir = Config().get('emissions', 'ubc-bsf-feps', 'working_dir')
        delete_if_no_error = Config().get('emissions', 'ubc-bsf-feps',
            'delete_working_dir_if_no_error')
        with osutils.create_working_dir(working_dir=working_dir,
                delete_if_no_error=delete_if_no_error) as wdir:
            fire_working_dir = self._get_fire_working_dir(fire, wdir)
            if 'activity' not in fire:
                raise ValueError(
                    "Missing activity data required for computing Canadian emissions")
            for aa in fire.active_areas:
                for loc in aa.locations:
                    if "consumption" not in loc:
                        raise ValueError(
                            "Missing consumption data required for computing Canadian emissions")
                    if 'fuelbeds' not in loc:
                        raise ValueError(
                            "Fuelbeds should be made in bsf load module before computing Canadian emissions")
                    if len(loc["fuelbeds"]) != 1:
                        raise ValueError(
                            "Each fuelbed array should only have one entry when running Canadian emissions")
                    loc["fuelbeds"][0]["emissions"] = self.emitter.run(loc, fire_working_dir)


##
## FEPS
##

class Feps(EmissionsBase):

    def __init__(self, fire_failure_handler):
        super(Feps, self).__init__(fire_failure_handler)

        # The same lookup object is used for both Rx and WF
        self.calculator = EmissionsCalculator(FepsEFLookup(),
            species=self.species)

    CONVERSION_FACTOR = 0.0005 # 1.0 ton / 2000.0 lbs

    def _run_on_fire(self, fire):
        if 'activity' not in fire:
            raise ValueError(
                "Missing activity data required for computing emissions")

        for aa in fire.active_areas:
            for loc in aa.locations:
                if 'fuelbeds' not in loc:
                   raise ValueError(
                        "Missing fuelbed data required for computing emissions")
                for fb in loc['fuelbeds']:
                    if 'consumption' not in fb:
                        raise ValueError(
                            "Missing consumption data required for computing emissions")
                    _calculate(self.calculator, fb, self.include_emissions_details,
                        self.include_emissions_factors)
                    # TODO: Figure out if we should indeed convert from lbs to tons;
                    #   if so, uncomment the following
                    # Note: According to BSF, FEPS emissions are in lbs/ton consumed.  Since
                    # consumption is in tons, and since we want emissions in tons, we need
                    # to divide each value by 2000.0
                    # datautils.multiply_nested_data(fb['emissions'], self.CONVERSION_FACTOR)
                    # if self.include_emissions_details:
                    #     datautils.multiply_nested_data(fb['emissions_details'], self.CONVERSION_FACTOR)

##
## Prichard / O'Neill
##

class PrichardOneill(EmissionsBase):

    def __init__(self, fire_failure_handler):
        super(PrichardOneill, self).__init__(fire_failure_handler)

        all_fuel_loadings = (Config().get('emissions','fuel_loadings')
            or Config().get('consumption','fuel_loadings'))
        self.fuel_loadings_manager = FuelLoadingsManager(
            all_fuel_loadings=all_fuel_loadings)

    # Consumption values are in tons, Prichard/ONeill EFS are in g/kg, and
    # we want emissions values in tons.  Since 1 g/kg == 2 lbs/ton, we need
    # to multiple the emissions output by:
    #   (2 lbs/ton) * (1 ton / 2000lbs) = 1/1000 = 0.001
    CONVERSION_FACTOR = 0.001

    def _run_on_fire(self, fire):
        if 'activity' not in fire:
            raise ValueError(
                "Missing activity data required for computing emissions")

        for aa in fire.active_areas:
            for loc in aa.locations:
                if 'fuelbeds' not in loc:
                    raise ValueError(
                        "Missing fuelbed data required for computing emissions")
                for fb in loc['fuelbeds']:
                    if 'consumption' not in fb:
                        raise ValueError(
                            "Missing consumption data required for computing emissions")
                    if 'fccs_id' not in fb:
                        raise ValueError(
                            "Missing FCCS Id required for computing emissions")
                    lookup = self._get_lookup_object(fire, fb)

                    # use EmissionsCalculator (emitcalc) for non-pile emissions
                    # if a fb has piles, remove them, so EmissionsCalculator
                    #  doesn't calculate them.
                    if 'woody fuels' in fb["consumption"]:
                        if 'piles' in fb["consumption"]['woody fuels']:
                            pileFlamingTemp = fb['consumption']['woody fuels']['piles']['flaming'][0]
                            pileSmolderingTemp = fb['consumption']['woody fuels']['piles']['smoldering'][0]
                            pileResidualTemp = fb['consumption']['woody fuels']['piles']['residual'][0]
                            fb['consumption']['woody fuels']['piles']['flaming'][0] = 0
                            fb['consumption']['woody fuels']['piles']['smoldering'][0] = 0
                            fb['consumption']['woody fuels']['piles']['residual'][0] = 0


                    calculator = EmissionsCalculator(lookup, species=self.species)
                    _calculate(calculator, fb, self.include_emissions_details,
                        self.include_emissions_factors)
                    # Convert from lbs to tons
                    # TODO: Update EFs to be tons/ton in a) eflookup package,
                    #   b) just after instantiating look-up objects, above,
                    #   or c) just before calling EmissionsCalculator, above
                    datautils.multiply_nested_data(fb['emissions'], self.CONVERSION_FACTOR)
                    if self.include_emissions_details:
                        datautils.multiply_nested_data(fb['emissions_details'], self.CONVERSION_FACTOR)

                    # calculate pile emissions by using consume.Emissions class
                    if 'woody fuels' in fb["consumption"]:
                        if 'piles' in fb["consumption"]['woody fuels']:
                            fb['consumption']['woody fuels']['piles']['flaming'][0] = pileFlamingTemp
                            fb['consumption']['woody fuels']['piles']['smoldering'][0] = pileSmolderingTemp
                            fb['consumption']['woody fuels']['piles']['residual'][0] = pileResidualTemp

                            if fb['consumption']['woody fuels']['piles']['flaming'][0] > 0 or \
                                fb['consumption']['woody fuels']['piles']['smoldering'][0] > 0 or \
                                fb['consumption']['woody fuels']['piles']['residual'][0] > 0:
                                fire_type = fire.get("type")
                                burn_type = fire.get("fuel_type") or 'natural'
                                season = datetimeutils.season_from_date(aa.get('start'))

                                fuel_loadings_csv_filename = self.fuel_loadings_manager.generate_custom_csv(fb['fccs_id'])
                                area = (fb['pct'] / 100.0) * loc['area']

                                fc = FuelConsumptionForEmissions(fb["consumption"], fb['heat'],
                                area, burn_type, fire_type, fb['fccs_id'], season, loc,
                                fccs_file=fuel_loadings_csv_filename)

                                # custom fuel loadings for this fuelbed
                                config_fuel_loadings = Config().get('consumption','fuel_loadings')[fb['fccs_id']]
                                fb['emissions_fuel_loadings'] = config_fuel_loadings
                                e = consume.Emissions(fuel_consumption_object=fc)

                                pile_black_pct = (fc._settings.get('pile_black_pct') * 0.01)
                                config_fuel_loadings_df = pd.DataFrame([config_fuel_loadings])
                                pile_loadings = pd.Series([config_fuel_loadings['pile_clean_loading'] + config_fuel_loadings['pile_dirty_loading'] + config_fuel_loadings['pile_vdirty_loading']])
                                (pile_pm, pile_pm10, pile_pm25) = e._emissions_calc_pm_piles(config_fuel_loadings_df, pile_loadings, pile_black_pct)

                                (pile_co, pile_co2, pile_ch4, pile_nmhc, pile_nmoc, pile_nh3, pile_no, pile_no2, pile_nox, pile_so2) = \
                                    e._emissions_calc_pollutants_piles(pile_loadings, pile_black_pct)

                                # EF are lbs/ton consumed (example: pm2.5 is 13.5lbs/ton), so we need to divide by 2000.0 to get tons
                                # (lbs/acre)(tons/2000lbs)(acres) = tons
                                self.add_pile_emissions(fb, 'PM2.5', (pile_pm25/2000.0)*area)
                                self.add_pile_emissions(fb, 'PM10', (pile_pm10/2000.0)*area)
                                self.add_pile_emissions(fb, 'CO', (pile_co/2000.0)*area)
                                self.add_pile_emissions(fb, 'CO2', (pile_co2/2000.0)*area)
                                self.add_pile_emissions(fb, 'CH4', (pile_ch4/2000.0)*area)
                                self.add_pile_emissions(fb, 'NH3', (pile_nh3/2000.0)*area)
                                self.add_pile_emissions(fb, 'NOx', (pile_nox/2000.0)*area)
                                self.add_pile_emissions(fb, 'SO2', (pile_so2/2000.0)*area)


    def add_pile_emissions(self, fb, pollutant, pile_fsrt_emissions):
        fb['emissions']['flaming'][pollutant][0] += pile_fsrt_emissions[0][0]
        fb['emissions']['smoldering'][pollutant][0] += pile_fsrt_emissions[1][0]
        fb['emissions']['residual'][pollutant][0] += pile_fsrt_emissions[2][0]
        fb['emissions']['total'][pollutant][0] += pile_fsrt_emissions[3][0]
        if self.include_emissions_details:
            fb['emissions_details']['woody fuels']['piles']['flaming'][pollutant][0] += pile_fsrt_emissions[0][0]
            fb['emissions_details']['woody fuels']['piles']['smoldering'][pollutant][0] += pile_fsrt_emissions[1][0]
            fb['emissions_details']['woody fuels']['piles']['residual'][pollutant][0] += pile_fsrt_emissions[2][0]

            fb['emissions_details']['summary']['total']['flaming'][pollutant][0] += pile_fsrt_emissions[0][0]
            fb['emissions_details']['summary']['total']['smoldering'][pollutant][0] += pile_fsrt_emissions[1][0]
            fb['emissions_details']['summary']['total']['residual'][pollutant][0] += pile_fsrt_emissions[2][0]
            fb['emissions_details']['summary']['total']['total'][pollutant][0] += pile_fsrt_emissions[3][0]

            fb['emissions_details']['summary']['woody fuels']['flaming'][pollutant][0] += pile_fsrt_emissions[0][0]
            fb['emissions_details']['summary']['woody fuels']['smoldering'][pollutant][0] += pile_fsrt_emissions[1][0]
            fb['emissions_details']['summary']['woody fuels']['residual'][pollutant][0] += pile_fsrt_emissions[2][0]



    def _get_lookup_object(self, fire, fuelbed):
        return Fccs2SeraEf(fuelbed["fccs_id"], is_rx=(fire["type"]=="rx"))


##
## Urbanski
##

class Urbanski(PrichardOneill):

    def _get_lookup_object(self, fire, fuelbed):
        return Fccs2Ef(fuelbed["fccs_id"], is_rx=(fire["type"]=="rx"))


##
## CONSUME
##

class Consume(EmissionsBase):

    def __init__(self, fire_failure_handler):
        super(Consume, self).__init__(fire_failure_handler)

        self.species = self.species and [e.upper() for e in self.species]

        all_fuel_loadings = (Config().get('emissions','fuel_loadings')
            or Config().get('consumption','fuel_loadings'))
        self.fuel_loadings_manager = FuelLoadingsManager(
            all_fuel_loadings=all_fuel_loadings)

    def _run_on_fire(self, fire):
        logging.debug("Consume emissions - fire {}".format(fire.get("id")))

        if 'activity' not in fire:
            raise ValueError(
                "Missing activity data required for computing consume emissions")

        fire_type = fire.get("type")
        burn_type = fire.get("fuel_type") or 'natural'
        # TODO: set burn type to 'activity' if fire["fuel_type"] == 'piles' ?
        if burn_type == 'piles':
            raise ValueError("Consume can't be used for fuel type 'piles'")

        for aa in fire.active_areas:
            season = datetimeutils.season_from_date(aa.get('start'))
            for loc in aa.locations:
                if 'fuelbeds' not in loc:
                    raise ValueError(
                        "Missing fuelbed data required for computing emissions")

                for fb in loc['fuelbeds']:
                    self._run_on_fuelbed(loc, fb, season, burn_type, fire_type)

    def _run_on_fuelbed(self, loc, fb, season, burn_type, fire_type):
        if 'consumption' not in fb:
            raise ValueError(
                "Missing consumption data required for computing emissions")
        if 'heat' not in fb:
            raise ValueError(
                "Missing heat data required for computing emissions")
        if 'pct' not in fb:
            raise ValueError(
                "Missing fuelbed 'ptc' required for computing emissions")
        if 'ecoregion' not in loc:
            raise ValueError(
                "Missing ecoregion required for computing emissions")

        fuel_loadings_csv_filename = self.fuel_loadings_manager.generate_custom_csv(
             fb['fccs_id'])
        # unlike with consume consumption results, emissions results reflect
        # how you set area and output_units
        area = (fb['pct'] / 100.0) * loc['area']
        fc = FuelConsumptionForEmissions(fb["consumption"], fb['heat'],
            area, burn_type, fire_type, fb['fccs_id'], season, loc,
            fccs_file=fuel_loadings_csv_filename)

        e_fuel_loadings = self.fuel_loadings_manager.get_fuel_loadings(
            fb['fccs_id'], fc.FCCS)
        fb['emissions_fuel_loadings'] = e_fuel_loadings
        e = consume.Emissions(fuel_consumption_object=fc)
        e.output_units = 'tons'

        # Consume emissions prints out lines like
        #    Converting units: tons_ac -> tons
        # which we want to capture and ignore
        # TODO: should we log??
        with capture_stdout() as stdout_buffer:
            r = e.results()['emissions']

        fb['emissions'] = {f: {} for f in CONSUME_FIELDS}
        # r's key hierarchy is species > phase; we want phase > species
        for k in r:
            upper_k = 'PM2.5' if k == 'pm25' else k.upper()
            if k != 'stratum' and (not self.species or upper_k in self.species):
                for p in r[k]:
                    fb['emissions'][p][upper_k] = r[k][p]

        if self.include_emissions_details:
            # Note: consume gives details per fuel category, not per
            #  subcategory; to match what FEPS and Prichard/O'Neill calculators
            #  produce, put all per-category details under'summary'
            # The details are under key 'stratum'. the key hierarchy is:
            #    'stratum' > species > fuel category > phase
            #   we want phase > species:
            #     'summary' > fuel category > phase > species
            fb['emissions_details'] = { "summary": {} }
            for k in r.get('stratum', {}):
                upper_k = 'PM2.5' if k == 'pm25' else k.upper()
                if not self.species or upper_k in self.species:
                    for c in r['stratum'][k]:
                        fb['emissions_details']['summary'][c] = fb['emissions_details']['summary'].get(c, {})
                        for p in r['stratum'][k][c]:
                            fb['emissions_details']['summary'][c][p] = fb['emissions_details']['summary'][c].get(p, {})
                            fb['emissions_details']['summary'][c][p][upper_k] = r['stratum'][k][c][p]

        # Note: We don't need to call
        #   datautils.multiply_nested_data(fb["emissions"], area)
        # because the consumption and heat data set in fc were assumed to
        # have been multiplied by area.

        # TODO: act on 'self.include_emissions_details'?  consume emissions
        #   doesn't provide as detailed emissions as FEPS and Prichard/O'Neill;
        #   it lists per-category emissions, not per-sub-category


##
## Helpers
##

def _calculate(calculator, fb, include_emissions_details,
        include_emissions_factors):
    emissions_details = calculator.calculate(fb["consumption"])
    fb['emissions'] = copy.deepcopy(emissions_details['summary']['total'])
    if include_emissions_details:
        fb['emissions_details'] = emissions_details
    if include_emissions_factors:
        fb['emissions_factors'] = calculator.emissions_factors

