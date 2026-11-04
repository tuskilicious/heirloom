"""
Looks at the real packaged window, through Chromium's debugging port: run Heirloom with
QTWEBENGINE_REMOTE_DEBUGGING=<port> first. Exits non-zero unless the page and its API work.
    python tests/window_probe.py <port> <folder for screenshots>
"""
import base64
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
  size: [innerWidth, innerHeight],
})"""


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

    def _call(self, method: str, **params):
        sent = next(self._ids)
        self._socket.send(json.dumps({'id': sent, 'method': method, 'params': params}))
        while True:
            answer = json.loads(self._socket.recv())
            if answer.get('id') == sent:
                if 'error' in answer:
                    raise RuntimeError(f'{method}: {answer["error"]}')
                return answer['result']

    def evaluate(self, expression: str):
        result = self._call('Runtime.evaluate', expression=expression, awaitPromise=True, returnByValue=True)
        if 'exceptionDetails' in result:
            raise RuntimeError(f'{expression[:80]}: {result["exceptionDetails"]}')
        return result['result'].get('value')

    def screenshot(self, path: Path) -> None:
        path.write_bytes(base64.b64decode(self._call('Page.captureScreenshot', format='png')['data']))


def main() -> None:
    port, out = int(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    page = Page(page_socket(port, 120))
    for _ in range(60):
        features = page.evaluate(FEATURES)
        if features['api']:
            break
        time.sleep(1)
    print(json.dumps(features, indent=1))
    assert features['api'], 'pywebview.api never appeared'
    state = page.evaluate('pywebview.api.state(-1)')
    print('state keys', sorted(state)[:20])
    assert 'jobs' in state, 'the API answered without jobs'
    page.screenshot(out / 'first.png')


if __name__ == '__main__':
    main()
