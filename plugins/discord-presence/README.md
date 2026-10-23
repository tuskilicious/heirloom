# Discord Rich Presence

Shows the game you started with `heirloom launch` in your Discord status while you play: "Playing Heirloom", with the
game's title and the time played so far.
It talks to the Discord app running on the same computer, so it needs no Discord login, and it never holds up a launch:
if Discord isn't running or doesn't answer, the game starts anyway.

## Install

1. Copy this `discord-presence` folder into Heirloom's plugins folder (`heirloom plugins` shows where it is).
2. Turn it on with `heirloom plugins enable discord-presence`.

## Your own Discord application

The status shows the name and icon of Heirloom's Discord application. To show another name, use your own:

1. Open the [Discord Developer Portal](https://discord.com/developers/applications) and choose **New Application**.
   Its name is what your status shows.
2. Copy the **Application ID** from its General Information page.
3. Set it in the environment Heirloom runs in, e.g. `setx HEIRLOOM_DISCORD_CLIENT_ID <id>` on Windows
   or `export HEIRLOOM_DISCORD_CLIENT_ID=<id>` in your shell profile on Linux and macOS.

## Notes

- The status shows while `heirloom launch` waits for the game, and clears when it exits.
  With `--no-wait` (or `disable_playtime_tracking`) Heirloom exits right after starting the game, and so does the status.
- Run Heirloom with `-v` to see whether the status was shown, or why not (e.g. Discord isn't running).
