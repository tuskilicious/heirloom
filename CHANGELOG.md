# Changelog

## Unreleased

### New
- **Manage a game from the window.** Each installed game has a Manage button (`⋯`): open its folder, add a desktop
  shortcut that plays it (Windows), verify and repair its files, sync its cloud saves, play without updating, or
  uninstall it.
- **A calmer library.** A game's buttons appear over its cover when you point at it or reach it with the keyboard,
  so the library reads as covers rather than rows of buttons. Updates and games being played are named in citron
  under their covers, and covers fade under the header as you scroll.

## 0.26.1 "Hearth" (2026-10-28)

Heirloom tidies up after installs, updates and uninstalls, and uninstalls games imported from the Epic Games Launcher properly.

### New
- **Less left behind.** After an install, update or uninstall, Heirloom removes the files it kept for game versions
  that are no longer installed, as `heirloom cleanup` does. Uninstalling a game says what is still in its folder
  (settings, saves and such the game made itself), so you can delete it if you don't need it.

### Fixed
- Uninstalling a game imported from the new Epic Games Launcher left its files behind when the launcher's version
  number differed from the one in the game's manifest.

## 0.26.0 "Hearth" (2026-10-28)

Heirloom brings over the games the Epic Games Launcher installed by itself, and tells you when a newer Heirloom is out.

### New
- **Heirloom tells you about new versions.** Once a day, when it logs in, Heirloom checks its latest release on
  GitHub. When a newer one is out, the window's sidebar links to its download page, and commands mention it when they
  finish, with the download for your platform (the installer on Windows). `disable_update_notice = true` hides it, and
  `disable_update_check = true` stops the check.
- **Games from the Epic Games Launcher come along by themselves.** Each time the window refreshes your library it adds
  the games the Epic Games Launcher installed that Heirloom doesn't have yet, as `egl-sync --import-only` does, and
  says which. `heirloom install` (and so Install in the window and the download queue) adds a game from there instead
  of downloading it again. No more downloading a game twice.

## 0.25.0 "Strongbox" (2026-10-28)

Playing a game through Heirloom now keeps its cloud saves in sync, as the Epic Games Launcher does.

### New
- **Cloud saves sync when you play.** `heirloom launch`, and so Play in the window, downloads a game's cloud save
  before it starts when that is newer, and uploads your save after the game exits when that is newer. The local files
  a download replaces are kept in `save-backups` in the config folder. `--no-sync-saves` or
  `disable_cloud_save_sync = true` turns it off. With `disable_playtime_tracking = true`, launches still wait for the
  game to exit to upload its save, unless save sync is off too.

## 0.24.0 "Lantern" (2026-10-28)

Heirloom gets a Windows installer, its own brand, and a new look for the window, where your games light up.

### New
- **Windows installer.** `heirloom_windows_x64_setup.exe` installs Heirloom for your user with a Start menu shortcut to
  the window, and optionally a desktop shortcut and the `heirloom` command on `PATH`. It updates and uninstalls cleanly
  and keeps your config folder. Opened from a shortcut, the window no longer comes with a terminal window.
- **The Heirloom brand.** The lantern app icon, and the brand's colours and logo in the window.
- **A new look for the window.** A sidebar for all, installed and updatable games, with counts. Games you haven't
  installed are shown without colour, and a download fills the cover with it as it goes. The game you played last is
  at the top with your time played and a Play button. Downloads and other tasks are listed in a corner with progress
  rings that stop a download when clicked. `/` jumps to the search.

## 0.23.0 "Locket" (2026-10-23)

Heirloom gets a window, a download queue for overnight installs and updates, and a Discord Rich Presence plugin.

### New
- **A window: `heirloom gui`.** Your library with cover art, search and filters, and Play, Install, Update and
  Uninstall buttons, with download progress and a Stop button. Each action runs as a regular `heirloom` command.
  Themes style it: the built-in ones have their own colours, and a theme's `gui_css` file can restyle the page.
- **Download queue.** `heirloom queue add <App Name>` (or `--updates` for every update) queues installs and updates,
  with any `install` options. `heirloom queue run` downloads them one after another, optionally only inside a daily time
  window (`--window 01:00-07:00` or `download_window` in the config). When the window closes, the current download stops
  as with CTRL-C and continues in the next window.
- **Discord Rich Presence plugin** in `plugins/discord-presence`. While a game started with `heirloom launch` runs,
  your Discord status shows it with the time played, using Heirloom's Discord application unless you set your own.
  Copy it into your plugins folder and enable it; see its README.

### Fixed
- A download that fails now makes `heirloom install` exit with an error instead of reporting success.

## 0.22.0 "Keepsake" (2026-10-22)

The first Heirloom release. Heirloom is a fork of [Legendary](https://github.com/derrod/legendary):
this release has everything in Legendary 0.21.1 "Lowlife", plus the changes below.

### Renamed to Heirloom
- The command is `heirloom`; `legendary` still works as an alias. The package is `heirloom-gl`, the Python module `heirloom`.
- On first run your Legendary config folder is copied to `~/.config/heirloom`, login and installed games included.
  Legendary's own folder is left untouched.
- `[Legendary]` sections in `config.ini` become `[Heirloom]` automatically.
- `HEIRLOOM_CONFIG_PATH` sets the config folder; `LEGENDARY_CONFIG_PATH` and `LEGENDARY_WRAPPER_EXE` still work.
- There is no update notice for now: the update feed Heirloom reads is still Legendary's, and says nothing about Heirloom releases.
  Its Epic launcher settings and game workarounds are still applied.

### New
- **Playtime tracking.** `heirloom launch` waits for the game to exit and records how long you played and whether the game exited normally or crashed.
  `heirloom playtime` shows the totals, `heirloom playtime <App Name>` the sessions of one game, `--json` for scripts.
  `--no-wait` or `disable_playtime_tracking = true` turns it off.
- **Plugins.** A plugin is a folder with a `plugin.json` manifest in the `plugins` folder of the config directory.
  Its Python code can react to the `game_launching`, `game_exited`, `game_installed` and `game_updated` events and add its own commands.
  `heirloom plugins` lists them, `heirloom plugins enable|disable <name>` switches them.
  A plugin that fails is logged and skipped; it never stops Heirloom.
- **Terminal themes.** Themes set the colours and symbols Heirloom prints with.
  `heirloom themes` previews them, `heirloom themes use <name>` switches.
  Built in: `default`, `modern`, `high-contrast` and `plain`. Add your own as JSON files in the `themes` folder, or ship them in a plugin.
  `NO_COLOR` and `FORCE_COLOR` are respected.
- **The new Epic Games Launcher.** `egl-sync` imports games installed with the 2026 launcher from its `installations.jsonl`.
  The file is found automatically on Windows; elsewhere use `--egl-installations <path>` or `egl_installations` in the config.
  This is import only: exporting to the new launcher isn't supported yet.
- **Download speed limits.** `install` (and `update`/`repair`) accept `--max-speed`, plus a lower `--max-speed-while-playing` that applies while a game started by `heirloom launch` is running.
  `max_download_speed` and `max_download_speed_while_playing` in the config apply them to every download.
- **Encrypted login.** Your Epic login tokens are no longer saved in plain text in `user.json`:
  - On Windows they are encrypted with DPAPI (`user.dpapi`), as the Epic Games Launcher does.
  - On macOS and Linux they go into the system keyring.
  - An existing login is moved there on first run.
  - Without a usable keyring they stay in `user.json` as before.

### Under the hood
- Paths use `pathlib` throughout, and the code has type hints checked with mypy for Linux, macOS and Windows.
- A pytest suite covers the CLI, downloads from a local test CDN, and the new features.
- CI runs ruff, mypy, and the tests on Linux, macOS and Windows with Python 3.10 and 3.14.
- The Windows and macOS executables are built with Python 3.14.
