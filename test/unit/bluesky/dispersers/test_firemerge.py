import copy
import datetime
import uuid

import pytest

from bluesky.dispersers import firemerge
from bluesky.exceptions import BlueSkyConfigurationError
from bluesky.models.fires import Fire


##
## PlumeMerge tests
##

CONSUMPTION = {
    "summary": {
        "flaming": 1311.2071801109494,
        "residual": 1449.3962581338644,
        "smoldering": 1267.0712004277434,
        "total": 4027.6746386725567
    }
}
PLUMERISE_HOUR = {
    "emission_fractions": [
        0.01,0.05,0.05,0.05,0.05,0.05,
        0.09,0.09,0.09,0.05,0.05,0.05,
        0.05,0.05,0.05,0.05,0.05,0.05,
        0.01,0.01
    ],
    "heights": [
        141.438826,200.84066925000002,260.2425125,
        319.64435575,379.046199,438.44804225,
        497.84988549999997,557.25172875,616.6535719999999,
        676.0554152499999,735.4572585000001,794.85910175,
        854.260945,913.66278825,973.0646314999999,
        1032.46647475,1091.868318,1151.27016125,
        1210.6720045,1270.0738477500001,1329.475691
    ],
    "smolder_fraction": 0.05
}
EMPTY_PLUMERISE_HOUR = {
    "emission_fractions": [
        0.05,0.05,0.05,0.05,0.05,0.05,
        0.05,0.05,0.05,0.05,0.05,0.05,
        0.05,0.05,0.05,0.05,0.05,0.05,
        0.05,0.05
    ],
    "heights": [
        0.0,0.0,0.0,0.0,0.0,0.0,
        0.0,0.0,0.0,0.0,0.0,0.0,
        0.0,0.0,0.0,0.0,0.0,0.0,
        0.0,0.0,0.0
    ],
    "smolder_fraction": 0.0
}

class TestFireMerger():

    FIRE_1 = Fire({
        "id": "SF11C14225236095807750-0",
        "original_fire_ids": {"SF11C14225236095807750"},
        "meta": {'foo': 'bar'},
        "start": datetime.datetime(2015,8,4,17,0,0),
        "end": datetime.datetime(2015,8,4,19,0,0),
        "area": 120.0, "latitude": 47.41, "longitude": -121.41, "utc_offset": -7.0,
        "plumerise": {
            "2015-08-04T17:00:00": PLUMERISE_HOUR,
            "2015-08-04T18:00:00": EMPTY_PLUMERISE_HOUR
        },
        "timeprofiled_area": {
            "2015-08-04T17:00:00": 12.0,
            "2015-08-04T18:00:00": 0.0
        },
        "timeprofiled_emissions": {
            "2015-08-04T17:00:00": {"CO": 0.0, "PM2.5": 4.0},  # == 5.0 * 0.2 + 10.0 * 0.1 + 20.0 * 0.1
            "2015-08-04T18:00:00": {"CO": 0.0, 'PM2.5': 0.0}
        },
        "consumption": CONSUMPTION['summary'],
        "heat": 1000000.0
    })

    # no conflicting meta, same location, but overlapping time window
    FIRE_OVERLAPPING_TIME_WINDOWS = Fire({
        "id": "SF11C14225236095807750-0",
        "original_fire_ids": {"SF11C14225236095807750"},
        "meta": {'foo': 'bar'},
        "start": datetime.datetime(2015,8,4,18,0,0),
        "end": datetime.datetime(2015,8,4,20,0,0),
        "area": 120.0, "latitude": 47.41, "longitude": -121.41, "utc_offset": -7.0,
        "plumerise": {
            "2015-08-04T18:00:00": PLUMERISE_HOUR,
            "2015-08-04T19:00:00": EMPTY_PLUMERISE_HOUR
        },
        "timeprofiled_area": {
            "2015-08-04T18:00:00": 12.0,
            "2015-08-04T19:00:00": 0.0
        },
        "timeprofiled_emissions": {
            "2015-08-04T18:00:00": {"CO": 0.0, "PM2.5": 4.0},  # == 5.0 * 0.2 + 10.0 * 0.1 + 20.0 * 0.1
            "2015-08-04T19:00:00": {"CO": 0.0, 'PM2.5': 0.0}
        },
        "consumption": CONSUMPTION['summary'],
        "heat": 2000000.0
    })

    # contiguous time windows, no conflicting meta, same location
    FIRE_CONTIGUOUS_TIME_WINDOWS = Fire({
        "id": "SF11C14225236095807750-0",
        "original_fire_ids": {"SF11C14225236095807750"},
        "meta": {'foo': 'bar', 'bar': 'asdasd'},
        "start": datetime.datetime(2015,8,4,19,0,0),
        "end": datetime.datetime(2015,8,4,21,0,0),
        "area": 100.0, "latitude": 47.41, "longitude": -121.41, "utc_offset": -7.0,
        "plumerise": {
            "2015-08-04T19:00:00": PLUMERISE_HOUR,
            "2015-08-04T20:00:00": EMPTY_PLUMERISE_HOUR
        },
        "timeprofiled_area": {
            "2015-08-04T19:00:00": 10.0,
            "2015-08-04T20:00:00": 0.0
        },
        "timeprofiled_emissions": {
            "2015-08-04T19:00:00": {"CO": 0.0, "PM2.5": 5.0},  # == 10.0 * 0.2 + 10.0 * 0.1 + 20.0 * 0.1
            "2015-08-04T20:00:00": {"CO": 0.0, 'PM2.5': 0.0}
        },
        "consumption": CONSUMPTION['summary'],
        "heat": 3000000.0
    })

    # non contiguous time windows, no conflicting meta, same location
    FIRE_NON_CONTIGUOUS_TIME_WINDOWS = Fire({
        "id": "SF11C14225236095807750-0",
        "original_fire_ids": {"SF11C14225236095807750"},
        "meta": {'foo': 'bar', 'bar': 'sdf'},
        "start": datetime.datetime(2015,8,4,20,0,0),
        "end": datetime.datetime(2015,8,4,22,0,0),
        "area": 120.0, "latitude": 47.41, "longitude": -121.41, "utc_offset": -7.0,
        "plumerise": {
            "2015-08-04T20:00:00": PLUMERISE_HOUR,
            "2015-08-04T21:00:00": EMPTY_PLUMERISE_HOUR
        },
        "timeprofiled_area": {
            "2015-08-04T20:00:00": 12.0,
            "2015-08-04T21:00:00": 0.0
        },
        "timeprofiled_emissions": {
            "2015-08-04T20:00:00": {"CO": 0.0, "PM2.5": 4.0},  # == 5.0 * 0.2 + 10.0 * 0.1 + 20.0 * 0.1
            "2015-08-04T21:00:00": {"CO": 0.0, 'PM2.5': 0.0}
        },
        "consumption": CONSUMPTION['summary'],
        "heat": 4000000.0
    })

    FIRE_CONFLICTING_META = Fire({
        "id": "SF11C14225236095807750-0",
        "original_fire_ids": {"SF11C14225236095807750"},
        "meta": {'foo': 'baz'},
        "start": datetime.datetime(2015,8,4,20,0,0),
        "end": datetime.datetime(2015,8,4,22,0,0),
        "area": 120.0, "latitude": 47.41, "longitude": -121.41, "utc_offset": -7.0,
        "plumerise": {
            "2015-08-04T20:00:00": PLUMERISE_HOUR,
            "2015-08-04T21:00:00": EMPTY_PLUMERISE_HOUR
        },
        "timeprofiled_area": {
            "2015-08-04T20:00:00": 12.0,
            "2015-08-04T21:00:00": 0.0
        },
        "timeprofiled_emissions": {
            "2015-08-04T20:00:00": {"CO": 0.0, "PM2.5": 4.0},  # == 5.0 * 0.2 + 10.0 * 0.1 + 20.0 * 0.1
            "2015-08-04T21:00:00": {"CO": 0.0, 'PM2.5': 0.0}
        },
        "consumption": CONSUMPTION['summary'],
        "heat": 5000000.0
    })

    FIRE_DIFFERENT_LAT_LNG = Fire({
        "id": "SF11C14225236095807750-0",
        "original_fire_ids": {"SF11C14225236095807750"},
        "meta": {},
        "start": datetime.datetime(2015,8,4,20,0,0),
        "end": datetime.datetime(2015,8,4,22,0,0),
        "area": 120.0, "latitude": 47.0, "longitude": -121.0, "utc_offset": -7.0,
        "plumerise": {
            "2015-08-04T20:00:00": PLUMERISE_HOUR,
            "2015-08-04T21:00:00": EMPTY_PLUMERISE_HOUR
        },
        "timeprofiled_area": {
            "2015-08-04T20:00:00": 12.0,
            "2015-08-04T21:00:00": 0.0
        },
        "timeprofiled_emissions": {
            "2015-08-04T20:00:00": {"CO": 0.0, "PM2.5": 4.0},  # == 5.0 * 0.2 + 10.0 * 0.1 + 20.0 * 0.1
            "2015-08-04T21:00:00": {"CO": 0.0, 'PM2.5': 0.0}
        },
        "consumption": CONSUMPTION['summary'],
        "heat": 6000000.0
    })

    # def setup_method(self):
    #     pass

    ## Cases that do *not* merge

    def test_one_fire(self):
        original_fire_1 = copy.deepcopy(self.FIRE_1)
        merged_fires = firemerge.FireMerger().merge([self.FIRE_1])

        assert len(merged_fires) == 1
        assert merged_fires == [self.FIRE_1]

        # make sure input fire wasn't modified
        assert self.FIRE_1 == original_fire_1

    def test_differenent_lat_lng(self):
        original_fire_1 = copy.deepcopy(self.FIRE_1)
        original_fire_different_lat_lng = copy.deepcopy(self.FIRE_DIFFERENT_LAT_LNG)

        # shouldn't be merged
        merged_fires = firemerge.FireMerger().merge([self.FIRE_1, self.FIRE_DIFFERENT_LAT_LNG])

        assert len(merged_fires) == 2
        assert merged_fires == [self.FIRE_1, self.FIRE_DIFFERENT_LAT_LNG]

        # make sure input fire wasn't modified
        assert self.FIRE_1 == original_fire_1
        assert self.FIRE_DIFFERENT_LAT_LNG == original_fire_different_lat_lng

    def test_overlapping_time_windows(self):
        original_fire_1 = copy.deepcopy(self.FIRE_1)
        original_overlapping_time_windows = copy.deepcopy(self.FIRE_OVERLAPPING_TIME_WINDOWS)

        # shouldn't be merged
        merged_fires = firemerge.FireMerger().merge([self.FIRE_1, self.FIRE_OVERLAPPING_TIME_WINDOWS])

        assert len(merged_fires) == 2
        assert merged_fires == [self.FIRE_1, self.FIRE_OVERLAPPING_TIME_WINDOWS]

        # make sure input fire wasn't modified
        assert self.FIRE_1 == original_fire_1
        assert self.FIRE_OVERLAPPING_TIME_WINDOWS == original_overlapping_time_windows

    def test_conflicting_meta(self):
        original_fire_1 = copy.deepcopy(self.FIRE_1)
        original_fire_conflicting_meta = copy.deepcopy(self.FIRE_CONFLICTING_META)

        # shouldn't be merged
        merged_fires = firemerge.FireMerger().merge([self.FIRE_1, self.FIRE_CONFLICTING_META])

        assert len(merged_fires) == 2
        assert merged_fires == [self.FIRE_1, self.FIRE_CONFLICTING_META]

        # make sure input fire wasn't modified
        assert self.FIRE_1 == original_fire_1
        assert self.FIRE_CONFLICTING_META == original_fire_conflicting_meta

    ## Cases that merge

    def test_non_contiguous_time_windows(self, monkeypatch):
        monkeypatch.setattr(uuid, 'uuid4', lambda: '1234abcd')

        original_fire_1 = copy.deepcopy(self.FIRE_1)
        original_fire_non_contiguous_time_windows = copy.deepcopy(self.FIRE_NON_CONTIGUOUS_TIME_WINDOWS)

        # *should* be merged
        merged_fires = firemerge.FireMerger().merge([self.FIRE_1, self.FIRE_NON_CONTIGUOUS_TIME_WINDOWS])

        expected_merged_fires = [
            Fire({
                "id": "1234abcd",
                "original_fire_ids": {"SF11C14225236095807750"},
                "meta": {'foo': 'bar', 'bar': 'sdf'},
                "start": datetime.datetime(2015,8,4,17,0,0),
                "end": datetime.datetime(2015,8,4,22,0,0),
                "area": 240.0, "latitude": 47.41, "longitude": -121.41, "utc_offset": -7.0,
                "plumerise": {
                    "2015-08-04T17:00:00": PLUMERISE_HOUR,
                    "2015-08-04T18:00:00": EMPTY_PLUMERISE_HOUR,
                    "2015-08-04T20:00:00": PLUMERISE_HOUR,
                    "2015-08-04T21:00:00": EMPTY_PLUMERISE_HOUR
                },
                "timeprofiled_area": {
                    "2015-08-04T17:00:00": 12.0,
                    "2015-08-04T18:00:00": 0.0,
                    "2015-08-04T20:00:00": 12.0,
                    "2015-08-04T21:00:00": 0.0
                },
                "timeprofiled_emissions": {
                    "2015-08-04T17:00:00": {"CO": 0.0, "PM2.5": 4.0},  # == 5.0 * 0.2 + 10.0 * 0.1 + 20.0 * 0.1
                    "2015-08-04T18:00:00": {"CO": 0.0, 'PM2.5': 0.0},
                    "2015-08-04T20:00:00": {"CO": 0.0, "PM2.5": 4.0},  # == 5.0 * 0.2 + 10.0 * 0.1 + 20.0 * 0.1
                    "2015-08-04T21:00:00": {"CO": 0.0, 'PM2.5': 0.0}
                },
                "consumption": {k: 2*v for k,v in CONSUMPTION['summary'].items()},
                "heat": 5000000.0
            })
        ]

        assert len(merged_fires) == len(expected_merged_fires)
        assert merged_fires == expected_merged_fires

        # make sure input fire wasn't modified
        assert self.FIRE_1 == original_fire_1
        assert self.FIRE_NON_CONTIGUOUS_TIME_WINDOWS == original_fire_non_contiguous_time_windows

    def test_contiguous_time_windows(self, monkeypatch):
        monkeypatch.setattr(uuid, 'uuid4', lambda: '1234abcd')

        original_fire_1 = copy.deepcopy(self.FIRE_1)
        original_fire_contiguous_time_windows = copy.deepcopy(self.FIRE_CONTIGUOUS_TIME_WINDOWS)

        # *should* be merged
        merged_fires = firemerge.FireMerger().merge([self.FIRE_1, self.FIRE_CONTIGUOUS_TIME_WINDOWS])

        expected_merged_fires = [
            Fire({
                "id": "1234abcd",
                "original_fire_ids": {"SF11C14225236095807750"},
                "meta": {'foo': 'bar', 'bar': 'asdasd'},
                "start": datetime.datetime(2015,8,4,17,0,0),
                "end": datetime.datetime(2015,8,4,21,0,0),
                "area": 220.0, "latitude": 47.41, "longitude": -121.41, "utc_offset": -7.0,
                "plumerise": {
                    "2015-08-04T17:00:00": PLUMERISE_HOUR,
                    "2015-08-04T18:00:00": EMPTY_PLUMERISE_HOUR,
                    "2015-08-04T19:00:00": PLUMERISE_HOUR,
                    "2015-08-04T20:00:00": EMPTY_PLUMERISE_HOUR
                },
                "timeprofiled_area": {
                    "2015-08-04T17:00:00": 12.0,
                    "2015-08-04T18:00:00": 0.0,
                    "2015-08-04T19:00:00": 10.0,
                    "2015-08-04T20:00:00": 0.0
                },
                "timeprofiled_emissions": {
                    "2015-08-04T17:00:00": {"CO": 0.0, "PM2.5": 4.0},  # == 5.0 * 0.2 + 10.0 * 0.1 + 20.0 * 0.1
                    "2015-08-04T18:00:00": {"CO": 0.0, 'PM2.5': 0.0},
                    "2015-08-04T19:00:00": {"CO": 0.0, "PM2.5": 5.0},  # == 10.0 * 0.2 + 10.0 * 0.1 + 20.0 * 0.1
                    "2015-08-04T20:00:00": {"CO": 0.0, 'PM2.5': 0.0}
                },
                "consumption": {k: 2*v for k,v in CONSUMPTION['summary'].items()},
                "heat": 4000000.0
            })
        ]

        assert len(merged_fires) == len(expected_merged_fires)
        assert merged_fires == expected_merged_fires

        # make sure input fire wasn't modified
        assert self.FIRE_1 == original_fire_1
        assert self.FIRE_CONTIGUOUS_TIME_WINDOWS == original_fire_contiguous_time_windows

    def test_all(self, monkeypatch):
        monkeypatch.setattr(uuid, 'uuid4', lambda: '1234abcd')

        original_fire_1 = copy.deepcopy(self.FIRE_1)
        original_overlapping_time_windows = copy.deepcopy(self.FIRE_OVERLAPPING_TIME_WINDOWS)
        original_fire_contiguous_time_windows = copy.deepcopy(self.FIRE_CONTIGUOUS_TIME_WINDOWS)
        original_fire_non_contiguous_time_windows = copy.deepcopy(self.FIRE_NON_CONTIGUOUS_TIME_WINDOWS)
        original_fire_conflicting_meta = copy.deepcopy(self.FIRE_CONFLICTING_META)
        original_fire_different_lat_lng = copy.deepcopy(self.FIRE_DIFFERENT_LAT_LNG)

        merged_fires = firemerge.FireMerger().merge([
            self.FIRE_1,
            self.FIRE_OVERLAPPING_TIME_WINDOWS,
            self.FIRE_CONTIGUOUS_TIME_WINDOWS,
            self.FIRE_NON_CONTIGUOUS_TIME_WINDOWS,
            self.FIRE_CONFLICTING_META,
            self.FIRE_DIFFERENT_LAT_LNG
        ])

        expected_merged_fires = [
            # FIRE_1 merged with FIRE_CONTIGUOUS_TIME_WINDOWS
            Fire({
                "id": "1234abcd",
                "original_fire_ids": {"SF11C14225236095807750"},
                "meta": {'foo': 'bar', 'bar': 'asdasd'},
                "start": datetime.datetime(2015,8,4,17,0,0),
                "end": datetime.datetime(2015,8,4,21,0,0),
                "area": 220.0, "latitude": 47.41, "longitude": -121.41, "utc_offset": -7.0,
                "plumerise": {
                    "2015-08-04T17:00:00": PLUMERISE_HOUR,
                    "2015-08-04T18:00:00": EMPTY_PLUMERISE_HOUR,
                    "2015-08-04T19:00:00": PLUMERISE_HOUR,
                    "2015-08-04T20:00:00": EMPTY_PLUMERISE_HOUR
                },
                "timeprofiled_area": {
                    "2015-08-04T17:00:00": 12.0,
                    "2015-08-04T18:00:00": 0.0,
                    "2015-08-04T19:00:00": 10.0,
                    "2015-08-04T20:00:00": 0.0
                },
                "timeprofiled_emissions": {
                    "2015-08-04T17:00:00": {"CO": 0.0, "PM2.5": 4.0},  # == 5.0 * 0.2 + 10.0 * 0.1 + 20.0 * 0.1
                    "2015-08-04T18:00:00": {"CO": 0.0, 'PM2.5': 0.0},
                    "2015-08-04T19:00:00": {"CO": 0.0, "PM2.5": 5.0},  # == 10.0 * 0.2 + 10.0 * 0.1 + 20.0 * 0.1
                    "2015-08-04T20:00:00": {"CO": 0.0, 'PM2.5': 0.0}
                },
                "consumption": {k: 2*v for k,v in CONSUMPTION['summary'].items()},
                "heat": 4000000.0
            }),
            # FIRE_OVERLAPPING_TIME_WINDOWS merged with
            # FIRE_NON_CONTIGUOUS_TIME_WINDOWS
            Fire({
                "id": "1234abcd",
                "original_fire_ids": {"SF11C14225236095807750"},
                "meta": {'foo': 'bar', 'bar': 'sdf'},
                "start": datetime.datetime(2015,8,4,18,0,0),
                "end": datetime.datetime(2015,8,4,22,0,0),
                "area": 240.0, "latitude": 47.41, "longitude": -121.41, "utc_offset": -7.0,
                "plumerise": {
                    "2015-08-04T18:00:00": PLUMERISE_HOUR,
                    "2015-08-04T19:00:00": EMPTY_PLUMERISE_HOUR,
                    "2015-08-04T20:00:00": PLUMERISE_HOUR,
                    "2015-08-04T21:00:00": EMPTY_PLUMERISE_HOUR
                },
                "timeprofiled_area": {
                    "2015-08-04T18:00:00": 12.0,
                    "2015-08-04T19:00:00": 0.0,
                    "2015-08-04T20:00:00": 12.0,
                    "2015-08-04T21:00:00": 0.0
                },
                "timeprofiled_emissions": {
                    "2015-08-04T18:00:00": {"CO": 0.0, "PM2.5": 4.0},
                    "2015-08-04T19:00:00": {"CO": 0.0, 'PM2.5': 0.0},
                    "2015-08-04T20:00:00": {"CO": 0.0, "PM2.5": 4.0},
                    "2015-08-04T21:00:00": {"CO": 0.0, 'PM2.5': 0.0}
                },
                "consumption": {k: 2*v for k,v in CONSUMPTION['summary'].items()},
                "heat": 6000000.0
            }),
            self.FIRE_CONFLICTING_META,
            self.FIRE_DIFFERENT_LAT_LNG
        ]

        assert len(merged_fires) == len(expected_merged_fires)
        assert merged_fires == expected_merged_fires

        # make sure input fire wasn't modified
        assert self.FIRE_1 == original_fire_1
        assert self.FIRE_OVERLAPPING_TIME_WINDOWS == original_overlapping_time_windows
        assert self.FIRE_CONTIGUOUS_TIME_WINDOWS == original_fire_contiguous_time_windows
        assert self.FIRE_NON_CONTIGUOUS_TIME_WINDOWS == original_fire_non_contiguous_time_windows
        assert self.FIRE_CONFLICTING_META == original_fire_conflicting_meta
        assert self.FIRE_DIFFERENT_LAT_LNG == original_fire_different_lat_lng

        # TODO: repeat, but with fires initially in different order


##
## PlumeMerge tests
##

class BaseTestPlumeMerger():

    def setup_method(self):
        self.merger = firemerge.PlumeMerger({
            "grid": {
                "spacing": 0.5,
                "boundary": {
                  "sw": { "lat": 30, "lng": -120 },
                  "ne": { "lat": 40, "lng": -110 }
                }
            }
        })


class TestPlumeMerger_ValidateConfig(BaseTestPlumeMerger):

    def test_invalid(self):
        with pytest.raises(BlueSkyConfigurationError) as e_info:
            firemerge.PlumeMerger({})

        with pytest.raises(BlueSkyConfigurationError) as e_info:
            firemerge.PlumeMerger({"foo": 'sdf'})

        with pytest.raises(BlueSkyConfigurationError) as e_info:
            firemerge.PlumeMerger({"grid": "sdf"})

        with pytest.raises(BlueSkyConfigurationError) as e_info:
            firemerge.PlumeMerger({"grid": {}})

        with pytest.raises(BlueSkyConfigurationError) as e_info:
            firemerge.PlumeMerger({
                "grid": {
                    "boundary": {
                      "sw": { "lat": 30, "lng": -120 },
                      "ne": { "lat": 40, "lng": -110 }
                    }
                }
            })

    def test_valid_not_empty(self):
        firemerge.PlumeMerger({
            "grid": {
                "spacing": 0.5,
                "boundary": {
                  "sw": { "lat": 30, "lng": -120 },
                  "ne": { "lat": 40, "lng": -110 }
                }
            }
        })


class TestPlumeMerger_HelperMethods(BaseTestPlumeMerger):

    def test_bucket_fires(self):
        fires = [
            # The following two fires will be in their own buckets, even
            # though they're within what would be a grid cell, because they're
            # outside the merging boundary
            Fire({'id': '1', 'latitude': 32.1, 'longitude': -100.1}),
            Fire({'id': '1.5', 'latitude': 32.2, 'longitude': -100.2}),
            Fire({'id': '2', 'latitude': 36.22, 'longitude': -111.1}),
            Fire({'id': '3', 'latitude': 32.2, 'longitude': -110}),
            Fire({'id': '4', 'latitude': 32.2, 'longitude': -111.2}),
            Fire({'id': '5', 'latitude': 36.1, 'longitude': -111.4}),
            Fire({'id': '6', 'latitude': 36.4, 'longitude': -111.3})
        ]
        expected = [
            [
                Fire({'id': '5', 'latitude': 36.1, 'longitude': -111.4}),
                Fire({'id': '6', 'latitude': 36.4, 'longitude': -111.3}),
                Fire({'id': '2', 'latitude': 36.22, 'longitude': -111.1})
            ],
            [Fire({'id': '4', 'latitude': 32.2, 'longitude': -111.2})],
            [Fire({'id': '3', 'latitude': 32.2, 'longitude': -110})],
            [Fire({'id': '1.5', 'latitude': 32.2, 'longitude': -100.2})],
            [Fire({'id': '1', 'latitude': 32.1, 'longitude': -100.1})]
        ]
        actual = self.merger._bucket_fires(fires)
        # sort to compare
        for a in actual:
            a.sort(key=lambda f: f.longitude)
        actual.sort(key=lambda fl: fl[0].longitude)

        assert actual == expected

    def test_get_height_midpoints(self):
        assert [] == self.merger._get_height_midpoints([])

        input = [100, 400, 600, 650]
        expected = [250, 500, 625]
        assert expected == self.merger._get_height_midpoints(input)


class TestPlumeMerger_AggregatePlumeriseHour(BaseTestPlumeMerger):

    FIRE_1 = Fire({
        "plumerise": {
            "2015-08-04T17:00:00": {
                "emission_fractions": [0.4, 0.2, 0.2, 0.2],
                "heights": [90, 250, 300, 325, 350],
                "smolder_fraction": 0.05
            }
        },
        "timeprofiled_emissions": {
            "2015-08-04T17:00:00": {"CO": 22.0, "PM2.5": 10.0}
        }
    })

    FIRE_2 = Fire({
        "plumerise": {
            "2015-08-04T17:00:00": {
                "emission_fractions": [0.1,0.3,0.4,0.2],
                "heights": [100,200,300,400,500],
                "smolder_fraction": 0.06
            },
            "2015-08-04T18:00:00": {
                "emission_fractions": [0.5, 0.2, 0.2, 0.1],
                "heights": [300, 350, 400, 425, 450],
                "smolder_fraction": 0.05
            }
        },
        "timeprofiled_emissions": {
            "2015-08-04T17:00:00": {"CO": 1.0, "PM2.5": 2.5},
            "2015-08-04T18:00:00": {"CO": 3.0, "PM2.5": 5.0},
        }
    })

    # Note: no need to test one fire, since _aggregate_plumerise_hour
    #   will never get called with one fire

    def test_two_fires_no_merge(self):
        expected = (
            [(325, 2.5), (375, 1.0), (412.5, 1.0), (437.5, 0.5)],
            300, 450, 0.25, 5.0
        )
        fires = [
            copy.deepcopy(self.FIRE_1),
            copy.deepcopy(self.FIRE_2)
        ]
        actual = self.merger._aggregate_plumerise_hour(
            fires, "2015-08-04T18:00:00")
        assert expected == actual

    def test_two_fires_w_merge(self):
        expected = (

            [(150, 0.25), (170, 4), (250, 0.75), (275, 2),
            (312.5, 2), (337.5, 2), (350, 1.0), (450, 0.5)],
            90, 500, 0.5+0.15, 12.5
        )

        fires = [
            copy.deepcopy(self.FIRE_1),
            copy.deepcopy(self.FIRE_2)
        ]
        assert expected == self.merger._aggregate_plumerise_hour(
            fires, "2015-08-04T17:00:00")

class TestPlumeMerger_MergeFires(BaseTestPlumeMerger):

    FIRE_1 =  Fire({
        "id": "aaa",
        "original_fire_ids": {"bbb"},
        "meta": {'foo': 'bar'},
        "start": datetime.datetime(2015,8,4,17,0,0),
        "end": datetime.datetime(2015,8,4,18,0,0),
        "area": 120.0, "latitude": 47.4, "longitude": -121.5, "utc_offset": -7.0,
        "plumerise": {
            "2015-08-04T17:00:00": {
                "emission_fractions": [0.4, 0.2, 0.2, 0.2],
                "heights": [90, 250, 300, 325, 350],
                "smolder_fraction": 0.05
            }
        },
        "timeprofiled_area": {
            "2015-08-04T17:00:00": 12.0
        },
        "timeprofiled_emissions": {
            "2015-08-04T17:00:00": {"CO": 22.0, "PM2.5": 10.0}
        },
        "consumption": {
            "flaming": 1311,
            "residual": 1449,
            "smoldering": 1267,
            "total": 4027
        },
        "heat": 1000000.0
    })

    FIRE_2 = Fire({
        "id": "ccc",
        "original_fire_ids": {"ddd", "eee"},
        "meta": {'foo': 'bar', 'bar': 'baz'},
        "start": datetime.datetime(2015,8,4,17,0,0),
        "end": datetime.datetime(2015,8,4,19,0,0),
        "area": 150.0, "latitude": 47.6, "longitude": -121.7, "utc_offset": -7.0,
        "plumerise": {
            "2015-08-04T17:00:00": {
                "emission_fractions": [0.1,0.3,0.4,0.2],
                "heights": [100,200,300,400,500],
                "smolder_fraction": 0.06
            },
            "2015-08-04T18:00:00": {
                "emission_fractions": [0.5, 0.2, 0.2, 0.1],
                "heights": [300, 350, 400, 425, 450],
                "smolder_fraction": 0.05
            }
        },
        "timeprofiled_area": {
            "2015-08-04T17:00:00": 20.0,
            "2015-08-04T18:00:00": 30.0
        },
        "timeprofiled_emissions": {
            "2015-08-04T17:00:00": {"CO": 1.0, "PM2.5": 2.5},
            "2015-08-04T18:00:00": {"CO": 3.0, "PM2.5": 5.0}
        },
        "consumption": {
            "flaming": 200,
            "residual": 100,
            "smoldering": 50,
            "total": 400
        },
        "heat": 2000000.0
    })

    FIRE_3 = Fire({
        "id": "ccc",
        "original_fire_ids": {"ddd", "eee"},
        "meta": {'foo': 'bar', 'bar': 'CONFLICT'},
        "start": datetime.datetime(2015,8,4,22,0,0),
        "end": datetime.datetime(2015,8,4,23,0,0),
        "area": 150.0, "latitude": 47.6, "longitude": -121.7, "utc_offset": -7.0,
        "plumerise": {
            "2015-08-04T22:00:00": {
                "emission_fractions": [0.2, 0.2, 0.2, 0.4],
                "heights": [111, 222, 333, 444, 555],
                "smolder_fraction": 0.05
            }
        },
        "timeprofiled_area": {
            "2015-08-04T22:00:00": 20.0
        },
        "timeprofiled_emissions": {
            "2015-08-04T22:00:00": {"CO": 1.0, "PM2.5": 4.0}
        },
        "consumption": {
            "flaming": 100,
            "residual": 2,
            "smoldering": 33,
            "total": 135
        },
        "heat": 2000.0
    })

    def setup_method(self):
        # The config won't come into play in these tests, since we're
        # calling _merge_fires directly
        self.merger = firemerge.PlumeMerger({
            "grid": {
                "spacing": 0.5,
                "boundary": {
                  "sw": { "lat": 30, "lng": -110 },
                  "ne": { "lat": 40, "lng": -120 }
                }
            }
        })

    def test_merge_one(self):
        assert self.FIRE_1 == self.merger._merge_fires([
            copy.deepcopy(self.FIRE_1)
        ])

    def test_merge_two(self, monkeypatch):
        monkeypatch.setattr(uuid, 'uuid4', lambda: '1234abcd')
        expected = Fire({
            "id": "1234abcd",
            "original_fire_ids": ["bbb", "ddd", "eee"],
            "meta": {'foo': 'bar', 'bar': 'baz'},
            "start": datetime.datetime(2015,8,4,17,0,0),
            "end": datetime.datetime(2015,8,4,19,0,0),
            "area": 270.0, "latitude": 47.5, "longitude": -121.6, "utc_offset": -7.0,
            "plumerise": {
                "2015-08-04T17:00:00": {
                    # "emission_fractions": [0.4, 0.2, 0.2, 0.2],
                    # "emission_fractions": [0.1, 0.3, 0.4,0.2],
                    "emission_fractions": [0.34, 0.22, 0.4, 0.04],
                    "heights": [90.0, 192.5, 295.0, 397.5, 500.0],
                    # need to write out how the result is calculated so that
                    # we have the same rounding error in expected as we have
                    # in actual
                    "smolder_fraction": (0.05*10 + 0.06*2.5) / 12.5  # == 0.052
                },
                "2015-08-04T18:00:00": {
                    "emission_fractions": [0.5, 0.2, 0.2, 0.1],
                    "heights": [300, 350, 400, 425, 450],
                    "smolder_fraction": 0.05
                }
            },
            "timeprofiled_area": {
                "2015-08-04T17:00:00": 32.0,
                "2015-08-04T18:00:00": 30.0

            },
            "timeprofiled_emissions": {
                "2015-08-04T17:00:00": {"CO": 23.0, "PM2.5": 12.5},
                "2015-08-04T18:00:00": {"CO": 3.0, "PM2.5": 5.0}
            },
            "consumption": {
                "flaming": 1511,
                "residual": 1549,
                "smoldering": 1317,
                "total": 4427
            },
            "heat": 3000000.0
        })
        actual = self.merger._merge_fires([
            copy.deepcopy(self.FIRE_1),
            copy.deepcopy(self.FIRE_2)
        ])
        assert actual == expected

    def test_merge_three(self, monkeypatch):
        monkeypatch.setattr(uuid, 'uuid4', lambda: '1234abcd')
        expected = Fire({
            "id": "1234abcd",
            "original_fire_ids": {"bbb", "ddd", "eee"},
            "meta": {'foo': 'bar', 'bar': 'CONFLICT'},
            "start": datetime.datetime(2015,8,4,17,0,0),
            "end": datetime.datetime(2015,8,4,23,0,0),
            # TODO: fill in ....
        })
        actual = self.merger._merge_fires([
            copy.deepcopy(self.FIRE_1),
            copy.deepcopy(self.FIRE_2),
            copy.deepcopy(self.FIRE_3)
        ])

        # TODO: uncomment after expected data is filled in
        #assert actual == expected


class TestPlumeMerger_Merge(BaseTestPlumeMerger):
    # TODO: add test with some fires merged and some not
    pass
