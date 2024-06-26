"""bluesky.growers.persistence"""

__author__ = "Joel Dubowy"

__version__ = "0.1.0"

import copy
import datetime
import logging

from afdatetime.parsing import parse as parse_dt

from bluesky import datautils
from bluesky.exceptions import BlueSkyConfigurationError
from bluesky.config import Config
from . import GrowerBase, to_date


DAYS_TO_PERSIST_NOT_POS_INT = "'days_to_persist' must be a positive integer"
INVALID_CONFIG = "Invalid persistence configuration ('config' > 'growth' > 'persistence')"
CONFIG_NOT_SPECIFIED = "Persistence configuration ('config' > 'growth' > 'persistence') not specified"
EMPTY_CONFIG_LIST = "Don't specify empty list of persistence config sets"
INVALID_START_END_DAY = "Invalid start/end day string: '{day_str}'"
DAYS_TO_PERSIST_AND_PERCENTAGES_BOTH_SPECIFIED = "Specify 'days_to_persist' or 'daily_percentages', but not both"
INVALID_DAILY_PERCENTAGES = "'daily_percentages', should be an array of percentage values"

class Grower(GrowerBase):

    def __init__(self, fires_manager):
        super().__init__(fires_manager) # sets self._fires_manager

        self._set_config()

    ##
    ## Configuration related helpers
    ##

    def _set_config(self):

        p_config = self.config()
        if p_config is None:
            raise BlueSkyConfigurationError(CONFIG_NOT_SPECIFIED)

        if isinstance(p_config, dict):
            self._select_config([p_config])

        elif isinstance(p_config, list):
            self._select_config(p_config)

        else:
            raise BlueSkyConfigurationError(INVALID_CONFIG)

    def _select_config(self, configs):
        # TODO: self._days_to_persist is redundant now that we have
        #   self._daily_precentages, so we may eventually remove it

        if len(configs) == 0:
            raise BlueSkyConfigurationError(EMPTY_CONFIG_LIST)

        self._date_to_persist = None
        self._days_to_persist = 1
        self._daily_percentages = [100]
        self._truncate = False

        # Find first matching set of config params
        for c in configs:
            dtp = (to_date(c.get('date_to_persist'))
                or self._fires_manager.today.date())
            start_day = self._parse_start_end_day(c.get('start_day'), dtp)
            end_day = self._parse_start_end_day(c.get('end_day'), dtp)
            if ((not start_day or start_day <= dtp)
                    and (not end_day or dtp <= end_day)):

                self._date_to_persist = dtp

                if c.get('days_to_persist') is not None and c.get('daily_percentages') is not None:
                    raise BlueSkyConfigurationError(DAYS_TO_PERSIST_AND_PERCENTAGES_BOTH_SPECIFIED)

                if c.get('daily_percentages'):
                    if not isinstance(c['daily_percentages'], list):
                        raise BlueSkyConfigurationError(INVALID_DAILY_PERCENTAGES)

                    # TODO: make sure each value is numeric
                    self._daily_percentages = c['daily_percentages']
                    self._days_to_persist = len(c['daily_percentages'])

                else:
                    # cast to int in case it was specified as string in config file or on
                    # command line (really, no excuse for this, since you can use -I option)
                    self._days_to_persist = (1 if c.get('days_to_persist') is None
                        else int(c['days_to_persist']))
                    if self._days_to_persist <= 0:
                        raise BlueSkyConfigurationError(DAYS_TO_PERSIST_NOT_POS_INT)

                    self._daily_percentages = [100 for i in range(self._days_to_persist)]

                self._truncate = not not c.get('truncate')

                return

        # If we get this far, 'self._date_to_persist' will be None,
        # which means that 'grow', below, will abort


    SUPPORT_START_END_DAY_FORMATS = [
        '%m-%d', '%b %d', '%b-%d', '%B %d', '%B-%d', '%j'
    ]
    def _parse_start_end_day(self, day_str, date_to_persist):
        if day_str:
            # cast to string in case day was specified as integer day of year
            day_str = str(day_str)

            try:
                day = parse_dt(day_str,
                    extra_formats=self.SUPPORT_START_END_DAY_FORMATS)
                return day.replace(year=date_to_persist.year).date()

            except ValueError as e:
                raise BlueSkyConfigurationError(
                    INVALID_START_END_DAY.format(day_str=day_str))

    ##
    ## Public API
    ##

    def grow(self):
        if self._date_to_persist:
            for fire in self._fires_manager.fires:
                with self._fires_manager.fire_failure_handler(fire):
                    self._grow_fire(fire)
        else:
            logging.warning("Skipping persistence - date to persist outside"
                " of configured time windows")

    ##
    ## Helpers for grow
    ##

    def _grow_fire(self, fire):
        if not any([a.get('active_areas') for a in fire.get('activity', [])]):
            return

        # TODO: figure out how to actually specify the following
        if fire.is_rx:
            self._fill_in_rx(fire)
        elif fire.is_wildfire:
            self._fill_in_wf(fire)
        else:
            logging.debug(f'Not persisting type {fire.type}')

    def _fill_in_rx(self, fire):
        # do anything?
        pass

    def _fill_in_wf(self, fire):
        # activity will be in in chronological order, both the activity
        # collections as well as the active areas within each collection.
        # Active area windows will never span two days (since Spider
        # limits growth_window_length to some divisor of 24)

        # leave growth as is if case 1) (with or without truncation)
        # or if case 3) or 4) without truncation
        first_start = to_date(fire['activity'][0]['active_areas'][0]['start'])
        last_start = to_date(fire['activity'][-1]['active_areas'][-1]['start'])
        if (last_start < self._date_to_persist or
                (not self._truncate and last_start > self._date_to_persist)):
            return

        before_activity = []
        date_to_persist_activity = []
        for a in fire['activity']:
            a_start = to_date(a["active_areas"][0]['start'])
            if a_start < self._date_to_persist:
                before_activity.append(copy.deepcopy(a))
            elif a_start == self._date_to_persist:
                date_to_persist_activity.append(copy.deepcopy(a))
            else:
                # stop processing
                break

        fire['activity'] = (before_activity + date_to_persist_activity
            + self._persist(date_to_persist_activity))

    ONE_DAY = datetime.timedelta(days=1)

    def _persist(self, date_to_persist_activity):
        if not date_to_persist_activity:
            return []

        persisted_activity = []
        for i in range(self._days_to_persist):
            activity = copy.deepcopy(date_to_persist_activity)
            t_diff = (i + 1) * self.ONE_DAY
            for a in activity:
                a['persisted'] = True
                for aa in a['active_areas']:
                    aa['start'] = parse_dt(aa['start']) + t_diff
                    aa['end'] = parse_dt(aa['end']) + t_diff
                    self._add_time_diff_to_keys(aa, t_diff, ('timeprofile',))
                    for l in aa.locations:
                        self._add_time_diff_to_keys(l, t_diff, ('plumerise',))
                        self._add_time_diff_to_keys(l, t_diff, ('timeprofile',))
                        self._add_time_diff_to_keys(l, t_diff, ('hourly_frp',))

                if self._daily_percentages[i] < 100:
                    self._reduce_activity(a, self._daily_percentages[i])

                persisted_activity.append(a)

        return persisted_activity

    def _add_time_diff_to_keys(self, d, t_diff, fields):
        # instantiate list from timeprofile's and plumerise's keys
        # to avoid unexpected behavior when popping and replacing
        # keys within for loop
        for f in fields:
            for k in list(d.get(f, {})):
                new_k = (parse_dt(k) + t_diff)

                # if string, keep as string; if datetime.date object
                # (which includes datetime.datetime), keep as datetime.date
                if not isinstance(k, datetime.date):
                    new_k = new_k.strftime('%Y-%m-%dT%H:%M:%S')

                d[f][new_k] = d[f].pop(k)

    SCALAR_FIELDS_TO_REDUCE = ["area", "frp"]
    NESTED_FIELDS_TO_REDUCE = ["emissions", "consumption", "heat"]
    def _reduce_activity(self, a, percentage):
        fraction = percentage / 100

        def _reduce(v):
            for f in self.SCALAR_FIELDS_TO_REDUCE:
                if v.get(f):
                    v[f] = v[f] * fraction
            for f in self.NESTED_FIELDS_TO_REDUCE:
                if v.get(f):
                    datautils.multiply_nested_data(v[f], fraction)

        for aa in a.active_areas:
            _reduce(aa)
            for loc in aa.locations:
                _reduce(loc)
                for fb in loc.get('fuelbeds', []):
                    _reduce(fb)
