import locale
import os
import sys


def is_pyinstaller():
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def is_windows_or_pyi():
    return is_pyinstaller() or os.name == 'nt'


def is_windows_mac_or_pyi():
    return is_pyinstaller() or os.name == 'nt' or sys.platform == 'darwin'


def get_system_locale() -> str | None:
    """
    The user's locale as "language_COUNTRY" (e.g. "en_US"), or None if unknown.

    Replaces locale.getdefaultlocale(), which is removed in Python 3.15, and matches what it returned.
    """
    if sys.platform == 'win32':
        import ctypes

        def locale_info(lctype: int) -> str:
            buf = ctypes.create_unicode_buffer(16)
            return buf.value if ctypes.windll.kernel32.GetLocaleInfoW(0x400, lctype, buf, len(buf)) else ''

        # LOCALE_USER_DEFAULT, LOCALE_SISO639LANGNAME / LOCALE_SISO3166CTRYNAME
        lang, country = locale_info(0x59), locale_info(0x5A)
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
