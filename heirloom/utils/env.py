import locale
import os
import sys


def is_pyinstaller():
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def is_windows_mac_or_pyi():
    return is_pyinstaller() or os.name == 'nt' or sys.platform == 'darwin'


def windows_home_country() -> str:
    """The two letters of Windows' "Country or region" setting, or nothing if it has none or Windows is too old"""
    if sys.platform != 'win32':
        return ''
    import ctypes
    buf = ctypes.create_unicode_buffer(16)
    try:
        found = ctypes.windll.kernel32.GetUserDefaultGeoName(buf, len(buf))
    except AttributeError:
        return ''
    # it can also be a three-digit code of a region of the world
    return buf.value if found and buf.value.isalpha() and len(buf.value) == 2 else ''


def get_system_locale() -> str | None:
    """
    The user's locale as "language_COUNTRY" (e.g. "en_US"), or None if unknown. On Windows the country is where the
    user says they are, as the locale's own country is only how they like dates written: British dates in India would
    otherwise mean British prices and free games.

    Replaces locale.getdefaultlocale(), which is removed in Python 3.15.
    """
    if sys.platform == 'win32':
        import ctypes

        def locale_info(lctype: int) -> str:
            buf = ctypes.create_unicode_buffer(16)
            return buf.value if ctypes.windll.kernel32.GetLocaleInfoW(0x400, lctype, buf, len(buf)) else ''

        # LOCALE_USER_DEFAULT, LOCALE_SISO639LANGNAME / LOCALE_SISO3166CTRYNAME
        lang, country = locale_info(0x59), locale_info(0x5A)
        country = windows_home_country() or country
        return f'{lang}_{country}' if lang and country else None

    for variable in ('LANG', 'LANGUAGE', 'LC_ALL', 'LC_CTYPE'):
        if value := os.environ.get(variable):
            if variable == 'LANGUAGE':
                value = value.split(':')[0]
            break
    else:
        return None

    code = locale.normalize(value).partition('@')[0].partition('.')[0]
    return None if code in ('C', 'UTF-8') else code
