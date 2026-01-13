from datetime import datetime

import pytz

from hippique_orchestrator import time_utils


def test_get_tz():
    assert time_utils.get_tz() == pytz.timezone('Europe/Paris')


def test_get_today_str(mocker):
    mock_now = datetime(2023, 10, 26, 12, 0, 0)
    mocker.patch(
        'hippique_orchestrator.time_utils.datetime',
        mocker.Mock(now=mocker.Mock(return_value=mock_now)),
    )
    assert time_utils.get_today_str() == '2023-10-26'


def test_convert_local_to_utc_naive():
    naive_dt = datetime(2023, 10, 26, 14, 30, 0)
    utc_dt = time_utils.convert_local_to_utc(naive_dt)
    assert utc_dt.tzinfo is not None
    assert utc_dt.utcoffset().total_seconds() == 0
    assert utc_dt.strftime('%Y-%m-%d %H:%M:%S') == '2023-10-26 12:30:00'


def test_convert_local_to_utc_aware():
    paris_tz = pytz.timezone('Europe/Paris')
    aware_dt = paris_tz.localize(datetime(2023, 10, 26, 14, 30, 0))
    utc_dt = time_utils.convert_local_to_utc(aware_dt)
    assert utc_dt.tzinfo is not None
    assert utc_dt.utcoffset().total_seconds() == 0
    assert utc_dt.strftime('%Y-%m-%d %H:%M:%S') == '2023-10-26 12:30:00'


def test_format_rfc3339():
    dt = datetime(2023, 10, 26, 14, 30, 0)
    assert time_utils.format_rfc3339(dt) == '2023-10-26T14:30:00Z'
