"""Installing plugins from Heirloom's plugin repository, against a zip made here rather than GitHub."""
import io
import json
import zipfile

import pytest

from heirloom import plugin_store
from heirloom.plugins import PluginManager

INDEX = [{'name': 'fish', 'common_name': 'Fish', 'description': 'Fish things', 'version': '1.1.0', 'folder': 'fish'}]


def repository(files, top='heirloom-plugins-main'):
    """The repository's zip, as codeload.github.com sends it: everything inside one top folder"""
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        for name, content in files.items():
            if isinstance(content, zipfile.ZipInfo):
                archive.writestr(content, 'target')
            else:
                archive.writestr(f'{top}/{name}', content)
    return data.getvalue()


def fish(version='1.1.0', **extra):
    return {'fish/plugin.json': json.dumps({'name': 'fish', 'common_name': 'Fish', 'version': version}),
            'fish/main.py': 'def setup(plugin):\n    pass\n', 'fish/lib/helper.py': 'X = 1\n',
            'goo/plugin.json': json.dumps({'name': 'goo'}), 'goo/main.py': '', **extra}


@pytest.fixture
def served(monkeypatch):
    """What "GitHub" serves: set its files, and the downloads are counted"""
    state = {'files': fish(), 'downloads': 0}

    def download(url):
        assert url == plugin_store.ARCHIVE, 'only the one repository'
        state['downloads'] += 1
        return repository(state['files'])

    monkeypatch.setattr(plugin_store, '_download', download)
    return state


def test_installs_only_that_plugins_folder_then_updates_it(tmp_path, served):
    plugins = tmp_path / 'plugins'
    assert plugin_store.install(plugins, 'fish', INDEX).version == '1.1.0'
    assert sorted(path.relative_to(plugins).as_posix() for path in plugins.rglob('*') if path.is_file()) == [
        'fish/lib/helper.py', 'fish/main.py', 'fish/plugin.json'], 'none of the other plugins, nothing left over'

    (plugins / 'fish' / 'settings.json').write_text('{}')
    served['files'] = fish('1.2.0')
    assert plugin_store.install(plugins, 'fish', INDEX).version == '1.2.0'
    assert PluginManager(plugins).discover()['fish'][1].version == '1.2.0'
    assert not (plugins / 'fish' / 'settings.json').exists(), 'an update is the repository copy'
    assert [path.name for path in plugins.iterdir()] == ['fish']

    with pytest.raises(ValueError):
        plugin_store.install(plugins, 'shark', INDEX)


@pytest.mark.parametrize('bad, why', [
    ({'fish/../../escape.py': 'x'}, 'a file outside its folder'),
    ({'fish/plugin.json': json.dumps({'name': 'shark'})}, 'named "shark"'),
    ({'fish/plugin.json': '{not json'}, ''),
    ({'fish/big.bin': b'0' * (plugin_store.MAX_PLUGIN + 1)}, 'larger than expected'),
])
def test_a_bad_update_keeps_the_old_copy(tmp_path, served, bad, why):
    plugins = tmp_path / 'plugins'
    plugin_store.install(plugins, 'fish', INDEX)
    served['files'] = fish('2.0.0', **bad)
    with pytest.raises(ValueError, match=why):
        plugin_store.install(plugins, 'fish', INDEX)
    assert PluginManager(plugins).discover()['fish'][1].version == '1.1.0'
    assert [path.name for path in plugins.iterdir()] == ['fish'], 'nothing half-unpacked left behind'


def test_links_are_refused(tmp_path, served):
    link = zipfile.ZipInfo('heirloom-plugins-main/fish/link')
    link.external_attr = 0o120777 << 16
    served['files'] = fish(link=link)
    with pytest.raises(ValueError, match='link'):
        plugin_store.install(tmp_path / 'plugins', 'fish', INDEX)


def test_index_keeps_only_well_named_plugins(monkeypatch):
    listed = {'plugins': [INDEX[0], {'name': '../evil', 'folder': 'x'}, {'name': 'ok', 'folder': '../x'}, 'junk']}
    response = type('Response', (), {'raise_for_status': lambda self: None, 'json': lambda self: listed})()
    monkeypatch.setattr('requests.get', lambda url, **options: response)
    assert plugin_store.fetch_index() == INDEX


def test_newer_versions():
    assert plugin_store.newer('1.10.0', '1.9.2') and not plugin_store.newer('1.1', '1.1')
    assert not plugin_store.newer('1.0.0', '1.1.0')
    assert plugin_store.newer('2024-beta', '1.0'), 'any other difference counts as newer'


def test_remove(tmp_path, served):
    plugins = tmp_path / 'plugins'
    plugin_store.install(plugins, 'fish', INDEX)
    PluginManager(plugins).set_enabled('fish', True)
    plugin_store.remove(plugins, 'fish')
    assert not (plugins / 'fish').exists() and PluginManager(plugins).enabled() == set()
    with pytest.raises(ValueError):
        plugin_store.remove(plugins, 'fish')


def test_plugins_in_the_window(lgd_home, served, monkeypatch):
    from heirloom.gui.app import GuiApi, Job, Jobs
    index = [INDEX[0] | {'version': '1.2.0'}]
    monkeypatch.setattr(plugin_store, 'fetch_index', lambda: index)
    served['files'] = fish('1.1.0', **{'fish/plugin.json': json.dumps({
        'name': 'fish', 'common_name': 'Fish', 'version': '1.1.0',
        'actions': [{'title': 'Count the fish', 'command': 'fish-count'}]})})
    api = GuiApi(None, lambda: {}, command=lambda: ['heirloom'])
    assert api.plugins()['store'] == [{'name': 'fish', 'title': 'Fish', 'description': 'Fish things',
                                       'version': '1.2.0', 'installed': False}]

    fish_plugin, = api.install_plugin('fish')['installed']
    assert fish_plugin == {'name': 'fish', 'title': 'Fish', 'description': '', 'version': '1.1.0', 'enabled': True,
                           'error': None, 'actions': [{'title': 'Count the fish', 'command': 'fish-count'}],
                           'update': '1.2.0'}, 'turned on, and the store has a newer one'
    (lgd_home / 'plugins' / 'errors.json').write_text(json.dumps({'fish': 'failed to load: oops'}))
    assert api.plugins()['installed'][0]['error'] == 'oops'

    monkeypatch.setattr(api._jobs, 'add', lambda kind, app_name, title, options: added.append((kind, title, options)))
    added = []
    api.run_plugin_action('fish', 'fish-count')
    assert added == [('plugin', 'Count the fish', ['fish-count'])]
    assert api._command(Job(1, 'plugin', '', 'Count the fish', options=['fish-count'])) == ['heirloom', '-y',
                                                                                           'fish-count']
    for name, command in (('fish', 'rm'), ('goo', 'fish-count')):
        with pytest.raises(ValueError):
            api.run_plugin_action(name, command)
    api.set_plugin('fish', False)
    with pytest.raises(ValueError):
        api.run_plugin_action('fish', 'fish-count')

    job = Job(2, 'plugin', '', 'Count the fish')
    for line in ('[cli] INFO: Counting...', '  12 fish', *['more'] * 300):
        Jobs._read(job, line)
    assert job.output[:2] == ['Counting...', '  12 fish'] and len(job.output) == 200, 'what it printed, capped'

    def offline():
        raise plugin_store.requests.ConnectionError('no network')
    monkeypatch.setattr(plugin_store, 'fetch_index', offline)
    api = GuiApi(None, lambda: {})
    plugins = api.plugins()
    assert plugins['store'] is None and 'GitHub' in plugins['store_error']
    assert plugins['installed'][0]['name'] == 'fish', 'installed ones show without the store'
    with pytest.raises(ValueError, match='GitHub'):
        api.install_plugin('fish')
