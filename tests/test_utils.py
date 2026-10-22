import locale
import sys
import warnings

import pytest

from heirloom.lfs.utils import clean_filename
from heirloom.utils.aliasing import generate_aliases
from heirloom.utils.cli import (
    get_boolean_choice,
    get_int_choice,
    sdl_prompt,
    strtobool,
)
from heirloom.utils.env import get_system_locale
from heirloom.utils.selective_dl import get_sdl_appname


@pytest.mark.parametrize(('env', 'expected'), [
    ({'LANG': 'de_DE.UTF-8'}, 'de_DE'),
    ({'LANG': 'de_DE@euro'}, 'de_DE'),
    ({'LANGUAGE': 'fr_FR:en_US'}, 'fr_FR'),
    ({'LANG': 'en_GB', 'LC_ALL': 'ja_JP.UTF-8'}, 'en_GB'),
    ({'LC_CTYPE': 'pt_BR'}, 'pt_BR'),
    ({'LANG': 'C'}, None),
    ({'LANG': 'POSIX'}, None),
    ({}, None),
])
def test_system_locale_posix(monkeypatch, env, expected):
    monkeypatch.setattr(sys, 'platform', 'linux')
    for var in ('LANG', 'LANGUAGE', 'LC_ALL', 'LC_CTYPE'):
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    assert get_system_locale() == expected


@pytest.mark.skipif(sys.platform != 'win32' or sys.version_info >= (3, 15), reason='compares to the removed stdlib call')
def test_system_locale_matches_getdefaultlocale_on_windows():
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', DeprecationWarning)
        assert get_system_locale() == locale.getdefaultlocale()[0]


def test_aliases_include_initialisms_and_roman_numerals():
    aliases = generate_aliases('Grand Theft Auto V')
    assert {'grand theft auto v', 'grandtheftautov', 'grandtheftauto5', 'gtav', 'gta5'} <= set(aliases)
    assert aliases == sorted(set(aliases))


def test_aliases_split_long_words_on_f():
    assert 'swbf2' in generate_aliases('Star Wars Battlefront II')
    assert 'swbf2' not in generate_aliases('Star Wars Battlefront II', split_words=False)


def test_aliases_subtitle_folder_and_app_name():
    aliases = generate_aliases('Control: Ultimate Edition', game_folder='Ctrl', app_name='Calluna')
    assert {'control', 'ctrl', 'calluna'} <= set(aliases)


@pytest.mark.parametrize(('value', 'expected'), [('YES', 1), ('on', 1), ('0', 0), ('', 0), ('off', 0)])
def test_strtobool(value, expected):
    assert strtobool(value) == expected


def test_strtobool_rejects_garbage():
    with pytest.raises(ValueError):
        strtobool('maybe')


def test_boolean_choice(monkeypatch):
    monkeypatch.setattr('builtins.input', lambda _: '')
    assert get_boolean_choice('?', default=False) is False
    monkeypatch.setattr('builtins.input', lambda _: 'yep')
    assert get_boolean_choice('?', default=False) is True


def test_int_choice_retries_once_then_gives_up(monkeypatch):
    answers = iter(['nope', '99'])
    monkeypatch.setattr('builtins.input', lambda _: next(answers))
    assert get_int_choice('?', max_choice=10) is None


def test_int_choice_accepts_valid(monkeypatch):
    monkeypatch.setattr('builtins.input', lambda _: '3')
    assert get_int_choice('?', min_choice=1, max_choice=5) == 3


def test_sdl_prompt_collects_required_and_chosen_tags(monkeypatch):
    sdl = {'__required': {'tags': ['core'], 'name': 'Core'},
           'de': {'tags': ['voice_de'], 'name': 'Deutsch'},
           'fr': {'tags': ['voice_fr'], 'name': 'Francais'}}
    monkeypatch.setattr('builtins.input', lambda _: 'de, bogus')
    assert sdl_prompt(sdl, 'Game') == ['', 'core', 'voice_de']


def test_sdl_appname():
    assert get_sdl_appname('Fortnite_Something') == 'Fortnite'
    assert get_sdl_appname('Unknown') is None


def test_clean_filename():
    assert clean_filename('a<b>:c"d/e\\f|g?h*') == 'abcdefgh'
