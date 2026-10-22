import json
from datetime import datetime, timedelta, timezone

import pytest

from legendary.lfs.lgndry import LGDLFS
from legendary.lfs.utils import LockedJSONData
from legendary.models.game import PlaytimeSession
from legendary.utils.cli import format_duration

from .test_cli import launch_fish, run

T0 = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(('exit_code', 'result'), [(0, 'exited'), (3, 'crashed'), (-1073741819, 'crashed'),
                                                   (None, 'unobservable')])
def test_session_result_follows_exit_code(exit_code, result):
    assert PlaytimeSession(T0, T0, exit_code).result == result


def test_session_json_roundtrip():
    session = PlaytimeSession(T0, T0 + timedelta(minutes=90), 0)
    assert PlaytimeSession.from_json(json.loads(json.dumps(session.to_json()))) == session
    assert session.duration == timedelta(minutes=90)


@pytest.mark.parametrize(('seconds', 'text'), [(0, '0s'), (59.9, '59s'), (61, '1m 01s'), (3600, '1h 00m'),
                                               (4 * 3600 + 5 * 60 + 9, '4h 05m')])
def test_format_duration(seconds, text):
    assert format_duration(seconds) == text


def test_locked_json_data_saves_in_place_changes(tmp_path):
    path = tmp_path / 'data.json'
    path.write_text('{"a": [1]}')
    with LockedJSONData(str(path)) as lock:
        lock.data['a'].append(2)
    assert json.loads(path.read_text()) == {'a': [1, 2]}


def test_sessions_accumulate_per_app(lgd_home):
    lgd = LGDLFS()
    assert lgd.get_playtime() == {}
    lgd.add_playtime_session('Fish', PlaytimeSession(T0, T0 + timedelta(hours=1), 0))
    LGDLFS().add_playtime_session('Fish', PlaytimeSession(T0, T0 + timedelta(minutes=5), 1))
    lgd.add_playtime_session('Cat', PlaytimeSession(T0, T0, None))

    playtime = LGDLFS().get_playtime()
    assert [s.result for s in playtime['Fish']] == ['exited', 'crashed']
    assert [s.result for s in playtime['Cat']] == ['unobservable']


def test_launch_waits_and_records_sessions(fake_game, monkeypatch):
    clean = launch_fish(monkeypatch, 0)
    assert clean.returncode == 0, clean.stderr
    assert 'Fish exited after' in clean.stderr

    crash = launch_fish(monkeypatch, 3)
    assert 'Fish crashed after' in crash.stderr and '0x00000003' in crash.stderr

    sessions = json.loads((fake_game / 'playtime.json').read_text())['Fish']
    assert [s['exit_code'] for s in sessions] == [0, 3]
    for s in sessions:
        duration = datetime.fromisoformat(s['end']) - datetime.fromisoformat(s['start'])
        assert duration >= timedelta(seconds=0.5), 'session spans the time the game ran'

    report = json.loads(run('playtime', '--json').stdout)
    assert len(report) == 1
    assert report[0]['title'] == 'Fish Game' and report[0]['sessions'] == 2 and report[0]['total_seconds'] >= 1

    text = run('playtime', 'Fish').stdout
    assert 'Fish Game (Fish)' in text and '2 session(s)' in text
    assert '(exited)' in text and '(crashed)' in text


def test_launch_no_wait_and_config_opt_out_record_nothing(fake_game, monkeypatch):
    result = launch_fish(monkeypatch, 0, '--no-wait')
    assert result.returncode == 0, result.stderr
    assert 'Waiting for the game' not in result.stderr

    (fake_game / 'config.ini').write_text('[Legendary]\ndisable_playtime_tracking = true\n')
    launch_fish(monkeypatch, 0)

    assert not (fake_game / 'playtime.json').exists()
    assert 'No playtime recorded yet' in run('playtime').stdout
