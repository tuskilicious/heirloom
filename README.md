<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/heirloom-horizontal-citron.svg">
    <img src="assets/brand/heirloom-horizontal-evergreen.svg" alt="Heirloom" width="300">
  </picture>
</h1>
## A free and open-source Epic Games Launcher alternative

Heirloom is an open-source game launcher that can download and install games from the Epic Games platform on Linux, macOS, and Windows.
Like Legendary, its name is a tongue-in-cheek play on tiers of [item rarity in many MMORPGs](https://wow.gamepedia.com/Quality).

Heirloom is a fork of [Legendary](https://github.com/derrod/legendary) by derrod and its contributors, under the same GPL-3.0 license.
It adds playtime tracking, plugins, terminal themes, download speed limits, encrypted login storage, and support for the new Epic Games Launcher; see the [changelog](CHANGELOG.md).
If you find it useful, consider [supporting Legendary's author](https://ko-fi.com/derrod), whose work it is built on.

Please read the [config file](#config-file) and [cli usage](#usage) sections before creating an issue to avoid invalid reports.
Report problems with Heirloom [on its GitHub](https://github.com/tuskilicious/heirloom/issues), not to the Legendary project.

**Note:** Heirloom is mainly a CLI (command-line interface) application, run from a terminal (e.g. PowerShell).
`heirloom gui` opens a window for your library, installs, updates and playing.

**Features:**
 - Authenticating with Epic's service
 - Downloading and installing your games and their DLC
 - Delta patching/updating of installed games
 - Launching games with online authentication (for multiplayer/DRM)
 - Syncing cloud saves (compatible with EGL)
 - Running games with WINE on Linux/macOS
 - Importing/Exporting installed games from/to the Epic Games Launcher (unsupported for macOS version of EGL)

**Planned:**
 - More of the CLI in the window (download queue, settings)
 - Lots and lots of bug fixes, optimizations, and refactoring...

## Requirements

- Linux, Windows (8.1+), or macOS (12.0+)
  + 32-bit operating systems are not supported
- python 3.10+ (64-bit)
  + (Windows) `pythonnet` is not yet compatible with 3.14+
- PyPI packages:
  + `requests`
  + (optional) `pywebview` for webview-based login
  + (optional) `uv` for setup/building

**Note:** Running Windows applications on Linux or macOS requires [Wine](https://www.winehq.org/).

## How to run/install

Prebuilt executables for Windows, macOS, and Linux are on the [releases page](https://github.com/tuskilicious/heirloom/releases/latest).
Heirloom is not on PyPI or in Linux package managers yet; to run it with your own Python, install it from this repository.

### Windows installer

Download `heirloom_windows_x64_setup.exe` from the [releases page](https://github.com/tuskilicious/heirloom/releases/latest) and run it.
It installs Heirloom for your user (no administrator rights needed) and adds a Start menu shortcut that opens the window (`heirloom gui`).
It can also add a desktop shortcut and add Heirloom to `PATH`, so the `heirloom` command works in a terminal.
Running a newer installer updates Heirloom; uninstalling it (Settings > Apps) keeps your config folder, with your login and game list.
When a newer Heirloom is out, the window's sidebar links to it and commands that log in mention it when they finish (checked once a day).
Windows may warn about an unrecognized app the first time, because the installer isn't code-signed: choose "More info" and "Run anyway".

### With pip

```bash
pip install "heirloom-gl @ git+https://github.com/tuskilicious/heirloom"
```

Optionally, for logging in through an embedded web view:
```bash
pip install "heirloom-gl[webview] @ git+https://github.com/tuskilicious/heirloom"
```
On Linux this may also require a supported web engine and its Python bindings (on Ubuntu: `sudo apt install python3-gi-cairo`).
Using pywebview's Qt engine may not work correctly, and pywebview is currently unsupported on macOS.

### With uv, from a clone

`uv` has various methods of installation. See <https://docs.astral.sh/uv/getting-started/installation/> and choose one.

````bash
git clone https://github.com/tuskilicious/heirloom.git
cd heirloom
uv sync --no-editable
````

### Coming from Legendary

- The command is now `heirloom`; `legendary` still works as an alias.
- On first run Heirloom copies your Legendary config folder (`~/.config/legendary`) to `~/.config/heirloom`, including your login and installed games.
  Legendary's own folder is left untouched. If you keep using both, you may have to log in again in one of them, since Epic replaces the login token on use.
- The `[Legendary]` config sections become `[Heirloom]` automatically.
- `HEIRLOOM_CONFIG_PATH` sets the config folder; `LEGENDARY_CONFIG_PATH` still works too.

If the `heirloom` executable is not available after installation, you may need to configure your `PATH` correctly. You can do this by running the command: 

```bash
echo 'export PATH=$PATH:~/.local/bin' >> ~/.profile && source ~/.profile
```

### Directly from the repo (for dev/testing)

- Install uv
- cd into the repository
- Run `uv sync`

This installs `heirloom` in "editable" mode - any changes to the source code will take effect next time the `heirloom` executable runs.

Before opening a pull request, run the same checks as CI:

```
uv run ruff check
uv run mypy
uv run pytest
```

## Quickstart

**Tip:** When using PowerShell with the standalone executable, you may need to replace `heirloom` with `.\heirloom` in the commands below.

To log in:
````
heirloom auth
````
When using the prebuilt Windows executables of version 0.20.14 or higher this should open a new window with the Epic Login.

Otherwise, authentication is a little finicky since we have to go through the Epic website and manually copy a code.
The login page should open in your browser and after logging in you should be presented with a JSON response that contains a code ("authorizationCode"), just copy the code into the terminal and hit enter.

Alternatively you can use the `--import` flag to import the authentication from the Epic Games Launcher (manually specifying the used WINE prefix may be required on Linux).
Note that this will log you out of the Epic Launcher.

Your login tokens are not saved in plain text: on Windows they are encrypted for your user account with DPAPI (in `user.dpapi`, like the Epic Games Launcher does), on macOS and Linux they go into the system keyring (Keychain, or GNOME Keyring/KWallet through Secret Service).
A login saved by an older version is moved there the next time Heirloom runs.
Without a usable keyring, for example on a headless machine, they stay in `user.json` as before; `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring` does that on purpose.

Open the window: your library with cover art, and Play, Install and Update buttons over each cover
````
heirloom gui
````
It needs pywebview, which the prebuilt Windows executable includes (install the `webview` extra otherwise; on Linux this also needs GTK WebKit, and macOS is untested).
The sidebar switches between all your games, the installed ones and the ones with an update, and the sort button orders them A to Z, by when you last played, by playtime or by size; the window opens on the shelf, order and sidebar you left it with.
`/` jumps to the search, which ignores case, spaces and punctuation ("hitman3" finds HITMAN 3), and Escape empties it. Double-click an installed game to play it, and right-click it for its Manage menu.
Installed games are in colour and the others are not; a download assembles its game's cover tile by tile, sharpening from a blur as it goes.
The game you played last is at the top with your time played, ready to continue.
On Windows, Customize in the sidebar also installs the Epic overlay, which games using Epic Online Services show friends, invites and achievements in, turns it on and off for every game, updates and removes it (as `heirloom eos-overlay` does).
Each installed game's Manage button (`⋯`) opens its folder, adds a desktop shortcut that plays it (Windows), verifies and repairs its files, syncs its cloud saves and uninstalls it.
Everything it does runs as a regular `heirloom` command, so playtime, plugins and resumable downloads work the same.
Downloads run one at a time; Stop stops one cleanly, and installing it again continues where it stopped.
On Windows, closing the window keeps Heirloom going in the tray, downloads and updates included: double-click its icon to bring the window back, or choose Quit in its menu. Opening Heirloom again brings back the window already open. Settings can start it with Windows, in the tray (`heirloom gui --background` starts it that way by hand).
Settings in the sidebar also chooses where games are installed, the download speed limits (and a lower one while you play), and turns automatic updates, cloud save sync and the notice about new Heirloom versions on and off; they are the same options as in the config file, saved as soon as they change.
Game updates install by themselves: each time Heirloom refreshes your library (when it opens, then every hour), it starts the updates of installed games, except games being played and updates you stopped or that failed since the window opened, which wait for their Update button. Set `disable_auto_updates = true` to update only when you choose.
Without a login, games are launched offline. The window has its own look, and can use your own CSS, see [Window themes](#window-themes).

Listing your games
````
heirloom list
````
This will fetch a list of games available on your account, the first time may take a while depending on how many games you have.

Installing a game
````
heirloom install Anemone
````
**Note:** the name used here is generally the game's "app name" as seen in the games list rather than its title, but as of 0.20.12 heirloom will try to match game names or abbreviations thereof as well. In this case `heirloom install world of goo` or `heirloom install wog` would also work!

Limit the download speed, and slow it down further while you play a game started with `heirloom launch`
````
heirloom install Anemone --max-speed 20M --max-speed-while-playing 2M
````
Speeds are in MiB/s by default (`20` and `20M` are the same), `K` and `G` suffixes are also accepted.
Set `max_download_speed` and `max_download_speed_while_playing` in the config to apply them to every download.
The lower limit kicks in within a couple of seconds of a game starting, and only for games that `heirloom launch` waits for (not with `--no-wait`).

Queue installs and updates to download later, e.g. overnight
````
heirloom queue add Anemone
heirloom queue add --updates
heirloom queue run --window 01:00-07:00
````
`queue add` takes the same options as `install` (e.g. `--platform Mac` or `--max-speed 5M`); `--updates` queues every installed game that has an update.
`queue run` downloads the queued games one after another, each as its own `heirloom install`, and only inside the time window, which may cross midnight (e.g. `23:00-07:00`).
When the window closes, the current download stops as it would with CTRL-C and continues where it stopped once the window opens again; downloads that fail stay queued.
Leave `queue run` running, or start it from Task Scheduler or cron. Set `download_window` in the config to use a window without `--window`.
`heirloom queue` shows the queue, `queue remove <App Name>` and `queue clear` change it.
Games that ask which optional parts to install (selective downloads) can't ask while queued: install them once yourself, or pass `--install-tag` or `--skip-sdl` when queueing.

List installed games and check for updates
````
heirloom list-installed --check-updates
````

Launch (run) a game with online authentication
````
heirloom launch "world of goo"
````
**Tip:** most games will run fine offline (`--offline`), and thus won't require launching through heirloom for online authentication.
You can run `heirloom launch <App Name> --offline --dry-run` to get a command line that will launch the game with all parameters that would be used by the Epic Launcher.
These can then be entered into any other game launcher (e.g. Lutris/Steam) if the game requires them.

`heirloom launch` waits for the game to exit and records how long you played, and whether the game exited normally or crashed.
Use `--no-wait` to return immediately instead, or set `disable_playtime_tracking = true` in the config to turn this off.

It also keeps cloud saves in sync, for games that have them: before the game starts it downloads the cloud save if that is newer, and after the game exits it uploads your save if that is newer.
The local files a download replaces are kept in the `save-backups` folder of the config folder, in case they were the ones to keep.
This needs a login, so offline launches don't sync, and `--no-wait` launches only download.
Use `--no-sync-saves` to skip it once, or set `disable_cloud_save_sync = true` in the config to turn it off.
The first time, the save folder is worked out from the game's information and remembered; when that isn't possible, `heirloom sync-saves <App Name>` asks for it once.

Show recorded playtime (add an app name to also list its individual sessions)
````
heirloom playtime
````

Importing a previously installed game
````
heirloom import Anemone /mnt/games/Epic/WorldOfGoo
````
**Note:** Importing will require a full verification so Heirloom can correctly update the game later.  
**Note 2:** In order to use an alias here you may have to put it into quotes if if contains more than one word, e.g. `heirloom import-game "world of goo" /mnt/games/Epic/WorldOfGoo`.

Sync savegames with the Epic Cloud
````
heirloom sync-saves
````
**Note:** When this command is run the first time after a supported game has been installed it will ask you to confirm or provide the path to where the savegame is located.

Automatically sync all games with the Epic Games Launcher
````
heirloom -y egl-sync
````
You rarely need to run this to bring games over: games the Epic Games Launcher installed are added by themselves, each time the window refreshes your library, and `heirloom install` adds a game from there instead of downloading it again.
**Note:** With the new Epic Games Launcher (the 2026 rewrite, whose data lives in `%LOCALAPPDATA%\com.epicgames.eglv2`), `egl-sync` can only *import*:
it reads the launcher's `installations.jsonl` and adds games installed there that Heirloom doesn't have yet; games already in Heirloom are left as they are.
Exporting games to it, removing games from it, and automatic sync are not supported yet, so run `egl-sync` again to import games you install there later.
On Windows the file is found automatically once the old launcher's `ProgramData` manifests are gone; elsewhere (e.g. in a WINE prefix) pass it with `--egl-installations <path>`.

## Usage

````
usage: heirloom [-h] [-H] [-v] [-y] [-V] [-J] [-A <seconds>] <command> ...

Heirloom v0.X.X - "Codename"

optional arguments:
  -h, --help            show this help message and exit
  -H, --full-help       Show full help (including individual command help)
  -v, --debug           Set loglevel to debug
  -y, --yes             Default to yes for all prompts
  -V, --version         Print version and exit
  -J, --pretty-json     Pretty-print JSON
  -A <seconds>, --api-timeout <seconds>
                        API HTTP request timeout (default: 10 seconds)

Commands:
  <command>
    activate            Activate games on third party launchers
    alias               Manage aliases
    auth                Authenticate with the Epic Games Store
    clean-saves         Clean cloud saves
    cleanup             Remove old temporary, metadata, and manifest files
    crossover           Setup CrossOver for launching games (macOS only)
    download-saves      Download all cloud saves
    egl-sync            Setup or run Epic Games Launcher sync
    eos-overlay         Manage EOS Overlay install
    gui                 Open the Heirloom window: your library, installs,
                        updates and playing
    import              Import an already installed game
    info                Prints info about specified app name or manifest
    install (download, update, repair)
                        Install/download/update/repair a game
    launch              Launch a game
    list                List available (installable) games
    list-files          List files in manifest
    list-installed      List installed games
    list-saves          List available cloud saves
    move                Move specified app name to a new location
    playtime            Show playtime recorded by "heirloom launch"
    plugins             List, enable, or disable plugins
    queue               Queue installs and updates to run later, e.g.
                        overnight
    themes              List terminal themes or switch to one
    status              Show heirloom status information
    sync-saves          Sync cloud saves
    uninstall           Uninstall (delete) a game
    verify              Verify a game's local files

Individual command help:

Command: activate
usage: heirloom activate [-h] (-U | -O)

optional arguments:
  -h, --help    show this help message and exit
  -U, --uplay   Activate Uplay/Ubisoft Connect titles on your Ubisoft account
                (Uplay install not required)
  -O, --origin  Activate Origin/EA App managed titles on your EA account
                (requires Origin to be installed)


Command: alias
usage: heirloom alias [-h]
                       <add|rename|remove|list> [<App name/Old alias>]
                       [<New alias>]

positional arguments:
  <add|rename|remove|list>
                        Action: Add, rename, remove, or list alias(es)
  <App name/Old alias>  App name when using "add" or "list" action, existing
                        alias when using "rename" or "remove" action
  <New alias>           New alias when using "add" action

optional arguments:
  -h, --help            show this help message and exit


Command: auth
usage: heirloom auth [-h] [--import] [--code <exchange code>]
                      [--sid <session id>] [--delete] [--disable-webview]

optional arguments:
  -h, --help            show this help message and exit
  --import              Import Epic Games Launcher authentication data (logs
                        out of EGL)
  --code <authorization code>
                        Use specified authorization code instead of interactive authentication
  --token <exchange token>
                        Use specified exchange token instead of interactive authentication
  --sid <session id>    Use specified session id instead of interactive
                        authentication
  --delete              Remove existing authentication (log out)
  --disable-webview     Do not use embedded browser for login


Command: clean-saves
usage: heirloom clean-saves [-h] [--delete-incomplete] [<App Name>]

positional arguments:
  <App Name>           Name of the app (optional)

optional arguments:
  -h, --help           show this help message and exit
  --delete-incomplete  Delete incomplete save files


Command: cleanup
usage: heirloom cleanup [-h] [--keep-manifests]

optional arguments:
  -h, --help        show this help message and exit
  --keep-manifests  Do not delete old manifests


Command: crossover
usage: heirloom crossover [-h] [--reset] [--download] [--ignore-version]
                           [--crossover-app <path to .app>]
                           [--crossover-bottle <bottle name>]
                           [<App Name>]

positional arguments:
  <App Name>            App name to configure, will configure defaults if
                        ommited

optional arguments:
  -h, --help            show this help message and exit
  --reset               Reset default/app-specific crossover configuration
  --download            Automatically download and set up a preconfigured
                        bottle (experimental)
  --ignore-version      Disable version check for available bottles when using
                        --download
  --crossover-app <path to .app>
                        Specify app to skip interactive selection
  --crossover-bottle <bottle name>
                        Specify bottle to skip interactive selection


Command: download-saves
usage: heirloom download-saves [-h] [<App Name>]

positional arguments:
  <App Name>  Name of the app (optional)

optional arguments:
  -h, --help  show this help message and exit


Command: egl-sync
usage: heirloom egl-sync [-h] [--egl-manifest-path EGL_MANIFEST_PATH]
                          [--egl-wine-prefix EGL_WINE_PREFIX]
                          [--egl-installations <path>] [--enable-sync]
                          [--disable-sync] [--one-shot] [--import-only]
                          [--export-only] [--migrate] [--unlink]

optional arguments:
  -h, --help            show this help message and exit
  --egl-manifest-path EGL_MANIFEST_PATH
                        Path to the Epic Games Launcher's Manifests folder,
                        should point to
                        /ProgramData/Epic/EpicGamesLauncher/Data/Manifests
  --egl-wine-prefix EGL_WINE_PREFIX
                        Path to the WINE prefix the Epic Games Launcher is
                        installed in
  --egl-installations <path>
                        Path to the new Epic Games Launcher's
                        installations.jsonl, if it is not found automatically
                        (e.g. in a WINE prefix)
  --enable-sync         Enable automatic EGL <-> Heirloom sync
  --disable-sync        Disable automatic sync and exit
  --one-shot            Sync once, do not ask to setup automatic sync
  --import-only         Only import games from EGL (no export)
  --export-only         Only export games to EGL (no import)
  --migrate             Import games into heirloom, then remove them from EGL
                        (implies --import-only --one-shot --unlink)
  --unlink              Disable sync and remove EGL metadata from installed
                        games


Command: eos-overlay
usage: heirloom eos-overlay [-h] [--path PATH] [--prefix PREFIX] [--app APP]
                             [--bottle BOTTLE]
                             <install|update|remove|enable|disable|info>

positional arguments:
  <install|update|remove|enable|disable|info>
                        Action: install, remove, enable, disable, or print
                        info about the overlay

optional arguments:
  -h, --help            show this help message and exit
  --path PATH           Path to the EOS overlay folder to be enabled/installed
                        to.
  --prefix PREFIX       WINE prefix to install the overlay in
  --app APP             Use this app's wine prefix (if configured in config)
  --bottle BOTTLE       WINE prefix to install the overlay in


Command: import
usage: heirloom import [-h] [--disable-check] [--with-dlcs] [--skip-dlcs]
                        [--platform <Platform>]
                        <App Name> <Installation directory>

positional arguments:
  <App Name>            Name of the app
  <Installation directory>
                        Path where the game is installed

optional arguments:
  -h, --help            show this help message and exit
  --disable-check       Disables completeness check of the to-be-imported game
                        installation (useful if the imported game is a much
                        older version or missing files)
  --with-dlcs           Automatically attempt to import all DLCs with the base
                        game
  --skip-dlcs           Do not ask about importing DLCs.
  --platform <Platform>
                        Platform for import (default: Mac on macOS, otherwise
                        Windows)


Command: info
usage: heirloom info [-h] [--offline] [--json] [--platform <Platform>]
                      <App Name/Manifest URI>

positional arguments:
  <App Name/Manifest URI>
                        App name or manifest path/URI

optional arguments:
  -h, --help            show this help message and exit
  --offline             Only print info available offline
  --json                Output information in JSON format
  --platform <Platform>
                        Platform to fetch info for (default: installed or Mac
                        on macOS, Windows otherwise)


Command: install
usage: heirloom install <App Name> [options]

Aliases: download, update

positional arguments:
  <App Name>            Name of the app

optional arguments:
  -h, --help            show this help message and exit
  --base-path <path>    Path for game installations (defaults to ~/Games)
  --game-folder <path>  Folder for game installation (defaults to folder
                        specified in metadata)
  --max-shared-memory <size>
                        Maximum amount of shared memory to use (in MiB),
                        default: 1 GiB
  --max-workers <num>   Maximum amount of download workers, default: min(2 *
                        CPUs, 16)
  --max-speed <speed>   Limit the download speed, e.g. "5" or "5M" for 5
                        MiB/s, "500K" for 500 KiB/s, 0 for no limit (default:
                        max_download_speed from the config)
  --max-speed-while-playing <speed>
                        Lower download speed limit while a game started by
                        "heirloom launch" is running (default:
                        max_download_speed_while_playing from the config)
  --manifest <uri>      Manifest URL or path to use instead of the CDN one
                        (e.g. for downgrading)
  --old-manifest <uri>  Manifest URL or path to use as the old one (e.g. for
                        testing patching)
  --delta-manifest <uri>
                        Manifest URL or path to use as the delta one (e.g. for
                        testing)
  --base-url <url>      Base URL to download from (e.g. to test or switch to a
                        different CDNs)
  --force               Download all files / ignore existing (overwrite)
  --disable-patching    Do not attempt to patch existing installation
                        (download entire changed files)
  --download-only, --no-install
                        Do not install app and do not run prerequisite
                        installers after download
  --update-only         Only update, do not do anything if specified app is
                        not installed
  --dlm-debug           Set download manager and worker processes' loglevel to
                        debug
  --platform <Platform>
                        Platform for install (default: installed or Windows)
  --prefix <prefix>     Only fetch files whose path starts with <prefix> (case
                        insensitive)
  --exclude <prefix>    Exclude files starting with <prefix> (case
                        insensitive)
  --install-tag <tag>   Only download files with the specified install tag
  --enable-reordering   Enable reordering optimization to reduce RAM
                        requirements during download (may have adverse results
                        for some titles)
  --dl-timeout <sec>    Connection timeout for downloader (default: 10
                        seconds)
  --save-path <path>    Set save game path to be used for sync-saves
  --repair              Repair installed game by checking and redownloading
                        corrupted/missing files
  --repair-and-update   Update game to the latest version when repairing
  --ignore-free-space   Do not abort if not enough free space is available
  --disable-delta-manifests
                        Do not use delta manifests when updating (may increase
                        download size)
  --reset-sdl           Reset selective downloading choices (requires repair
                        to download new components)
  --skip-sdl            Skip SDL prompt and continue with defaults (only
                        required game data)
  --disable-sdl         Disable selective downloading for title, reset
                        existing configuration (if any)
  --preferred-cdn <hostname>
                        Set the hostname of the preferred CDN to use when
                        available
  --no-https            Download games via plaintext HTTP (like EGS), e.g. for
                        use with a lan cache
  --with-dlcs           Automatically install all DLCs with the base game
  --skip-dlcs           Do not ask about installing DLCs.


Command: launch
usage: heirloom launch <App Name> [options]

Note: additional arguments are passed to the game

positional arguments:
  <App Name>            Name of the app

optional arguments:
  -h, --help            show this help message and exit
  --offline             Skip login and launch game without online
                        authentication
  --skip-version-check  Skip version check when launching game in online mode
  --override-username <username>
                        Override username used when launching the game (only
                        works with some titles)
  --dry-run             Print the command line that would have been used to
                        launch the game and exit
  --no-wait             Return right after starting the game instead of
                        waiting for it to exit (playtime will not be recorded,
                        and saves not uploaded)
  --no-sync-saves       Do not download a newer cloud save before the game
                        starts, or upload a newer local save after it exits
  --language <two letter language code>
                        Override language for game launch (defaults to system
                        locale)
  --wrapper <wrapper command>
                        Wrapper command to launch game with
  --set-defaults        Save parameters used to launch to config (does not
                        include env vars)
  --reset-defaults      Reset config settings for app and exit
  --override-exe <exe path>
                        Override executable to launch (relative path)
  --origin              Launch Origin to activate or run the game.
  --json                Print launch information as JSON and exit
  --wine <wine binary>  Set WINE binary to use to launch the app
  --wine-prefix <wine pfx path>
                        Set WINE prefix to use
  --no-wine             Do not run game with WINE (e.g. if a wrapper is used)
  --crossover           Interactively configure CrossOver for this
                        application.
  --crossover-app <path to .app>
                        Specify which App to use for CrossOver (e.g.
                        "/Applications/CrossOver.app")
  --crossover-bottle <bottle name>
                        Specify which bottle to use for CrossOver


Command: list
usage: heirloom list [-h] [--platform <Platform>] [--include-ue] [-T] [--csv]
                      [--tsv] [--json] [--force-refresh]

optional arguments:
  -h, --help            show this help message and exit
  --platform <Platform>
                        Platform to fetch game list for (default: Mac on
                        macOS, otherwise Windows)
  --include-ue          Also include Unreal Engine content
                        (Engine/Marketplace) in list
  -T, --third-party, --include-non-installable
                        Include apps that are not installable (e.g. that have
                        to be activated on Origin)
  --csv                 List games in CSV format
  --tsv                 List games in TSV format
  --json                List games in JSON format
  --force-refresh       Force a refresh of all game metadata


Command: list-files
usage: heirloom list-files [-h] [--force-download] [--platform <Platform>]
                            [--manifest <uri>] [--csv] [--tsv] [--json]
                            [--hashlist] [--install-tag <tag>]
                            [<App Name>]

positional arguments:
  <App Name>            Name of the app (optional)

optional arguments:
  -h, --help            show this help message and exit
  --force-download      Always download instead of using on-disk manifest
  --platform <Platform>
                        Platform (default: Mac on macOS, otherwise Windows)
  --manifest <uri>      Manifest URL or path to use instead of the CDN one
  --csv                 Output in CSV format
  --tsv                 Output in TSV format
  --json                Output in JSON format
  --hashlist            Output file hash list in hashcheck/sha1sum -c
                        compatible format
  --install-tag <tag>   Show only files with specified install tag


Command: list-installed
usage: heirloom list-installed [-h] [--check-updates] [--csv] [--tsv]
                                [--json] [--show-dirs]

optional arguments:
  -h, --help       show this help message and exit
  --check-updates  Check for updates for installed games
  --csv            List games in CSV format
  --tsv            List games in TSV format
  --json           List games in JSON format
  --show-dirs      Print installation directory in output


Command: list-saves
usage: heirloom list-saves [-h] [<App Name>]

positional arguments:
  <App Name>  Name of the app (optional)

optional arguments:
  -h, --help  show this help message and exit


Command: move
usage: heirloom move [-h] [--skip-move] <App Name> <New Base Path>

positional arguments:
  <App Name>       Name of the app
  <New Base Path>  Directory to move game folder to

optional arguments:
  -h, --help       show this help message and exit
  --skip-move      Only change heirloom database, do not move files (e.g. if
                   already moved)


Command: playtime
usage: heirloom playtime [-h] [--json] [<App Name>]

positional arguments:
  <App Name>  Only show this app, including its individual sessions

optional arguments:
  -h, --help  show this help message and exit
  --json      Output information in JSON format


Command: plugins
usage: heirloom plugins [-h] [{list,enable,disable}] [<name>]

positional arguments:
  {list,enable,disable}
                        What to do (default: list)
  <name>                Plugin to enable or disable

optional arguments:
  -h, --help            show this help message and exit


Command: queue
usage: heirloom queue [list|add|remove|clear|run] [<App Name> ...] [options]

"add" also takes "heirloom install" options for the queued downloads, e.g.
"heirloom queue add Anemone --platform Mac"

positional arguments:
  {list,add,remove,clear,run}
                        What to do (default: list)
  <App Name>            Games to add or remove

optional arguments:
  -h, --help            show this help message and exit
  --updates             With "add": queue every installed game that has an
                        update
  --window <HH:MM-HH:MM>
                        With "run": only download in this daily time window,
                        e.g. "01:00-07:00" (default: download_window from the
                        config, otherwise any time)


Command: themes
usage: heirloom themes [-h] [{list,use}] [<name>]

positional arguments:
  {list,use}  What to do (default: list)
  <name>      Theme to use

optional arguments:
  -h, --help  show this help message and exit


Command: status
usage: heirloom status [-h] [--offline] [--json]

optional arguments:
  -h, --help  show this help message and exit
  --offline   Only print offline status information, do not login
  --json      Show status in JSON format


Command: sync-saves
usage: heirloom sync-saves [-h] [--skip-upload] [--skip-download]
                            [--force-upload] [--force-download]
                            [--save-path <path>] [--disable-filters]
                            [<App Name>]

positional arguments:
  <App Name>          Name of the app (optional)

optional arguments:
  -h, --help          show this help message and exit
  --skip-upload       Only download new saves from cloud, don't upload
  --skip-download     Only upload new saves from cloud, don't download
  --force-upload      Force upload even if local saves are older
  --force-download    Force download even if local saves are newer
  --save-path <path>  Override savegame path (requires single app name to be
                      specified)
  --disable-filters   Disable save game file filtering


Command: uninstall
usage: heirloom uninstall [-h] [--keep-files] <App Name>

positional arguments:
  <App Name>    Name of the app

optional arguments:
  -h, --help    show this help message and exit
  --keep-files  Keep files but remove game from Heirloom database


Command: verify
usage: heirloom verify [-h] <App Name>

positional arguments:
  <App Name>  Name of the app

optional arguments:
  -h, --help  show this help message and exit
````


## Plugins

Plugins add features to Heirloom, much like [Millennium](https://github.com/SteamClientHomebrew/Millennium) does for Steam.
Each plugin is a folder in the `plugins` folder of the config directory (`~/.config/heirloom/plugins` by default) with a `plugin.json` manifest and a Python file:

````json
{
  "name": "session-log",
  "common_name": "Session Log",
  "description": "Logs how long each game ran",
  "version": "1.0.0",
  "backend": "main.py"
}
````

Only `name` is required (lowercase letters, digits, `-` and `_`); `backend` defaults to `main.py`.
Plugins run inside Heirloom with access to your Epic account and files, so each one stays off until you enable it.
In the window, Customize in the sidebar turns plugins on and off, removes them and opens the plugins folder; in a terminal:

````
heirloom plugins
heirloom plugins enable session-log
heirloom plugins disable session-log
````

Heirloom comes with a few plugins to install from Customize's plugin store, which copies one into the plugins folder and turns it on:

| Plugin | What it does |
|--------|--------------|
| Notifications (`notifications`) | A desktop notification when a game finishes installing or updating, the window's automatic updates included |
| High performance while playing (`power-plan`) | Switches Windows to the High performance power plan while a game runs, and back afterwards (laptops with Modern Standby have no such plan) |
| Close the Epic Games Launcher (`close-epic-launcher`) | Closes the Epic Games Launcher when a game starts, so it doesn't run in the background while you play |
| Library worth (`library-worth`) | Adds `heirloom worth`: what your games and DLC cost on the Epic Games Store in your country, at full price and today, with the most valuable (`--top <n>`, `--json`) |

They are in [`heirloom/store`](heirloom/store), and make good examples.

The backend's `setup(plugin)` function subscribes to events and can add commands:

````python
def setup(plugin):
    def on_launch(event):
        # event.command, event.environment and event.working_directory can be changed before the game starts
        event.environment['DXVK_HUD'] = 'fps'

    def on_exit(event):
        plugin.log.info(f'{event.app_name} ran for {event.session.duration} ({event.session.result})')

    plugin.on('game_launching', on_launch)
    plugin.on('game_exited', on_exit)

    def count(args, core):
        print(f'{len(core.get_installed_list())} games installed')

    parser = plugin.command('count', count, help='Count installed games')
    parser.add_argument('--verbose', action='store_true')
````

| Event            | Sent                                                          | Fields                                                                           |
|------------------|---------------------------------------------------------------|----------------------------------------------------------------------------------|
| `game_launching` | right before `heirloom launch` starts a game                 | `app_name`, `game`, and the editable `command`, `environment`, `working_directory` |
| `game_exited`    | when that game exits (not with `--no-wait`)                   | `app_name`, `session` (`start`, `end`, `duration`, `exit_code`, `result`)         |
| `game_installed` | after a game or DLC is installed                              | `app_name`, `game`                                                               |
| `game_updated`   | after an installed game or DLC is updated                     | `app_name`, `game`, `previous_version`                                           |

A backend can import other files in its folder with relative imports (`from . import helpers`).
A plugin that fails to load or raises in a handler is logged and skipped, it never stops Heirloom; run with `-v` to see the traceback.
Plugin commands cannot replace Heirloom's own commands.

The [`plugins`](plugins) folder of this repository has plugins ready to copy into yours:

- [Discord Rich Presence](plugins/discord-presence) shows the game you're playing in your Discord status.


## Themes

Themes set the colours and symbols Heirloom prints with. `heirloom themes` lists the available themes with a preview, and `heirloom themes use <name>` switches to one.
Heirloom comes with `default`, `modern` (bright colours, Unicode symbols), `high-contrast`, and `plain` (no colours).

A theme is a JSON file. Put your own in the `themes` folder of the config directory (`~/.config/heirloom/themes` by default):

````json
{
  "name": "dracula",
  "common_name": "Dracula",
  "description": "Purple and pink on dark backgrounds",
  "colors": {
    "accent": "bold #bd93f9",
    "warning": "#f1fa8c",
    "error": "bold #ff5555",
    "logger": "#6272a4",
    "muted": "#6272a4"
  },
  "symbols": {"bullet": "•", "alert": "!"}
}
````

| Color      | Used for                                    |
|------------|---------------------------------------------|
| `debug`, `info`, `warning`, `error`, `critical` | log messages of that level |
| `logger`   | the `[cli]` prefix of log messages          |
| `accent`   | game and plugin names in lists              |
| `muted`    | secondary text                              |

Styles combine `bold`, `dim`, `italic`, `underline`, a colour (`black`, `red`, `green`, `yellow`, `blue`, `magenta`, `cyan`, `white`, or `bright_` versions of them, or `#rrggbb`), and `on <colour>` for the background.
Symbols are 1 to 3 characters: `bullet` marks list entries, `alert` marks problems.
Only `name` is required; anything left out comes from the default theme.

Plugins can ship themes too, which are available while the plugin is enabled. A theme-only plugin needs no Python code:

````json
{
  "name": "dracula-theme",
  "useBackend": false,
  "themes": ["themes/dracula.json"]
}
````

Colours are only used when printing to a terminal, and never when `NO_COLOR` is set. Set `FORCE_COLOR=1` to keep them when piping output.

### Window themes

The window of `heirloom gui` has its own look, apart from the terminal's theme. Your own CSS can restyle it: once there is a window theme besides Heirloom's own, Customize in the sidebar switches between them, and its Themes folder button opens the folder to add or remove them.
High contrast needs no theme: the window follows Windows' contrast themes and "Increase contrast" settings by itself.
Heirloom comes with two more window themes. Fluent is Heirloom in the manner of Windows 11: a Mica-dark base with the library on a rounded layer, acrylic menus and panels, the light-blue accent and Segoe UI Variable (Windows 11's own font, so nothing is bundled). Impeccable is a light, editorial-poster look with cream pages, a burnt-orange sidebar, an amber accent, and Chakra Petch with JetBrains Mono (bundled, under the SIL Open Font License). They are also worked examples of window themes, in [`heirloom/gui/web/themes`](heirloom/gui/web/themes).

The quickest window theme is a CSS file in the `themes` folder, such as `paper-white.css`, which shows as "Paper white".
A terminal theme can bring window CSS too: name a CSS file next to the theme in `gui_css`.
Either way it is added to the window's page, so it can restyle anything:

````json
{
  "name": "neon",
  "common_name": "Neon",
  "colors": {"accent": "bold bright_cyan"},
  "gui_css": "neon.css"
}
````

````css
:root {
  --bg: #07070d;
  --surface: #10101c;
  --surface-raised: #191930;
  --border: #ff2bd6;
  --text: #f5f5ff;
  --muted: #b9b9ff;
  --accent: #00f0ff;
  --accent-text: #001014;
  --radius: 2px;
  --font: "Consolas", monospace;
}
.card { box-shadow: 0 0 18px #ff2bd633; }
````

The page's own colours, corners and font come from those CSS variables (plus `--surface-raised`, `--danger`, `--progress`, `--radius-control` for buttons and fields, `--logo` for the logo's colour, `--unlit` for the CSS filter over covers of games not installed, `--card-width` and `--shadow`), so most themes only need to set some of them.
The page is in [`heirloom/gui/web`](heirloom/gui/web) for the class names to style.


## Config file

Heirloom supports some options as well as game specific configuration in `~/.config/heirloom/config.ini`:
````ini
[Heirloom]
log_level = debug
; maximum shared memory (in MiB) to use for installation
max_memory = 2048
; maximum number of worker processes when downloading (fewer workers will be slower, but also use less system resources)
max_workers = 8
; download speed limit (MiB/s, or with a K/M/G suffix), 0 for none
max_download_speed = 20
; lower download speed limit while a game started by "heirloom launch" is running
max_download_speed_while_playing = 2
; daily time window for "heirloom queue run" (may cross midnight, e.g. 23:00-07:00)
download_window = 01:00-07:00
; default install directory
install_dir = /mnt/tank/games
; locale override, must be in RFC 1766 format (e.g. "en-US")
locale = en-US
; whether or not syncing with egl is enabled
egl_sync = false
; path to the "Manifests" folder in the EGL ProgramData directory
egl_programdata = /home/user/Games/epic-games-store/drive_c/... 
; path to the new Epic Games Launcher's installations.jsonl (import only), if it is not found automatically
egl_installations = /home/user/Games/epic-games-store/drive_c/users/user/AppData/Local/com.epicgames.eglv2/installations.jsonl
; Set preferred CDN host (e.g. to improve download speed)
preferred_cdn = epicgames-download1.akamaized.net
; disable HTTPS for downloads (e.g. to use a LanCache)
disable_https = false
; Disables the automatic update check
disable_update_check = false
; Disables the notice about a newer Heirloom release, on exit and in the window
disable_update_notice = false
; Disable automatically-generated aliases
disable_auto_aliasing = false
; Do not record playtime (launches stop waiting for games to exit if cloud save sync is off too)
disable_playtime_tracking = false
; Do not download a newer cloud save before a game starts, or upload a newer local save after it exits
disable_cloud_save_sync = false
; Do not install game updates by themselves when the window of "heirloom gui" finds them
disable_auto_updates = false
; Terminal theme (see "heirloom themes")
theme = default
; Window theme of "heirloom gui" (see "Window themes")
window_theme = heirloom

; macOS specific settings
; Default application platform to use (default: Mac on macOS, Windows elsewhere)
default_platform = Windows
; Fallback to "Windows" platform if native version unavailable
install_platform_fallback = true
; (macOS) Disable automatic CrossOver use
disable_auto_crossover = false
; Default directory for native Mac applications (.app packages)
mac_install_dir = /User/heirloom/Applications

[Heirloom.aliases]
; List of aliases for simpler CLI use, in the format `<alias> = <app name>`
HITMAN 3 = Eider
gtav = 9d2d0eb64d5c44529cece33fe2a46482

; default settings to use for all apps (unless overridden in the app's config section)
; Note that only the settings listed below are supported.
[default]
; (all) wrapper to run the game with (e.g. "gamemode")
wrapper = gamemode
; (linux/macOS) Wine executable and prefix
wine_executable = wine
wine_prefix = /home/user/.wine
; (macOS) CrossOver options
crossover_app = /Applications/CrossOver.app
crossover_bottle = Heirloom

; default environment variables to set (overridden by game specific ones)
[default.env]
WINEPREFIX = /home/user/heirloom/.wine

; Settings to only use for "AppName"
[AppName]
; launch game without online authentication by default
offline = true
; Skip checking for updates when launching this game
skip_update_check = true
; start parameters to use (in addition to the required ones)
start_params = -windowed
; override language with two-letter language code
language = fr
; Override Wine version for this app
wine_executable = /path/to/wine64

[AppName.env]
; environment variables to set for this game (mostly useful on linux)
WINEPREFIX = /mnt/tank/games/Game/.wine
DXVK_CONFIG_FILE = /mnt/tank/games/Game/dxvk.conf

[AppName2]
; Use a wrapper to run this script
; Note that the path might have to be quoted if it contains spaces
wrapper = "/path/with spaces/gamemoderun"
; Do not run this executable with WINE (e.g. when the wrapper handles that)
no_wine = true
; Override the executable launched for this game, for example to bypass a launcher (e.g. Borderlands)
override_exe = relative/path/to/file.exe
; Disable selective downloading for this title
disable_sdl = true

[AppName3]
; Command to run before launching the gmae
pre_launch_command = /path/to/script.sh
; Whether or not to wait for command to finish running
pre_launch_wait = false
; (macOS) override crossover settings
crossover_app = /Applications/CrossOver Nightly.app
crossover_bottle = SomethingElse
````
