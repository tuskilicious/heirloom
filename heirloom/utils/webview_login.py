import json
import logging
import os
import webbrowser

from heirloom import __version__

logger = logging.getLogger('WebViewHelper')
webview_available = True

try:
    import webview

    # silence logger
    webview.logger.setLevel(logging.FATAL)
    gui = webview.initialize()
    if gui and os.name == 'nt' and gui.renderer not in ('edgechromium', 'cef'):
        raise NotImplementedError(f'Renderer {gui.renderer} not supported on Windows.')
except Exception as e:
    if isinstance(e, ImportError) and e.name == 'webview':
        # pywebview is optional, not having it is no problem
        logger.debug(f'Webview unavailable, disabling webview login (Exception: {e!r}).')
    else:
        # installed but broken, e.g. a pythonnet too old for the running Python
        logger.warning(f'The login window could not start, using the browser login instead (Exception: {e!r}).')
    webview_available = False

login_url = 'https://www.epicgames.com/id/login'
sid_url = 'https://www.epicgames.com/id/api/redirect?'
logout_url = f'https://www.epicgames.com/id/logout?productName=epic-games&redirectUrl={login_url}'
goodbye_url = 'https://legendary.gl/goodbye'
window_js = '''
window.ue = {
    signinprompt: {
        requestexchangecodesignin: pywebview.api.set_exchange_code,
        registersignincompletecallback: pywebview.api.trigger_sid_exchange
    },
    common: {
        launchexternalurl: pywebview.api.open_url_external
    }
}
'''

get_sid_js = '''
function on_loaded() {
    pywebview.api.login_sid(this.responseText);
}

var sid_req = new XMLHttpRequest();
sid_req.addEventListener("load", on_loaded);
sid_req.open("GET", "/id/api/redirect?");
sid_req.send();
'''


class MockLauncher:
    # pywebview exposes this object's public attributes to the page and walks into the objects they hold,
    # so the window and callbacks are private: walking the window touches WebView2 off the UI thread,
    # which froze the login window
    def __init__(self, callback_sid, callback_code):
        self._callback_sid = callback_sid
        self._callback_code = callback_code
        self._window = None
        self.inject_js = True
        self.destroy_on_load = False
        self.callback_result = None

    def on_loaded(self):
        url = self._window.get_current_url()
        logger.debug(f'Loaded url: {url.partition("?")[0]}')

        if self.destroy_on_load:
            logger.info('Closing login window...')
            self._window.destroy()
            return

        # Inject JS so required window.ue stuff is available
        if self.inject_js:
            self._window.evaluate_js(window_js)

        if 'logout' in url and self._callback_sid:
            # prepare to close browser after logout redirect
            self.destroy_on_load = True
        elif 'logout' in url:
            self.inject_js = True

    def nop(self, *args, **kwargs):
        return

    def open_url_external(self, url):
        webbrowser.open(url)

    def set_exchange_code(self, exchange_code, param):
        if param:
            logger.warning(f'Unknown parameter provided: {param}. Please report it on GitHub')
        self.inject_js = False
        logger.debug('Got exchange code (stage 1)!')
        # The default Windows webview retains cookies, GTK/Qt do not. Therefore we can
        # skip logging out on those platforms and directly use the exchange code we're given.
        # On windows we have to do a little dance with the SID to create a session that
        # remains valid after logging out in the embedded browser.
        #  Update: Epic broke SID login, we'll also do this on Windows now
        # if self._window.gui.renderer in ('gtkwebkit2', 'qtwebengine', 'qtwebkit'):
        self.destroy_on_load = True
        try:
            self.callback_result = self._callback_code(exchange_code)
        except Exception as e:
            logger.error(f'Logging in via exchange-code failed with {e!r}')
        finally:
            # We cannot destroy the browser from here,
            # so we'll load a small goodbye site first.
            self._window.load_url(goodbye_url)

    def trigger_sid_exchange(self, *args, **kwargs):
        # check if code-based login hasn't already set the destroy flag
        if not self.destroy_on_load:
            logger.debug('Injecting SID JS')
            # inject JS to get SID API response and call our API
            self._window.evaluate_js(get_sid_js)

    def login_sid(self, sid_json):
        # Try SID login, then log out
        try:
            j = json.loads(sid_json)
            sid = j['sid']
            logger.debug('Got SID (stage 2)! Executing sid login callback...')
            exchange_code = self._callback_sid(sid)
            if exchange_code:
                self.callback_result = self._callback_code(exchange_code)
        except Exception as e:
            logger.error(f'SID login failed with {e!r}')
        finally:
            logger.debug('Starting browser logout...')
            self._window.load_url(logout_url)


def do_webview_login(callback_sid=None, callback_code=None, user_agent=None):
    api = MockLauncher(callback_sid=callback_sid, callback_code=callback_code)
    url = login_url

    if os.name == 'nt':
        # On Windows we open the logout URL first to invalidate the current cookies (if any).
        # Additionally, we have to disable JS injection for the first load, as otherwise the user
        # will get an error for some reason.
        url = logout_url
        api.inject_js = False

    logger.info('Opening Epic Games login window...')
    # Open logout URL first to remove existing cookies, then redirect to login.
    window = webview.create_window(f'Heirloom {__version__} - Epic Games Account Login',
                                   url=url, width=768, height=1024, js_api=api)
    api._window = window
    window.events.loaded += api.on_loaded

    try:
        webview.start(user_agent=user_agent)
    except Exception as we:
        logger.error(f'Running webview failed with {we!r}. If this error persists try the manual '
                     f'login process by adding --disable-webview to your command line.')
        return None

    if api.callback_result is None:
        logger.error('Login aborted by user.')

    return api.callback_result
