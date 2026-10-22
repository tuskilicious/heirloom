import configparser
import time
from pathlib import Path


class LGDConf(configparser.ConfigParser):
    def __init__(self, *args, **kwargs):
        self.modified = False
        self.read_only = False
        self.modtime: int | None = None
        super().__init__(*args, **kwargs)

    def optionxform(self, optionstr: str) -> str:
        return optionstr

    def read(self, filenames, encoding: str | None = None) -> list[str]:  # type: ignore[override]
        # if config file exists, save modification time
        if Path(filenames).exists():
            self.modtime = int(Path(filenames).stat().st_mtime)

        return super().read(filenames, encoding)

    def write(self, *args, **kwargs):
        self.modified = False
        super().write(*args, **kwargs)
        self.modtime = int(time.time())

    def set(self, section, option, value=None):
        if self.read_only:
            return

        # ensure config section exists
        if not self.has_section(section):
            self.add_section(section)

        self.modified = True
        super().set(section, option, value)

    def remove_option(self, section, option):
        if self.read_only:
            return False

        self.modified = True
        return super().remove_option(section, option)

    def __setitem__(self, key, value):
        if self.read_only:
            return

        self.modified = True
        super().__setitem__(key, value)
