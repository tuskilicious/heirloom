import io
import json
import logging

import pytest

from heirloom.plugins import PluginManager, PluginManifest
from heirloom.themes import (
    BUILTIN_THEMES,
    DEFAULT_THEME,
    Theme,
    ThemedFormatter,
    load_themes,
    parse_style,
)

from .test_cli import run

ESC = chr(27)


@pytest.mark.parametrize(('spec', 'codes'), [
    ('', None),
    ('bold', '1'),
    ('red', '31'),
    ('bright_cyan', '96'),
    ('bold underline white on red', '1;4;37;41'),
    ('on bright_black', '100'),
    ('#ff5500', '38;2;255;85;0'),
    ('dim on #000080', '2;48;2;0;0;128'),
])
def test_parse_style(spec, codes):
    assert parse_style(spec) == (f'{ESC}[{codes}m' if codes else '')


@pytest.mark.parametrize('spec', ['purple', 'on', 'on bold', '#12345', 'bright_bold'])
def test_parse_style_rejects_unknown(spec):
    with pytest.raises(ValueError):
        parse_style(spec)


def test_theme_file_inherits_defaults_and_validates():
    theme = Theme.from_json({'name': 'mine', 'colors': {'error': 'magenta'}, 'symbols': {'bullet': '>'}}, 'user')
    assert theme.styles['error'] == parse_style('magenta')
    assert theme.styles['warning'] == DEFAULT_THEME.styles['warning']
    assert theme.symbols == {'bullet': '>', 'alert': '!'}
    assert theme.common_name == 'mine'

    for bad in ({'name': 'Bad Name'}, {'name': 'x', 'colors': {'title': 'red'}},
                {'name': 'x', 'colors': {'error': 'purple'}}, {'name': 'x', 'symbols': {'bullet': '>>>>'}},
                {'name': 'x', 'symbols': {'arrow': '>'}}):
        with pytest.raises(ValueError):
            Theme.from_json(bad, 'user')


class FakeStream(io.StringIO):
    def __init__(self, tty):
        super().__init__()
        self.tty = tty

    def isatty(self):
        return self.tty


@pytest.mark.parametrize(('env', 'tty', 'coloured'), [
    ({}, False, False),
    ({'FORCE_COLOR': '1'}, False, True),
    ({'NO_COLOR': '1', 'FORCE_COLOR': '1'}, False, False),
    ({'NO_COLOR': '1'}, True, False),
    ({'TERM': 'dumb'}, True, False),
])
def test_colours_follow_terminal_and_env(monkeypatch, env, tty, coloured):
    for var in ('NO_COLOR', 'FORCE_COLOR', 'TERM'):
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    theme = BUILTIN_THEMES['modern'].for_stream(FakeStream(tty))
    assert (ESC in theme.alert('x')) is coloured
    assert theme.bullet('Title').startswith('•'), 'symbols do not depend on colour'


def test_formatter_colours_by_level():
    theme = BUILTIN_THEMES['default']
    formatter = ThemedFormatter(theme)
    record = logging.LogRecord('cli', logging.WARNING, __file__, 1, 'careful %s', ('now',), None)
    assert formatter.format(record) == (f'{theme.styles["logger"]}[cli]{ESC}[0m '
                                        f'{theme.styles["warning"]}WARNING: careful now{ESC}[0m')
    plain = ThemedFormatter(BUILTIN_THEMES['plain'])
    assert plain.format(record) == '[cli] WARNING: careful now', 'the plain theme keeps the classic log format'


def test_load_themes_from_user_folder_and_plugins(tmp_path):
    user = tmp_path / 'themes'
    user.mkdir()
    (user / 'mine.json').write_text(json.dumps({'name': 'mine'}))
    (user / 'clash.json').write_text(json.dumps({'name': 'modern'}))
    (user / 'broken.json').write_text('{oops')
    plugin_theme = tmp_path / 'dracula.json'
    plugin_theme.write_text(json.dumps({'name': 'dracula', 'colors': {'accent': 'bold #bd93f9'}}))

    themes, errors = load_themes(user, [('dracula-theme', plugin_theme)])
    assert set(themes) == set(BUILTIN_THEMES) | {'mine', 'dracula'}
    assert themes['dracula'].source == 'plugin "dracula-theme"'
    assert 'already exists' in errors['clash.json (user)']
    assert 'broken.json (user)' in errors
    assert load_themes(tmp_path / 'missing', [])[0] == BUILTIN_THEMES


def theme_plugin(plugins_dir):
    folder = plugins_dir / 'dracula-theme'
    (folder / 'themes').mkdir(parents=True)
    (folder / 'plugin.json').write_text(json.dumps({
        'name': 'dracula-theme', 'useBackend': False, 'themes': ['themes/dracula.json']}))
    (folder / 'themes' / 'dracula.json').write_text(json.dumps({
        'name': 'dracula', 'common_name': 'Dracula', 'colors': {'accent': 'bold #bd93f9'}, 'symbols': {'bullet': '>'}}))
    return folder


def test_theme_only_plugin_needs_no_backend_and_must_be_enabled(tmp_path):
    import argparse
    plugins_dir = tmp_path / 'plugins'
    theme_plugin(plugins_dir)
    sub = argparse.ArgumentParser().add_subparsers()

    manager = PluginManager(plugins_dir)
    manager.load(sub)
    assert manager.theme_files() == [], 'disabled plugins provide no themes'

    manager.set_enabled('dracula-theme', True)
    manager.load(sub)
    assert manager.errors == {}
    assert [name for name, _ in manager.theme_files()] == ['dracula-theme']

    (plugins_dir / 'dracula-theme' / 'plugin.json').write_text(json.dumps({'name': 'x', 'themes': ['../out.json']}))
    with pytest.raises(ValueError):
        PluginManifest.read(plugins_dir / 'dracula-theme')


def test_themes_end_to_end_through_the_cli(fake_game, monkeypatch):
    monkeypatch.delenv('NO_COLOR', raising=False)
    listing = run('themes').stdout
    assert all(f'({name})' in listing for name in BUILTIN_THEMES)
    assert '(default) (active)' in listing

    assert run('themes', 'use', 'nope').returncode != 0
    assert run('themes', 'use', 'modern').returncode == 0
    assert 'theme = modern' in (fake_game / 'config.ini').read_text()
    assert '(modern) (active)' in run('themes').stdout

    installed = run('list-installed').stdout
    assert ' • Fish Game' in installed and ESC not in installed, 'symbols apply, colours only on a terminal'
    monkeypatch.setenv('FORCE_COLOR', '1')
    coloured = run('list-installed').stdout
    assert f'{parse_style("bold bright_cyan")}Fish Game{ESC}[0m' in coloured

    theme_plugin(fake_game / 'plugins')
    assert run('themes', 'use', 'dracula').returncode != 0, 'themes of disabled plugins are not available'
    run('plugins', 'enable', 'dracula-theme')
    assert run('themes', 'use', 'dracula').returncode == 0
    assert f'> {parse_style("bold #bd93f9")}Fish Game' in run('list-installed').stdout

    run('plugins', 'disable', 'dracula-theme')
    fallback = run('list-installed')
    assert 'Theme "dracula" is not available' in fallback.stderr
    assert ' * ' in fallback.stdout, 'falls back to the default theme'
