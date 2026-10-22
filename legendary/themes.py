"""
Terminal themes: the colours and symbols legendary prints with.
Built-in themes live here; more come from <config>/themes/*.json and from enabled plugins.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, TextIO

ROLES = ('debug', 'info', 'warning', 'error', 'critical', 'logger', 'accent', 'muted')
SYMBOLS = ('bullet', 'alert')
RESET = '\x1b[0m'

_ATTRIBUTES = {'bold': 1, 'dim': 2, 'italic': 3, 'underline': 4}
_COLOURS = {name: i for i, name in enumerate(('black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white'))}

_DEFAULT: dict[str, Any] = {
    'name': 'default', 'common_name': 'Default', 'description': 'Coloured log levels with ASCII symbols',
    'colors': {'debug': 'dim', 'info': '', 'warning': 'yellow', 'error': 'red', 'critical': 'bold red',
               'logger': 'dim', 'accent': 'bold', 'muted': 'dim'},
    'symbols': {'bullet': '*', 'alert': '!'},
}
_BUILTIN: list[dict[str, Any]] = [
    _DEFAULT,
    {'name': 'modern', 'common_name': 'Modern', 'description': 'Bright colours with Unicode symbols',
     'colors': {'warning': 'bright_yellow', 'error': 'bright_red', 'critical': 'bold bright_white on red',
                'logger': 'blue', 'accent': 'bold bright_cyan', 'muted': 'bright_black'},
     'symbols': {'bullet': '•', 'alert': '▲'}},
    {'name': 'high-contrast', 'common_name': 'High Contrast', 'description': 'Bold, bright text for readability',
     'colors': {'debug': '', 'warning': 'bold bright_yellow', 'error': 'bold bright_red',
                'critical': 'bold bright_white on red', 'logger': 'bold bright_white',
                'accent': 'bold underline bright_white', 'muted': ''}},
    {'name': 'plain', 'common_name': 'Plain', 'description': 'No colours',
     'colors': dict.fromkeys(ROLES, '')},
]


def parse_style(spec: str) -> str:
    """Turns e.g. "bold #ff5555 on black" into an ANSI escape sequence ('' for no style)"""
    codes: list[str] = []
    tokens = spec.lower().split()
    while tokens:
        token = tokens.pop(0)
        background = token == 'on'
        if background:
            if not tokens:
                raise ValueError(f'"on" needs a colour in style "{spec}"')
            token = tokens.pop(0)
        if token in _ATTRIBUTES and not background:
            codes.append(str(_ATTRIBUTES[token]))
        elif (colour := token.removeprefix('bright_')) in _COLOURS:
            base = (40 if background else 30) + (60 if token.startswith('bright_') else 0)
            codes.append(str(base + _COLOURS[colour]))
        elif re.fullmatch(r'#[0-9a-f]{6}', token):
            r, g, b = (int(token[i:i + 2], 16) for i in (1, 3, 5))
            codes.append(f'{48 if background else 38};2;{r};{g};{b}')
        else:
            raise ValueError(f'unknown style "{token}" in "{spec}"')
    return f'\x1b[{";".join(codes)}m' if codes else ''


@dataclass(frozen=True)
class Theme:
    name: str
    common_name: str
    description: str
    styles: dict[str, str]
    symbols: dict[str, str]
    source: str = 'built-in'

    @classmethod
    def from_json(cls, data: dict[str, Any], source: str) -> Theme:
        name = data.get('name')
        if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', name):
            raise ValueError(f'"name" must be lowercase letters, digits, "-" and "_", got {name!r}')
        colors, symbols = data.get('colors', {}), data.get('symbols', {})
        if unknown := set(colors) - set(ROLES):
            raise ValueError(f'unknown colors {sorted(unknown)}, known: {", ".join(ROLES)}')
        if unknown := set(symbols) - set(SYMBOLS):
            raise ValueError(f'unknown symbols {sorted(unknown)}, known: {", ".join(SYMBOLS)}')
        if any(not isinstance(s, str) or not 0 < len(s) <= 3 for s in symbols.values()):
            raise ValueError('symbols must be 1 to 3 characters long')
        return cls(
            name=name, common_name=data.get('common_name') or name, description=data.get('description', ''),
            styles={role: parse_style(colors.get(role, _DEFAULT['colors'][role])) for role in ROLES},
            symbols={key: symbols.get(key, _DEFAULT['symbols'][key]) for key in SYMBOLS},
            source=source,
        )

    def paint(self, role: str, text: str) -> str:
        style = self.styles[role]
        return f'{style}{text}{RESET}' if style else text

    def bullet(self, title: str) -> str:
        """A list entry's symbol and highlighted title"""
        return f'{self.symbols["bullet"]} {self.paint("accent", title)}'

    def alert(self, text: str) -> str:
        """A problem shown under a list entry"""
        return self.paint('warning', f'{self.symbols["alert"]} {text}')

    def for_stream(self, stream: TextIO) -> Theme:
        """This theme, without colours unless the stream is a terminal that shows them"""
        return self if use_colors(stream) else replace(self, styles=dict.fromkeys(ROLES, ''))


BUILTIN_THEMES = {data['name']: Theme.from_json(data, 'built-in') for data in _BUILTIN}
DEFAULT_THEME = BUILTIN_THEMES['default']


def use_colors(stream: TextIO) -> bool:
    # https://no-color.org and the common FORCE_COLOR convention
    if os.environ.get('NO_COLOR'):
        return False
    if os.environ.get('FORCE_COLOR'):
        return True
    if not stream.isatty() or os.environ.get('TERM') == 'dumb':
        return False
    if sys.platform == 'win32':
        return _enable_windows_ansi(stream)
    return True


def _enable_windows_ansi(stream: TextIO) -> bool:
    if sys.platform == 'win32':
        import ctypes
        import msvcrt
        try:
            handle = msvcrt.get_osfhandle(stream.fileno())
            mode = ctypes.c_uint32()
            if not ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                return False
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            return bool(mode.value & 4 or ctypes.windll.kernel32.SetConsoleMode(handle, mode.value | 4))
        except (OSError, ValueError):
            return False
    return True


def load_themes(user_dir: Path, plugin_themes: list[tuple[str, Path]]) -> tuple[dict[str, Theme], dict[str, str]]:
    """All available themes by name, and why any theme file was skipped"""
    themes = dict(BUILTIN_THEMES)
    errors: dict[str, str] = {}
    candidates = [('user', path) for path in sorted(user_dir.glob('*.json'))]
    candidates += [(f'plugin "{plugin}"', path) for plugin, path in plugin_themes]
    for source, path in candidates:
        label = f'{path.name} ({source})'
        try:
            theme = Theme.from_json(json.loads(path.read_text(encoding='utf-8')), source)
        except Exception as e:
            errors[label] = str(e)
            continue
        if theme.name in themes:
            errors[label] = f'a theme named "{theme.name}" already exists ({themes[theme.name].source})'
            continue
        themes[theme.name] = theme
    return themes, errors


class ThemedFormatter(logging.Formatter):
    """Legendary's "[logger] LEVEL: message" log lines, coloured by level"""

    def __init__(self, theme: Theme):
        super().__init__('%(message)s')
        self.theme = theme

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        role = record.levelname.lower() if record.levelname.lower() in ROLES else 'info'
        return f'{self.theme.paint("logger", f"[{record.name}]")} ' \
               f'{self.theme.paint(role, f"{record.levelname}: {message}")}'
