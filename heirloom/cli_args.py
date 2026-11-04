"""The command line of "heirloom": every command and its options, without what they do (see cli.py)."""
import argparse
import os

from heirloom import __codename__, __version__
from heirloom.downloader.throttle import parse_speed
from heirloom.utils.cli import strtobool
from heirloom.utils.custom_parser import HiddenAliasSubparsersAction


def _speed_argument(text):
    try:
        return parse_speed(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def build_parser():
    """The parser, its commands to add to, and the two commands whose options are checked again later"""
    parser = argparse.ArgumentParser(description=f'Heirloom v{__version__} - "{__codename__}"')
    parser.register('action', 'parsers', HiddenAliasSubparsersAction)

    # general arguments
    parser.add_argument('-H', '--full-help', dest='full_help', action='store_true',
                        help='Show full help (including individual command help)')
    parser.add_argument('-v', '--debug', dest='debug', action='store_true', help='Set loglevel to debug')
    parser.add_argument('-y', '--yes', dest='yes', action='store_true', help='Default to yes for all prompts')
    parser.add_argument('-V', '--version', dest='version', action='store_true', help='Print version and exit')
    parser.add_argument('-c', '--config-file', dest='config_file', action='store', metavar='<path/name>',
                        help=argparse.SUPPRESS)
    parser.add_argument('-J', '--pretty-json', dest='pretty_json', action='store_true',
                        help='Pretty-print JSON')
    parser.add_argument('-A', '--api-timeout', dest='api_timeout', action='store',
                        type=float, default=10, metavar='<seconds>',
                        help='API HTTP request timeout (default: 10 seconds)')

    # all the commands
    subparsers = parser.add_subparsers(title='Commands', dest='subparser_name', metavar='<command>')
    activate_parser = subparsers.add_parser('activate', help='Activate games on third party launchers')
    alias_parser = subparsers.add_parser('alias', help='Manage aliases')
    auth_parser = subparsers.add_parser('auth', help='Authenticate with the Epic Games Store')
    clean_saves_parser = subparsers.add_parser('clean-saves', help='Clean cloud saves')
    clean_parser = subparsers.add_parser('cleanup', help='Remove old temporary, metadata, and manifest files')
    download_saves_parser = subparsers.add_parser('download-saves', help='Download all cloud saves')
    egl_sync_parser = subparsers.add_parser('egl-sync', help='Setup or run Epic Games Launcher sync')
    gui_parser = subparsers.add_parser('gui', help='Open the Heirloom window: your library, installs, updates and playing')
    eos_overlay_parser = subparsers.add_parser('eos-overlay', help='Manage EOS Overlay install')
    gui_parser.add_argument('--background', action='store_true',
                            help='Start in the tray, with the window hidden (as when starting with Windows)')
    import_parser = subparsers.add_parser('import', help='Import an already installed game',
                                          aliases=('import-game',), hide_aliases=True)
    info_parser = subparsers.add_parser('info', help='Prints info about specified app name or manifest')
    install_parser = subparsers.add_parser('install', help='Install/download/update/repair a game',
                                           aliases=('download', 'update', 'repair'),
                                           usage='%(prog)s <App Name> [options]',
                                           description='Aliases: download, update')
    launch_parser = subparsers.add_parser('launch', help='Launch a game', usage='%(prog)s <App Name> [options]',
                                          description='Note: additional arguments are passed to the game')
    list_parser = subparsers.add_parser('list', aliases=('list-games',), hide_aliases=True,
                                        help='List available (installable) games')
    list_files_parser = subparsers.add_parser('list-files', help='List files in manifest')
    list_installed_parser = subparsers.add_parser('list-installed', help='List installed games')
    list_saves_parser = subparsers.add_parser('list-saves', help='List available cloud saves')
    move_parser = subparsers.add_parser('move', help='Move specified app name to a new location')
    playtime_parser = subparsers.add_parser('playtime', help='Show playtime recorded by "heirloom launch"')
    plugins_parser = subparsers.add_parser('plugins', help='List, enable, or disable plugins')
    themes_parser = subparsers.add_parser('themes', help='List terminal themes or switch to one')
    queue_parser = subparsers.add_parser('queue', help='Queue installs and updates to run later, e.g. overnight',
                                         usage='%(prog)s [list|add|remove|clear|run] [<App Name> ...] [options]',
                                         description='"add" also takes "heirloom install" options for the queued '
                                                     'downloads, e.g. "heirloom queue add Anemone --max-speed 5M"')
    status_parser = subparsers.add_parser('status', help='Show heirloom status information')
    sync_saves_parser = subparsers.add_parser('sync-saves', help='Sync cloud saves')
    uninstall_parser = subparsers.add_parser('uninstall', help='Uninstall (delete) a game')
    verify_parser = subparsers.add_parser('verify', help='Verify a game\'s local files',
                                          aliases=('verify-game',), hide_aliases=True)
    achievements_parser = subparsers.add_parser('achievements', help='List achievement status for a given game')

    # hidden commands have no help text
    get_token_parser = subparsers.add_parser('get-token')

    # Positional arguments
    install_parser.add_argument('app_name', help='Name of the app', metavar='<App Name>')
    uninstall_parser.add_argument('app_name', help='Name of the app', metavar='<App Name>')
    launch_parser.add_argument('app_name', help='Name of the app', metavar='<App Name>')
    list_files_parser.add_argument('app_name', nargs='?', metavar='<App Name>',
                                   help='Name of the app (optional)')
    list_saves_parser.add_argument('app_name', nargs='?', metavar='<App Name>', default='',
                                   help='Name of the app (optional)')
    download_saves_parser.add_argument('app_name', nargs='?', metavar='<App Name>', default='',
                                       help='Name of the app (optional)')
    clean_saves_parser.add_argument('app_name', nargs='?', metavar='<App Name>', default='',
                                    help='Name of the app (optional)')
    sync_saves_parser.add_argument('app_name', nargs='?', metavar='<App Name>', default='',
                                   help='Name of the app (optional)')
    verify_parser.add_argument('app_name', help='Name of the app', metavar='<App Name>')
    import_parser.add_argument('app_name', help='Name of the app', metavar='<App Name>')
    import_parser.add_argument('app_path', help='Path where the game is installed',
                               metavar='<Installation directory>')
    info_parser.add_argument('app_name_or_manifest', help='App name or manifest path/URI',
                             metavar='<App Name/Manifest URI>')

    alias_parser.add_argument('action', help='Action: Add, rename, remove, or list alias(es)',
                              choices=['add', 'rename', 'remove', 'list'],
                              metavar='<add|rename|remove|list>')
    alias_parser.add_argument('app_or_alias', help='App name when using "add" or "list" action, '
                                                   'existing alias when using "rename" or "remove" action',
                              metavar='<App name/Old alias>', nargs='?')
    alias_parser.add_argument('alias', help='New alias when using "add" action',
                              metavar='<New alias>', nargs='?')

    move_parser.add_argument('app_name', metavar='<App Name>', help='Name of the app')
    move_parser.add_argument('new_path', metavar='<New Base Path>', help='Directory to move game folder to')

    # Flags
    auth_parser.add_argument('--import', dest='import_egs_auth', action='store_true',
                             help='Import Epic Games Launcher authentication data (logs out of EGL)')
    auth_parser.add_argument('--code', dest='auth_code', action='store', metavar='<authorization code>',
                             help='Use specified authorization code instead of interactive authentication')
    auth_parser.add_argument('--token', dest='ex_token', action='store', metavar='<exchange token>',
                             help='Use specified exchange token instead of interactive authentication')
    auth_parser.add_argument('--sid', dest='session_id', action='store', metavar='<session id>',
                             help='Use specified session id instead of interactive authentication')
    auth_parser.add_argument('--delete', dest='auth_delete', action='store_true',
                             help='Remove existing authentication (log out)')
    auth_parser.add_argument('--disable-webview', dest='no_webview', action='store_true',
                             help='Do not use embedded browser for login')

    install_parser.add_argument('--base-path', dest='base_path', action='store', metavar='<path>',
                                help='Path for game installations (defaults to ~/Games)')
    install_parser.add_argument('--game-folder', dest='game_folder', action='store', metavar='<path>',
                                help='Folder for game installation (defaults to folder specified in metadata)')
    install_parser.add_argument('--max-shared-memory', dest='shared_memory', action='store', metavar='<size>',
                                type=int, help='Maximum amount of shared memory to use (in MiB), default: 1 GiB')
    install_parser.add_argument('--max-workers', dest='max_workers', action='store', metavar='<num>',
                                type=int, help='Maximum amount of download workers, default: min(2 * CPUs, 16)')
    install_parser.add_argument('--max-speed', dest='max_speed', action='store', metavar='<speed>',
                                type=_speed_argument,
                                help='Limit the download speed, e.g. "5" or "5M" for 5 MiB/s, "500K" for 500 KiB/s, '
                                     '0 for no limit (default: max_download_speed from the config)')
    install_parser.add_argument('--max-speed-while-playing', dest='max_speed_while_playing', action='store',
                                metavar='<speed>', type=_speed_argument,
                                help='Lower download speed limit while a game started by "heirloom launch" is '
                                     'running (default: max_download_speed_while_playing from the config)')
    install_parser.add_argument('--manifest', dest='override_manifest', action='store', metavar='<uri>',
                                help='Manifest URL or path to use instead of the CDN one (e.g. for downgrading)')
    install_parser.add_argument('--old-manifest', dest='override_old_manifest', action='store', metavar='<uri>',
                                help='Manifest URL or path to use as the old one (e.g. for testing patching)')
    install_parser.add_argument('--delta-manifest', dest='override_delta_manifest', action='store', metavar='<uri>',
                                help='Manifest URL or path to use as the delta one (e.g. for testing)')
    install_parser.add_argument('--base-url', dest='override_base_url', action='store', metavar='<url>',
                                help='Base URL to download from (e.g. to test or switch to a different CDNs)')
    install_parser.add_argument('--force', dest='force', action='store_true',
                                help='Download all files / ignore existing (overwrite)')
    install_parser.add_argument('--disable-patching', dest='disable_patching', action='store_true',
                                help='Do not attempt to patch existing installation (download entire changed files)')
    install_parser.add_argument('--download-only', '--no-install', dest='no_install', action='store_true',
                                help='Do not install app and do not run prerequisite installers after download')
    install_parser.add_argument('--update-only', dest='update_only', action='store_true',
                                help='Only update, do not do anything if specified app is not installed')
    install_parser.add_argument('--dlm-debug', dest='dlm_debug', action='store_true',
                                help='Set download manager and worker processes\' loglevel to debug')
    install_parser.add_argument('--platform', dest='platform', action='store', metavar='<Platform>', type=str,
                                help='Platform for install (default: installed or Windows)')
    install_parser.add_argument('--prefix', dest='file_prefix', action='append', metavar='<prefix>',
                                help='Only fetch files whose path starts with <prefix> (case insensitive)')
    install_parser.add_argument('--exclude', dest='file_exclude_prefix', action='append', metavar='<prefix>',
                                type=str, help='Exclude files starting with <prefix> (case insensitive)')
    install_parser.add_argument('--install-tag', dest='install_tag', action='append', metavar='<tag>',
                                type=str, help='Only download files with the specified install tag')
    install_parser.add_argument('--enable-reordering', dest='order_opt', action='store_true',
                                help='Enable reordering optimization to reduce RAM requirements '
                                     'during download (may have adverse results for some titles)')
    install_parser.add_argument('--dl-timeout', dest='dl_timeout', action='store', metavar='<sec>', type=int,
                                help='Connection timeout for downloader (default: 10 seconds)')
    install_parser.add_argument('--save-path', dest='save_path', action='store', metavar='<path>',
                                help='Set save game path to be used for sync-saves')
    install_parser.add_argument('--repair', dest='repair_mode', action='store_true',
                                help='Repair installed game by checking and redownloading corrupted/missing files')
    install_parser.add_argument('--repair-and-update', dest='repair_and_update', action='store_true',
                                help='Update game to the latest version when repairing')
    install_parser.add_argument('--ignore-free-space', dest='ignore_space', action='store_true',
                                help='Do not abort if not enough free space is available')
    install_parser.add_argument('--disable-delta-manifests', dest='disable_delta', action='store_true',
                                help='Do not use delta manifests when updating (may increase download size)')
    install_parser.add_argument('--reset-sdl', dest='reset_sdl', action='store_true',
                                help='Reset selective downloading choices (requires repair to download new components)')
    install_parser.add_argument('--skip-sdl', dest='skip_sdl', action='store_true',
                                help='Skip SDL prompt and continue with defaults (only required game data)')
    install_parser.add_argument('--disable-sdl', dest='disable_sdl', action='store_true',
                                help='Disable selective downloading for title, reset existing configuration (if any)')
    install_parser.add_argument('--preferred-cdn', dest='preferred_cdn', action='store', metavar='<hostname>',
                                help='Set the hostname of the preferred CDN to use when available')
    install_parser.add_argument('--no-https', dest='disable_https', action='store_true',
                                help='Download games via plaintext HTTP (like EGS), e.g. for use with a lan cache')
    install_parser.add_argument('--with-dlcs', dest='with_dlcs', action='store_true',
                                help='Automatically install all DLCs with the base game')
    install_parser.add_argument('--skip-dlcs', dest='skip_dlcs', action='store_true',
                                help='Do not ask about installing DLCs.')
    install_parser.add_argument('--bind', dest='bind_ip', action='store', metavar='<IPs>', type=str,
                                help='Comma-separated list of IPs to bind to for downloading')

    uninstall_parser.add_argument('--keep-files', dest='keep_files', action='store_true',
                                  help='Keep files but remove game from Heirloom database')
    uninstall_parser.add_argument('--skip-uninstaller', dest='skip_uninstaller', action='store_true',
                                  help='Skip running the uninstaller')

    launch_parser.add_argument('--offline', dest='offline', action='store_true',
                               default=False, help='Skip login and launch game without online authentication')
    launch_parser.add_argument('--skip-version-check', dest='skip_version_check', action='store_true',
                               default=False, help='Skip version check when launching game in online mode')
    launch_parser.add_argument('--override-username', dest='user_name_override', action='store', metavar='<username>',
                               help='Override username used when launching the game (only works with some titles)')
    launch_parser.add_argument('--dry-run', dest='dry_run', action='store_true',
                               help='Print the command line that would have been used to launch the game and exit')
    launch_parser.add_argument('--no-wait', dest='no_wait', action='store_true',
                               help='Return right after starting the game instead of waiting for it to exit '
                                    '(playtime will not be recorded, and saves not uploaded)')
    launch_parser.add_argument('--no-sync-saves', dest='no_sync_saves', action='store_true',
                               help='Do not download a newer cloud save before the game starts, or upload a newer '
                                    'local save after it exits')
    launch_parser.add_argument('--language', dest='language', action='store', metavar='<two letter language code>',
                               help='Override language for game launch (defaults to system locale)')
    launch_parser.add_argument('--wrapper', dest='wrapper', action='store', metavar='<wrapper command>',
                               default=os.environ.get('LGDRY_WRAPPER', None),
                               help='Wrapper command to launch game with')
    launch_parser.add_argument('--set-defaults', dest='set_defaults', action='store_true',
                               help='Save parameters used to launch to config (does not include env vars)')
    launch_parser.add_argument('--reset-defaults', dest='reset_defaults', action='store_true',
                               help='Reset config settings for app and exit')
    launch_parser.add_argument('--override-exe', dest='executable_override', action='store', metavar='<exe path>',
                               help='Override executable to launch (relative path)')
    launch_parser.add_argument('--origin', dest='origin', action='store_true',
                               help='Launch Origin to activate or run the game.')
    launch_parser.add_argument('--ubisoft', dest='ubisoft', action='store_true',
                               help='Launch Ubisoft to install and run the game.')
    launch_parser.add_argument('--json', dest='json', action='store_true',
                               help='Print launch information as JSON and exit')

    if os.name != 'nt':
        launch_parser.add_argument('--wine', dest='wine_bin', action='store', metavar='<wine binary>',
                                   default=os.environ.get('LGDRY_WINE_BINARY', None),
                                   help='Set WINE binary to use to launch the app')
        launch_parser.add_argument('--wine-prefix', dest='wine_pfx', action='store', metavar='<wine pfx path>',
                                   default=os.environ.get('LGDRY_WINE_PREFIX', None),
                                   help='Set WINE prefix to use')
        launch_parser.add_argument('--no-wine', dest='no_wine', action='store_true',
                                   default=strtobool(os.environ.get('LGDRY_NO_WINE', 'False')),
                                   help='Do not run game with WINE (e.g. if a wrapper is used)')
    else:
        # hidden arguments to not break this on Windows
        launch_parser.add_argument('--wine', help=argparse.SUPPRESS, dest='wine_bin')
        launch_parser.add_argument('--wine-prefix', help=argparse.SUPPRESS, dest='wine_pfx')
        launch_parser.add_argument('--no-wine', dest='no_wine', help=argparse.SUPPRESS,
                                   action='store_true', default=True)

    list_parser.add_argument('--platform', dest='platform', action='store', metavar='<Platform>', type=str,
                             help='Platform to fetch game list for (default: Windows)')
    list_parser.add_argument('--include-ue', dest='include_ue', action='store_true',
                             help='Also include Unreal Engine content (Engine/Marketplace) in list')
    list_parser.add_argument('-T', '--third-party', '--include-non-installable',
                             dest='include_noasset', action='store_true', default=False,
                             help='Include apps that are not installable (e.g. that have to be activated on Origin)')
    list_parser.add_argument('--csv', dest='csv', action='store_true', help='List games in CSV format')
    list_parser.add_argument('--tsv', dest='tsv', action='store_true', help='List games in TSV format')
    list_parser.add_argument('--json', dest='json', action='store_true', help='List games in JSON format')
    list_parser.add_argument('--force-refresh', dest='force_refresh', action='store_true',
                             help='Force a refresh of all game metadata')

    list_installed_parser.add_argument('--check-updates', dest='check_updates', action='store_true',
                                       help='Check for updates for installed games')
    list_installed_parser.add_argument('--csv', dest='csv', action='store_true',
                                       help='List games in CSV format')
    list_installed_parser.add_argument('--tsv', dest='tsv', action='store_true',
                                       help='List games in TSV format')
    list_installed_parser.add_argument('--json', dest='json', action='store_true',
                                       help='List games in JSON format')
    list_installed_parser.add_argument('--show-dirs', dest='include_dir', action='store_true',
                                       help='Print installation directory in output')

    list_files_parser.add_argument('--force-download', dest='force_download', action='store_true',
                                   help='Always download instead of using on-disk manifest')
    list_files_parser.add_argument('--platform', dest='platform', action='store', metavar='<Platform>',
                                   type=str, help='Platform (default: Windows)')
    list_files_parser.add_argument('--manifest', dest='override_manifest', action='store', metavar='<uri>',
                                   help='Manifest URL or path to use instead of the CDN one')
    list_files_parser.add_argument('--csv', dest='csv', action='store_true', help='Output in CSV format')
    list_files_parser.add_argument('--tsv', dest='tsv', action='store_true', help='Output in TSV format')
    list_files_parser.add_argument('--json', dest='json', action='store_true', help='Output in JSON format')
    list_files_parser.add_argument('--hashlist', dest='hashlist', action='store_true',
                                   help='Output file hash list in hashcheck/sha1sum -c compatible format')
    list_files_parser.add_argument('--install-tag', dest='install_tag', action='store', metavar='<tag>',
                                   type=str, help='Show only files with specified install tag')

    sync_saves_parser.add_argument('--skip-upload', dest='download_only', action='store_true',
                                   help='Only download new saves from cloud, don\'t upload')
    sync_saves_parser.add_argument('--skip-download', dest='upload_only', action='store_true',
                                   help='Only upload new saves from cloud, don\'t download')
    sync_saves_parser.add_argument('--force-upload', dest='force_upload', action='store_true',
                                   help='Force upload even if local saves are older')
    sync_saves_parser.add_argument('--force-download', dest='force_download', action='store_true',
                                   help='Force download even if local saves are newer')
    sync_saves_parser.add_argument('--save-path', dest='save_path', action='store', metavar='<path>',
                                   help='Override savegame path (requires single app name to be specified)')
    sync_saves_parser.add_argument('--disable-filters', dest='disable_filters', action='store_true',
                                   help='Disable save game file filtering')
    sync_saves_parser.add_argument('--accept-path', dest='accept_path', action='store_true',
                                   help=argparse.SUPPRESS)

    clean_saves_parser.add_argument('--delete-incomplete', dest='delete_incomplete', action='store_true',
                                    help='Delete incomplete save files')

    import_parser.add_argument('--disable-check', dest='disable_check', action='store_true',
                               help='Disables completeness check of the to-be-imported game installation '
                                    '(useful if the imported game is a much older version or missing files)')
    import_parser.add_argument('--with-dlcs', dest='with_dlcs', action='store_true',
                               help='Automatically attempt to import all DLCs with the base game')
    import_parser.add_argument('--skip-dlcs', dest='skip_dlcs', action='store_true',
                               help='Do not ask about importing DLCs.')
    import_parser.add_argument('--platform', dest='platform', action='store', metavar='<Platform>', type=str,
                               help='Platform for import (default: Windows)')

    egl_sync_parser.add_argument('--egl-manifest-path', dest='egl_manifest_path', action='store',
                                 help='Path to the Epic Games Launcher\'s Manifests folder, should '
                                      'point to /ProgramData/Epic/EpicGamesLauncher/Data/Manifests')
    egl_sync_parser.add_argument('--egl-wine-prefix', dest='egl_wine_prefix', action='store',
                                 help='Path to the WINE prefix the Epic Games Launcher is installed in')
    egl_sync_parser.add_argument('--egl-installations', dest='egl_installations', action='store', metavar='<path>',
                                 help='Path to the new Epic Games Launcher\'s installations.jsonl, if it is not '
                                      'found automatically (e.g. in a WINE prefix)')
    egl_sync_parser.add_argument('--enable-sync', dest='enable_sync', action='store_true',
                                 help='Enable automatic EGL <-> Heirloom sync')
    egl_sync_parser.add_argument('--disable-sync', dest='disable_sync', action='store_true',
                                 help='Disable automatic sync and exit')
    egl_sync_parser.add_argument('--one-shot', dest='one_shot', action='store_true',
                                 help='Sync once, do not ask to setup automatic sync')
    egl_sync_parser.add_argument('--import-only', dest='import_only', action='store_true',
                                 help='Only import games from EGL (no export)')
    egl_sync_parser.add_argument('--export-only', dest='export_only', action='store_true',
                                 help='Only export games to EGL (no import)')
    egl_sync_parser.add_argument('--migrate', dest='migrate', action='store_true',
                                 help='Import games into heirloom, then remove them from EGL '
                                      '(implies --import-only --one-shot --unlink)')
    egl_sync_parser.add_argument('--unlink', dest='unlink', action='store_true',
                                 help='Disable sync and remove EGL metadata from installed games')

    status_parser.add_argument('--offline', dest='offline', action='store_true',
                               help='Only print offline status information, do not login')
    status_parser.add_argument('--json', dest='json', action='store_true',
                               help='Show status in JSON format')

    clean_parser.add_argument('--keep-manifests', dest='keep_manifests', action='store_true',
                              help='Do not delete old manifests')

    info_parser.add_argument('--offline', dest='offline', action='store_true',
                             help='Only print info available offline')
    info_parser.add_argument('--json', dest='json', action='store_true',
                             help='Output information in JSON format')
    info_parser.add_argument('--platform', dest='platform', action='store', metavar='<Platform>', type=str,
                             help='Platform to fetch info for (default: installed or Windows)')

    store_group = activate_parser.add_mutually_exclusive_group(required=True)
    store_group.add_argument('-U', '--uplay', dest='uplay', action='store_true',
                             help='Activate Uplay/Ubisoft Connect titles on your Ubisoft account '
                                  '(Uplay install not required)')
    store_group.add_argument('-O', '--origin', dest='origin', action='store_true',
                             help='Activate Origin/EA App managed titles on your EA account '
                                  '(requires Origin to be installed)')

    get_token_parser.add_argument('--json', dest='json', action='store_true',
                                  help='Output information in JSON format')
    get_token_parser.add_argument('--bearer', dest='bearer', action='store_true',
                                  help='Return fresh bearer token rather than an exchange code')

    eos_overlay_parser.add_argument('action', help='Action: install, remove, enable, disable, '
                                                   'or print info about the overlay',
                                    choices=['install', 'update', 'remove', 'enable', 'disable', 'info'],
                                    metavar='<install|update|remove|enable|disable|info>')
    eos_overlay_parser.add_argument('--path', dest='path', action='store',
                                    help='Path to the EOS overlay folder to be enabled/installed to.')

    if os.name != 'nt':
        eos_overlay_parser.add_argument('--prefix', dest='prefix', action='store',
                                        help='WINE prefix to install the overlay in')
        eos_overlay_parser.add_argument('--app', dest='app', action='store',
                                        help='Use this app\'s wine prefix (if configured in config)')
    else:
        eos_overlay_parser.add_argument('--prefix', dest='prefix', action='store', help=argparse.SUPPRESS)
        eos_overlay_parser.add_argument('--app', dest='app', action='store', help=argparse.SUPPRESS)

    move_parser.add_argument('--skip-move', dest='skip_move', action='store_true',
                             help='Only change heirloom database, do not move files (e.g. if already moved)')

    playtime_parser.add_argument('app_name', nargs='?', metavar='<App Name>',
                                 help='Only show this app, including its individual sessions')
    playtime_parser.add_argument('--json', dest='json', action='store_true',
                                 help='Output information in JSON format')

    achievements_parser.add_argument('app_name', metavar='<App Name>', help='Name of the app')
    achievements_parser.add_argument('--hidden', dest='show_hidden', action='store_true',
                                     help='Show undiscovered achievements (may contain spoilers)')
    achievements_parser.add_argument('--json', dest='json', action='store_true',
                                     help='Output information in JSON format')

    plugins_parser.add_argument('action', nargs='?', default='list',
                                choices=('list', 'enable', 'disable', 'store', 'install', 'update', 'remove'),
                                help='What to do (default: list); "store" lists the plugins to install from '
                                     'github.com/tuskilicious/heirloom-plugins')
    plugins_parser.add_argument('plugin_name', nargs='?', metavar='<name>',
                                help='Plugin to enable, disable, install, update or remove')

    themes_parser.add_argument('action', nargs='?', default='list', choices=('list', 'use'),
                               help='What to do (default: list)')
    themes_parser.add_argument('theme_name', nargs='?', metavar='<name>', help='Theme to use')

    queue_parser.add_argument('action', nargs='?', default='list', choices=('list', 'add', 'remove', 'clear', 'run'),
                              help='What to do (default: list)')
    queue_parser.add_argument('app_names', nargs='*', metavar='<App Name>', help='Games to add or remove')
    queue_parser.add_argument('--updates', dest='updates', action='store_true',
                              help='With "add": queue every installed game that has an update')
    queue_parser.add_argument('--window', dest='window', metavar='<HH:MM-HH:MM>',
                              help='With "run": only download in this daily time window, e.g. "01:00-07:00" '
                                   '(default: download_window from the config, otherwise any time)')
    return parser, subparsers, install_parser, queue_parser
