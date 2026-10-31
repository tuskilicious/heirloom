import argparse
import json
from textwrap import dedent

import pytest

from heirloom.models.game import InstalledGame
from heirloom.plugins import (
    GameExited,
    GameInstalled,
    GameUpdated,
    PluginManager,
    PluginManifest,
    install_event,
)

from .test_cli import launch_fish, run


def make_plugin(plugins_dir, folder, backend_source, manifest=None, extra_files=None):
    path = plugins_dir / folder
    path.mkdir(parents=True)
    (path / 'plugin.json').write_text(json.dumps(manifest or {'name': folder}))
    (path / 'main.py').write_text(dedent(backend_source))
    for name, source in (extra_files or {}).items():
        (path / name).write_text(dedent(source))
    return path


def test_manifest_defaults_and_validation(tmp_path):
    folder = tmp_path / 'p'
    folder.mkdir()

    (folder / 'plugin.json').write_text('{"name": "my-plugin_2"}')
    manifest = PluginManifest.read(folder)
    assert (manifest.common_name, manifest.backend) == ('my-plugin_2', 'main.py')

    (folder / 'plugin.json').write_text(json.dumps({'name': 'worth', 'actions': [
        {'title': " Work out my library's worth ", 'command': 'worth'}]}))
    assert PluginManifest.read(folder).actions == (("Work out my library's worth", 'worth'),)

    for bad in ({}, {'name': 'Upper'}, {'name': 'has space'}, {'name': 'ok', 'backend': '../escape.py'},
                {'name': 'ok', 'actions': [{'title': 'Run', 'command': 'rm -rf'}]},
                {'name': 'ok', 'actions': [{'command': 'worth'}]}, {'name': 'ok', 'actions': ['worth']}):
        (folder / 'plugin.json').write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            PluginManifest.read(folder)


def test_install_event():
    game = InstalledGame(app_name='Fish', install_path='/g', title='Fish', version='2')
    assert install_event('Fish', game, None) == GameInstalled('Fish', game)
    assert install_event('Fish', game, '1') == GameUpdated('Fish', game, '1')
    assert install_event('Fish', game, '2') is None, 'a repair keeps the version and is not an update'


@pytest.fixture
def subparsers():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='subparser_name')
    subparsers.add_parser('install')
    return parser, subparsers


def test_loads_only_enabled_plugins_and_isolates_failures(tmp_path, subparsers):
    parser, sub = subparsers
    plugins_dir = tmp_path / 'plugins'
    make_plugin(plugins_dir, 'good', '''
        CALLS = []
        def setup(plugin):
            plugin.on('game_exited', lambda event: 1 / 0)
            plugin.on('game_exited', CALLS.append)
            plugin.command('hello', lambda args, core: CALLS.append(args.who), help='Say hi').add_argument('who')
            plugin.command('install', lambda args, core: None)
    ''')
    make_plugin(plugins_dir, 'boom', '''
        def setup(plugin):
            plugin.on('game_exited', lambda event: event.session.append('boom'))
            raise RuntimeError('broken plugin')
    ''')
    make_plugin(plugins_dir, 'typo', 'def setup(plugin):\n    plugin.on("game_exit", print)\n')
    make_plugin(plugins_dir, 'off', 'raise SystemExit("must not be imported")\n')
    (plugins_dir / 'broken').mkdir()
    (plugins_dir / 'broken' / 'plugin.json').write_text('{not json')

    manager = PluginManager(plugins_dir)
    for name in ('good', 'boom', 'typo'):
        manager.set_enabled(name, True)
    original_install = sub.choices['install']
    manager.load(sub)

    assert set(manager.plugins) == {'good'}
    assert 'broken plugin' in manager.errors['boom']
    assert 'Unknown event "game_exit"' in manager.errors['typo']
    assert 'invalid plugin.json' in manager.errors['broken']

    event = GameExited('Fish', session=[])
    manager.emit(event)
    calls = __import__('heirloom_plugin_good').CALLS
    assert calls == [event], 'a failing handler does not stop the next one'
    assert event.session == [], 'a plugin whose setup() failed gets no events'

    assert manager.load_errors() == {'boom': manager.errors['boom'], 'typo': manager.errors['typo']}, \
        'kept for the window, which loads no plugins itself'

    # fixed, it loads, and its error is gone; the others' stay until they load
    (plugins_dir / 'typo' / 'main.py').write_text('def setup(plugin):\n    pass\n')
    PluginManager(plugins_dir).load(argparse.ArgumentParser().add_subparsers())
    assert set(PluginManager(plugins_dir).load_errors()) == {'boom'}

    assert sub.choices['install'] is original_install, 'plugins cannot replace built-in commands'
    args = parser.parse_args(['hello', 'world'])
    manager.run_command(args, core=None)
    assert calls[-1] == 'world'


def test_multi_file_plugin_and_enabled_state(tmp_path, subparsers):
    _, sub = subparsers
    plugins_dir = tmp_path / 'plugins'
    make_plugin(plugins_dir, 'multi', '''
        from . import helper
        def setup(plugin):
            plugin.on('game_installed', helper.remember)
    ''', extra_files={'helper.py': 'SEEN = []\ndef remember(event):\n    SEEN.append(event.app_name)\n'})

    manager = PluginManager(plugins_dir)
    manager.set_enabled('multi', True)
    manager.set_enabled('multi', False)
    manager.load(sub)
    assert manager.plugins == {}

    manager.set_enabled('multi', True)
    manager.load(sub)
    manager.emit(GameInstalled('Fish', game=None))
    assert __import__('heirloom_plugin_multi.helper', fromlist=['SEEN']).SEEN == ['Fish']


def test_unreadable_enabled_list_enables_nothing(tmp_path):
    (tmp_path / 'enabled.json').write_text('{oops')
    assert PluginManager(tmp_path).enabled() == set()


DEMO_PLUGIN = '''
    from . import recorder

    def setup(plugin):
        def launching(event):
            event.environment['EXIT_CODE'] = '5'
            recorder.write(plugin.folder, 'game_launching', event.app_name, event.game.title)

        def exited(event):
            recorder.write(plugin.folder, 'game_exited', event.app_name, event.session.result,
                           event.session.exit_code)

        plugin.on('game_launching', launching)
        plugin.on('game_exited', exited)
        hello = plugin.command('hello', lambda args, core: print(f'hello {args.who}, {len(core.get_installed_list())} game(s)'),
                               help='Greet someone')
        hello.add_argument('who')
'''

RECORDER = '''
    import json

    def write(folder, *fields):
        with (folder / 'events.jsonl').open('a') as f:
            f.write(json.dumps(fields) + chr(10))
'''


def test_plugin_end_to_end_through_the_cli(fake_game, monkeypatch):
    folder = make_plugin(fake_game / 'plugins', 'demo-folder', DEMO_PLUGIN, extra_files={'recorder.py': RECORDER},
                         manifest={'name': 'demo', 'common_name': 'Demo Plugin', 'version': '1.0',
                                   'description': 'Records events'})

    listing = run('plugins').stdout
    assert 'Demo Plugin (demo) 1.0 [disabled]' in listing
    assert run('hello', 'you').returncode != 0, 'a disabled plugin adds no commands'

    assert run('plugins', 'enable', 'demo').returncode == 0
    assert run('plugins', 'enable', 'missing').returncode != 0
    listing = run('plugins').stdout
    assert '[enabled]' in listing and 'Commands: hello' in listing

    hello = run('hello', 'world')
    assert hello.returncode == 0, hello.stderr
    assert 'hello world, 1 game(s)' in hello.stdout

    launch_fish(monkeypatch, 0, '--dry-run')
    assert not (folder / 'events.jsonl').exists(), 'a dry run launches nothing'

    result = launch_fish(monkeypatch, 0)
    assert 'Fish crashed after' in result.stderr, 'the environment change from game_launching reached the game'
    events = [json.loads(line) for line in (folder / 'events.jsonl').read_text().splitlines()]
    assert events == [['game_launching', 'Fish', 'Fish Game'], ['game_exited', 'Fish', 'crashed', 5]]

    run('plugins', 'disable', 'demo')
    assert run('hello', 'world').returncode != 0
