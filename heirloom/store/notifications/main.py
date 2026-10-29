"""A desktop notification when a game finishes installing or updating, from the window's updates too"""
import os
import subprocess
import sys

# a Windows toast, from the HL_* variables so no game title is ever part of the script; it is shown as
# coming from Windows PowerShell, as an app needs to be registered with Windows to show its own
TOAST = '''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$toast = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
    [Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$text = $toast.GetElementsByTagName('text')
$text.Item(0).AppendChild($toast.CreateTextNode($env:HL_TITLE)) > $null
$text.Item(1).AppendChild($toast.CreateTextNode($env:HL_TEXT)) > $null
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show(
    [Windows.UI.Notifications.ToastNotification]::new($toast))
'''


def notify(title, text):
    if sys.platform == 'win32':
        command = ['powershell', '-NoProfile', '-NonInteractive', '-Command', TOAST]
        options = {'env': os.environ | {'HL_TITLE': title, 'HL_TEXT': text},
                   'creationflags': subprocess.CREATE_NO_WINDOW}
    elif sys.platform == 'darwin':
        command = ['osascript', '-e', 'on run argv', '-e',
                   'display notification (item 2 of argv) with title (item 1 of argv)', '-e', 'end run', title, text]
        options = {}
    else:
        command, options = ['notify-send', '--app-name=Heirloom', title, text], {}
    subprocess.run(command, capture_output=True, timeout=30, check=True, **options)


def setup(plugin):
    def send(title, text):
        try:
            notify(title, text)
        except (OSError, subprocess.SubprocessError) as e:
            plugin.log.warning(f'Could not show a notification: {e!r}')

    plugin.on('game_installed', lambda event: send(f'{event.game.title} is installed', 'Ready to play.'))
    plugin.on('game_updated', lambda event: send(f'{event.game.title} is updated',
                                                 f'Version {event.game.version}, ready to play.'))
