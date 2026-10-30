"""Launching a game logs in without asking Epic first, and logs in again only when Epic refuses the saved login."""
import json
from types import SimpleNamespace

import pytest
from requests import Response
from requests.exceptions import HTTPError

from heirloom.api.egs import EPCAPI
from heirloom.cli import HeirloomCLI
from heirloom.core import HeirloomCore

LOGIN = {'account_id': 'abc', 'displayName': 'Tester', 'access_token': 'eg1~a', 'refresh_token': 'eg1~r'}


def save_login(lgd_home, expires_at):
    lgd_home.mkdir(exist_ok=True)
    (lgd_home / 'user.json').write_text(json.dumps(LOGIN | {'expires_at': expires_at}))


def no_network(*args, **kwargs):
    raise AssertionError('asked Epic')


def test_quick_login_uses_a_session_with_time_left(lgd_home, monkeypatch):
    save_login(lgd_home, '2099-01-01T00:00:00.000Z')
    for name in ('resume_session', 'start_session'):
        monkeypatch.setattr(EPCAPI, name, no_network)
    monkeypatch.setattr(HeirloomCore, 'check_for_updates', no_network)
    core = HeirloomCore()
    assert core.login(quick=True)
    assert core.egs.user['account_id'] == 'abc'
    assert core.egs.session.headers['Authorization'] == 'bearer eg1~a'
    assert core.login(), 'a later login in the same run is free too'


def test_quick_login_refreshes_a_session_about_to_end(lgd_home, monkeypatch):
    save_login(lgd_home, '2000-01-01T00:00:00.000Z')
    refreshed = LOGIN | {'access_token': 'eg1~new', 'expires_at': '2099-01-01T00:00:00.000Z'}
    monkeypatch.setattr(EPCAPI, 'start_session', lambda self, refresh_token: refreshed)
    monkeypatch.setattr(HeirloomCore, 'check_for_updates', lambda self: None)
    core = HeirloomCore()
    assert core.login(quick=True)
    assert core.lgd.userdata['access_token'] == 'eg1~new'


def refusal(status):
    response = Response()
    response.status_code = status
    return HTTPError(response=response)


def test_a_refused_login_is_refreshed_once():
    logins, calls = [], []

    def call():
        calls.append(1)
        if len(calls) == 1:
            raise refusal(401)
        return 'parameters'

    cli = SimpleNamespace(core=SimpleNamespace(login=lambda force_refresh: logins.append(force_refresh) or True))
    assert HeirloomCLI._logged_in(cli, call) == 'parameters'
    assert logins == [True] and len(calls) == 2

    def broken():
        raise refusal(500)
    with pytest.raises(HTTPError):
        HeirloomCLI._logged_in(cli, broken)
    assert logins == [True], 'only a refused login is logged in again'
