"""
Looks at the real packaged window, through Chromium's debugging port: run Heirloom with
QTWEBENGINE_REMOTE_DEBUGGING=<port> first. Exits non-zero unless the page and its API work. With a folder, it also takes
a screenshot of each screen in each theme and mode, over a made-up library, and lists what looks broken.
    python tests/window_probe.py <port> [folder for screenshots]
"""
import base64
import contextlib
import itertools
import json
import sys
import time
import urllib.request
from pathlib import Path

import websocket

FEATURES = """({
  url: location.href,
  engine: navigator.userAgent,
  secure: isSecureContext,
  api: typeof pywebview === 'object' && typeof pywebview.api?.state === 'function',
  library: !!document.querySelector('#library'),
  transitions: typeof document.startViewTransition,
  gamepads: typeof navigator.getGamepads,
  color_mix: CSS.supports('color', 'color-mix(in srgb, red, blue)'),
  backdrop: CSS.supports('backdrop-filter', 'blur(4px)'),
  font: getComputedStyle(document.body).fontFamily,
  fonts_used: document.fonts.size,
  size: [innerWidth, innerHeight],
})"""

# real covers come from Epic's servers, and the made-up library's are inline, so this is what proves they can load.
# GitHub's, as Epic's refuse scripts
REMOTE_IMAGE = """new Promise((done) => {
  const art = new Image();
  art.onload = () => done(`loaded, ${art.naturalWidth} px wide`);
  art.onerror = () => done('blocked or failed');
  setTimeout(() => done('nothing after 25 s'), 25000);
  art.src = 'https://github.githubassets.com/favicons/favicon.png';
})"""

# light, dark and busy art, long names, and games in every state, as bugs have come from each
LIBRARY = r"""(() => {
  window.__errors = [];
  addEventListener('error', (event) => __errors.push(event.message));
  addEventListener('unhandledrejection', (event) => __errors.push(String(event.reason)));
  const art = (hue, light, label, width, height) => 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="hsl(${hue},70%,${light}%)"/><stop offset="1" stop-color="hsl(${hue + 50},70%,${light / 2}%)"/></linearGradient></defs>
    <rect width="${width}" height="${height}" fill="url(#g)"/><circle cx="${width * .7}" cy="${height * .35}" r="${height * .28}" fill="hsl(${hue + 20},80%,70%)" opacity=".55"/>
    <text x="24" y="${height - 40}" font-family="sans-serif" font-size="34" font-weight="700" fill="white">${label}</text></svg>`);
  const names = ['Anemone Adventures', 'The Rivers Between Us and the Long Way Home', 'Kart', 'Stonefall', 'A Hat in Time',
    'Moonlighter', 'World of Goo', 'Fish Game', 'Battlefield Classic', 'Untitled Indie Game', 'Sundered: Eldritch Edition'];
  const lights = [52, 96, 12, 40, 85, 30];
  const now = Date.now(), day = 864e5;
  const games = Array.from({length: 66}, (_, i) => {
    const installed = i % 3 === 0, title = i < names.length ? names[i] : `${names[i % names.length]} ${i}`, hue = i * 37 % 360;
    return {app_name: `game${i}`, title, installed, update: i % 12 === 0, size: installed ? 3e9 + i * 7e8 : null,
      played: installed ? i * 3600 : 0, version: '1.4.2-CL-102938', store: i === 8 ? 'Origin' : null, cloud_saves: i % 2 === 0,
      cover: i % 11 === 9 ? '' : art(hue, lights[i % 6], title.split(' ')[0], 300, 400),
      art: i % 11 === 9 ? '' : art(hue, lights[i % 6], '', 1200, 500),
      last_played: installed ? new Date(now - i * day).toISOString() : null, dlcs: i % 5 === 0 ? 2 : 0, ubisoft: false,
      achievements: i % 4 === 0 ? {unlocked: i, total: 40} : null, developer: 'A Studio With a Name',
      added: new Date(now - i * 9 * day).toISOString(), about: i === 3 ? 'A game about stones, falling for a long time.' : null};
  });
  const real = pywebview.api.state;
  pywebview.api.state = async (have) => ({...(await real(have)), games, free_games: [], user: 'Player', refreshing: false, notice: '', revision: 1,
    jobs: [{id: 1, kind: 'install', app_name: 'game1', title: names[1], status: 'running', progress: 42.5, speed: '18.42 MiB/s', message: ''},
           {id: 2, kind: 'install', app_name: 'game2', title: names[2], status: 'queued', progress: null, speed: '', message: ''}]});
  state.revision = 0;
})()"""
SHOW_THEME = "(async () => { await showThemes(await pywebview.api.use_theme(%s)); colorMode = %s; applyMode(); scrollTo(0, 0); })()"
CLOSE = """for (const d of [...document.querySelectorAll('dialog[open]')].reverse()) d.close(); scrollTo(0, 0);"""
SCREENS = {
    'library': 'scrollTo(0, 0)',
    'scrolled': 'scrollTo(0, 1000)',
    'game': "openGame(state.games.find((g) => g.app_name === 'game3'))",
    'game-downloading': "openGame(state.games.find((g) => g.app_name === 'game1'))",
    'customize': "document.querySelector('#customize-open').click()",
    'settings': "document.querySelector('#settings-open').click()",
}


def page_socket(port: int, wait: float) -> str:
    deadline = time.monotonic() + wait
    while True:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list', timeout=5) as response:
                pages = [t for t in json.load(response) if t.get('type') == 'page' and 'index.html' in t.get('url', '')]
            if pages:
                return pages[0]['webSocketDebuggerUrl']
        except OSError:
            pass
        if time.monotonic() > deadline:
            raise SystemExit(f'No window on port {port} after {wait} s')
        time.sleep(1)


class Page:
    def __init__(self, url: str):
        self._socket = websocket.create_connection(url, timeout=60, suppress_origin=True)
        self._ids = itertools.count(1)

    def call(self, method: str, **params):
        sent = next(self._ids)
        self._socket.send(json.dumps({'id': sent, 'method': method, 'params': params}))
        while True:
            answer = json.loads(self._socket.recv())
            if answer.get('id') == sent:
                if 'error' in answer:
                    raise RuntimeError(f'{method}: {answer["error"]}')
                return answer['result']

    def evaluate(self, expression: str):
        result = self.call('Runtime.evaluate', expression=expression, awaitPromise=True, returnByValue=True)
        if 'exceptionDetails' in result:
            raise RuntimeError(f'{expression[:80]}: {result["exceptionDetails"]}')
        return result['result'].get('value')

    def screenshot(self, path: Path) -> None:
        path.write_bytes(base64.b64decode(self.call('Page.captureScreenshot', format='png')['data']))


def tour(page: Page, out: Path) -> list[str]:
    """Each screen in each theme and mode, at the window's usual size whatever the machine's screen; the page's errors"""
    audit = Path(__file__).with_name('window_audit.js').read_text(encoding='utf-8')
    page.call('Emulation.setDeviceMetricsOverride', width=1280, height=800, deviceScaleFactor=1, mobile=False)
    page.evaluate(LIBRARY)
    for _ in range(30):
        if page.evaluate('state.games.length') >= 60:
            break
        time.sleep(0.5)
    assert page.evaluate('state.games.length') >= 60, 'the page never took the made-up library'
    themes = page.evaluate('pywebview.api.themes().then((t) => t.themes.map((theme) => theme.name))')
    print('themes', themes)
    findings = {}
    for theme, mode in itertools.product(themes, ('dark', 'light')):
        page.evaluate(SHOW_THEME % (json.dumps(theme), json.dumps(mode)))
        time.sleep(1)
        for screen, show in SCREENS.items():
            page.evaluate(show)
            time.sleep(0.7)
            name = f'{theme}_{mode}_{screen}'
            page.screenshot(out / f'{name}.png')
            if issues := page.evaluate(f'({audit})()'):
                findings[name] = issues
            page.evaluate(CLOSE)
    (out / 'findings.json').write_text(json.dumps(findings, indent=1), encoding='utf-8')
    print(f'{len(findings)} screens with something to look at, of {len(themes) * 2 * len(SCREENS)}')
    return page.evaluate('__errors')


def main() -> None:
    page = Page(page_socket(int(sys.argv[1]), 120))
    features = {}
    for _ in range(60):
        # while still loading there is no <body> yet
        with contextlib.suppress(RuntimeError):
            features = page.evaluate(FEATURES)
        if features.get('api') and features.get('library'):
            break
        time.sleep(1)
    print(json.dumps(features, indent=1))
    remote_image = page.evaluate(REMOTE_IMAGE)
    print('A remote image in the page:', remote_image)
    assert remote_image.startswith('loaded'), 'covers from Epic would not show'
    if not features.get('library'):
        print('What the window shows:', page.evaluate('document.body?.innerText'))
        print('It went to:', [entry['url'] for entry in page.call('Page.getNavigationHistory')['entries']])
    assert features.get('api') and features.get('library'), 'the page never loaded, or pywebview.api never appeared'
    state = page.evaluate('pywebview.api.state(-1)')
    assert 'jobs' in state, 'the API answered without jobs'
    if len(sys.argv) > 2:
        out = Path(sys.argv[2])
        out.mkdir(parents=True, exist_ok=True)
        errors = tour(page, out)
        assert not errors, f'the page had errors: {errors}'


if __name__ == '__main__':
    main()
