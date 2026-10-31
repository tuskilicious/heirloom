# Changelog

## Unreleased

### Added
- **Four themes that change the layout**, in Customize:
  - **Big picture**, for a TV and a controller: a bar along the top, a tall banner for the game you're on with its
    art glowing behind the page, and one row of large covers that scrolls sideways.
  - **Compact list**: a dense table, one row per game with its status, size, time played and last played. The
    headings sort by their column, and about forty games fit on screen.
  - **Showcase**: a banner most of the window high with a huge headline and slowly drifting art, and big covers that
    float into place as you scroll.
  - **Retro arcade**: neon on black behind CRT scanlines, the sidebar as a cabinet's lit marquee, installed games
    glowing cyan, and PRESS START flashing over the cover under the pointer.
- **Keyboard and gamepad control**, in every theme:
  - The arrow keys, or a gamepad's D-pad or stick, move between games.
  - Enter or A plays, updates or opens Install.
  - The Menu key or Y opens Manage.
  - B closes a dialog or menu.
- **Theme tiles**: the theme picker shows each theme as a small preview in its colours.

## 0.34.0 "Guildhall" (2026-10-31)

Plugins that do what they say, in the window, from their own repository.

### Changed
- **Plugins live in their own repository**, [tuskilicious/heirloom-plugins](https://github.com/tuskilicious/heirloom-plugins),
  and Heirloom downloads one only when you install it. Customize's plugin store lists them from there. In a
  terminal: `heirloom plugins store`, and `heirloom plugins install|update|remove <name>`. Plugins you already have
  keep working, and the window offers their updates.

### Added
- **Plugins can add buttons to the window.** Library worth now has "Work out my library's worth" in Customize, and the
  window shows what it found.
- **Discord Rich Presence is in the plugin store**, to install with one click.
- **Customize shows why a plugin didn't load**, rather than it silently doing nothing.

### Fixed
- **Notifications come from Heirloom** rather than Windows PowerShell (update the plugin in Customize). Windows only
  shows them with notifications turned on, in Settings → System → Notifications.

## 0.33.0 "Courier" (2026-10-31)

Downloads you control: which goes next, when updates run, and how they download.

### Added
- **Download next.** A waiting download in the downloads panel has a button that moves it ahead of the others
  waiting, so it starts when the current one finishes.
- **Update games only between set hours**, overnight say, under Settings → Downloads. Automatic updates start only
  then; Update by hand works any time. It's the `download_window` option that `heirloom queue` keeps to as well.
- **Advanced download settings**, folded away under Settings → Downloads: the number of download threads, the
  memory downloads use, and a preferred download server. Empty or 0 keeps Heirloom's own choice.

## 0.32.0 "Mantelpiece" (2026-10-31)

Your Epic achievements, in the window: per game, and as a count on the cards.

### Added
- **Achievements in the window.** Achievements… in a game's menu (Manage, or right-click) lists its achievements:
  the ones you unlocked and when, the ones in progress and how far along you are, and the share of players who have
  each. Hidden ones are counted, and shown once unlocked.
- **Cards show "12/40 achievements"** for games whose achievements Heirloom has asked Epic about: installed games, at
  each refresh; a game, when it closes after playing; and any game whose Achievements… you opened.

## 0.31.0 "Workbench" (2026-10-30)

The window can now move games, add ones already on disk, manage DLC, show how cloud saves stand, and activate
Ubisoft games, all things only the terminal or Epic's launcher could do before.

### Added
- **Move a game** to another folder or drive, from Move… in its Manage menu. Heirloom checks there is room on the
  other drive first. `heirloom move` now moves across drives too, by copying the files and then deleting the old ones.
- **Add a game that's already on this PC**, from a copy or another drive, rather than downloading it again: "Already
  on this PC…" in the install dialog, or in the menu you get by right-clicking a game that isn't installed. Its DLC
  that is there is added too.
- **DLC after installing.** DLC… in the Manage menu lists the game's DLC that has files of its own, and installs or
  uninstalls each one. It only shows for games that have such DLC.
- **Cloud saves… in the Manage menu** shows whether the saves on this PC or the cloud's are newer, when each was made,
  and where they are, with Sync now.
- **Activate on Ubisoft Connect.** Ubisoft games show an Activate button, which adds all your Ubisoft games from Epic
  to your Ubisoft account, as `heirloom activate --uplay` does.

### Fixed
- **Sync cloud saves did nothing for a game whose save folder wasn't set yet.** It now uses the folder Epic gives.
- **`heirloom move` and `heirloom import` exit with code 1 when they fail**, so the window shows them as failed.

## 0.30.0 "Lantern" (2026-10-30)

The window opens in about half the time, and can wait in the tray from the moment Windows starts.

### Changed
- **The window opens in about half the time.** Each time it opened, it first asked whether a Heirloom window was
  already open, through a port that the last Heirloom to quit had left behind; Windows takes about two seconds to say
  nothing answers there. It no longer waits for that, and Heirloom removes the port when it quits. With a copy of a
  564-game library, the time to the window's first call to Heirloom went from 4.3 to 1.9 seconds.
- **Covers load from the disk.** The window keeps its browser profile (in the `webview` folder next to Heirloom's
  config), so covers it showed before come from the disk cache rather than from Epic each time it opens.
- **A window brought back from the tray is up to date at once**, rather than at the next refresh a second later.
- **The installer starts Heirloom with Windows**, in the tray, unless you untick it. It then opens at once, and games
  update before you play. Settings turns it off.

## 0.29.0 "Kindling" (2026-10-30)

Games start sooner after Play.

### Changed
- **Games start sooner.** Before a game started, Heirloom asked Epic whether its saved login was still good, fetched
  the versions of every game to check this one was current, and checked for updates of Heirloom and the overlay, one
  after another. Now:
  - a saved login with time left is used as it is, and only logged in again if Epic refuses it;
  - launching checks for no updates (the window's hourly refresh does that);
  - Play in the window skips the version check when the window fetched the versions within the hour and the game
    has no update;
  - a newer cloud save is looked for at the same time as the launch is prepared.

  Preparing to launch Celeste the way the window does went from 3.7 to 2.2 seconds (a dry run from source; the
  installed build starts about 0.3 seconds faster than that).

## 0.28.3 "Homestead" (2026-10-30)

Heirloom offers its own new releases the day they are out.

### Fixed
- **A new Heirloom is offered within the hour.** Heirloom asked GitHub for a newer version of itself only once a
  day, with the rest of the update feed, so a release could go unnoticed until the next day. It now asks each
  hour; the feed is still fetched once a day.

## 0.28.2 "Homestead" (2026-10-30)

Heirloom's window opens faster and stays smooth with a large library.

### Fixed
- **The window opens faster and no longer hitches every second.** It sent the whole library (about 300 KiB for 564
  games) from Heirloom to the page once a second; now it sends the games only when they changed, which takes the
  once-a-second work from about 14 ms to 1 ms. Heirloom also reads each game's details only when something needs
  them, rather than all of them every time it starts: the window's own calls went from 0.3 s each to a few
  milliseconds, and the library is read while the window opens rather than before. Commands such as
  `heirloom launch` start sooner too.

## 0.28.1 "Homestead" (2026-10-29)

Heirloom's window is fast again with a large library.

### Fixed
- **The window is fast with a large library again.** Every card carried two live blurs of what was behind it (the
  name plate and the grey of a game not installed), a 3D layer of its own and an animation it never let go of, so a
  library of hundreds of games made the window crawl. Name plates are now a tint, a game not installed is greyed by a
  filter on its cover, the tilt only exists under the pointer, and only the first screenful fades in. Covers come
  from Epic's image server at the size they are drawn rather than as originals, and a window hidden in the tray stops
  redrawing. The frosted glass stays on the header, the menus and the downloads panel.

## 0.28.0 "Homestead" (2026-10-29)

Heirloom settles in as your launcher: it keeps going in the tray and starts with Windows, asks where a game goes
before installing it, has its settings in the window, and shows what Epic gives away.

### New
- **Heirloom keeps going in the tray.** On Windows, closing the window hides it to an icon in the tray, and downloads
  and updates go on; double-click the icon to bring the window back, or choose Quit in its menu. Opening Heirloom
  again brings back the window already open rather than a second one. Customize can start Heirloom with Windows,
  hidden in the tray, so games are updated before you sit down to play (`heirloom gui --background` does the same by
  hand). The library is refreshed every hour while Heirloom runs, window open or not.
- **Free on Epic.** Above the library, the games Epic gives away now and next, with when, from Epic's public list;
  the ones already in your library are marked, and Claim on Epic opens a game's store page in your browser to claim
  it there. Discounts that aren't free are left out.
- **Launch options.** Manage has Launch options, to set the arguments a game starts with (such as `-dx11`), kept as
  `start_params` in its section of the config; options with a stray quote are refused.
- **An install dialog.** Install opens a dialog with the game's download size, its size on disk and the space free
  where it goes, and warns rather than starts when it won't fit. A game can go into a folder of its own, and its DLC
  can be left out. It opens at once and fills in the sizes when Epic has answered.
- **Settings.** A Settings panel in the sidebar chooses where games are installed (with the system's folder
  dialog), sets the download speed limit and a lower one while you play, and turns automatic updates, cloud save
  sync, starting with Windows and the notice about new Heirloom versions on and off. They are the config file's
  options, saved as soon as they change, and a value that makes no sense is refused with a message.

## 0.27.0 "Keepsake" (2026-10-29)

Heirloom's window becomes a launcher to keep: games manage and update themselves, themes and plugins are a click
away, and the library assembles, glides and glows.

### New
- **Game updates install by themselves.** Each time the window refreshes your library, when it opens and then every
  hour, it starts the updates of installed games and says which. Games being played are left alone, and so are
  updates you stopped or that failed since the window opened, until you press Update. `disable_auto_updates = true`
  in the config file turns it off.
- **Manage a game from the window.** Each installed game has a Manage button (`⋯`): open its folder, add a desktop
  shortcut that plays it (Windows), verify and repair its files, sync its cloud saves, play without updating, or
  uninstall it.
- **A calmer, livelier library.** A game's buttons appear over its cover when you point at it or reach it with
  the keyboard, so the library reads as covers rather than rows of buttons. Covers lean toward the pointer, catch a
  sweep of light and glow in the lantern's colour; the art of the game you played last lights the page behind the
  frosted header, and the logo's lantern flickers. Scrollbars are slim and in the window's colours.
- **Downloads assemble their cover.** While a game downloads, tiles over its cover light up in a scattered order,
  flash citron and snap away, and the art beneath sharpens from a blur and gains its colour, crisp at 100%. When the
  game is installed, the whole cover flares up. The progress bar of the downloads panel glints too.
- **The window's own theme.** The window keeps its own look whatever the terminal's theme is, and window themes are
  your CSS: a `.css` file in the `themes` folder, or a theme's `gui_css`. Themes are chosen in Customize, which only
  offers a choice once there is one. High contrast follows Windows' contrast settings. The setting is `window_theme`
  in the config file.
- **Quality of life in the window.** A sort button orders the library A to Z, by when you last played, by playtime or
  by size, the cards gliding into place. The window opens on the shelf, order and sidebar you left it with. Search
  ignores case, spaces and punctuation, and Escape empties it. Double-click an installed game to play it, right-click
  it for its Manage menu, and notices can be closed.
- **Fluent, a window theme in the manner of Windows 11.** A Mica-dark base with the library on a rounded layer,
  acrylic menus and panels with a fine grain, the light-blue accent, Fluent's calm deceleration, and Segoe UI
  Variable, which Windows 11 has.
- **Impeccable, a second window theme.** A light, editorial-poster look to choose in Customize: cream pages beside a
  burnt-orange sidebar, an amber accent with burnt-orange text where amber would be too faint to read, and Chakra Petch
  with JetBrains Mono labels, bundled so it works offline. No glows; shadows are tinted warm.
- **The Epic overlay in the window.** On Windows, Customize installs the Epic overlay (friends, invites and
  achievements in games using Epic Online Services) as a download, turns it on and off for every game, updates and
  removes it, and says when it is on from the Epic Games Launcher's own copy.
- **Covers tilt with the pointer at once.** The tilt toward the pointer no longer trails behind it; the lift keeps
  its spring, and the tilt springs back on leaving.
- **Customize, and a plugin store.** Customize in the sidebar opens a panel to choose the window's theme, turn
  plugins on and off, remove them, and open the themes and plugins folders to add your own. Its plugin store installs
  the plugins that now come with Heirloom in one click: Notifications (when a game is installed or updated), High
  performance while playing (the Windows power plan), Close the Epic Games Launcher (when a game starts), and
  Library worth, whose `heirloom worth` adds up what your games and DLC cost on the Epic Games Store, at full price
  and today.
- **Smoother.** Covers lift, the sidebar marker slides and menus open on a gentle spring; filtering and searching
  glide the cards to their new places; menus and Customize ease out as well as in; the downloads list folds up;
  loading covers shimmer, and notices slide in with a citron edge. The logged-out lantern glows.
- **Frosted glass.** The header is a floating bar of frosted glass, each game's name and status sit on a frosted
  plate over its cover (making way for its buttons under the pointer), and the downloads panel and menus are frosted
  too. Under Windows' contrast settings they stay solid.

### Fixed
- Opening Heirloom from the Start menu or desktop shortcut no longer shows a terminal window for a moment. The
  shortcuts run the new `heirloom-gui.exe`, a windowed program that starts the window with its terminal hidden.

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
