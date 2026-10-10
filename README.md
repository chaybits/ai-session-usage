# ai-session-usage

English | [Türkçe](README.tr.md)

A KDE Plasma 6 widget and a Windows Rainmeter skin showing your Claude Code and ChatGPT (Codex) subscription limits, with reset times.

![The card on a KDE Plasma desktop: three Claude rows, Session (5hr), Weekly (7 day) and Weekly (Fable), and two ChatGPT rows, each with a percentage, a bar and its reset time. Example values.](docs/01-claude-and-chatgpt.png)

## Install

You need:

- Python 3.9 or newer on the `PATH` (as `python3` on Linux, `python` on Windows).
- Claude Code, logged in with a Claude subscription, or the Codex CLI, logged in with a ChatGPT account. One is enough; a provider you are not logged in to is left out.

No extra dependencies: the helper uses only the Python standard library.

### KDE Plasma 6 (Linux)

Requires KDE Plasma 6. Download the `.plasmoid` and its `.sha256` file from the [latest release](https://github.com/chaybits/ai-session-usage/releases/latest), then, in the folder you saved them to (the `*` assumes one downloaded package there):

```
sha256sum -c ai-session-usage-*.plasmoid.sha256
kpackagetool6 --type Plasma/Applet --install ai-session-usage-*.plasmoid
```

The first line prints the file's name followed by `OK`. **AI Session Usage** should now appear in the widget list (**Add or Manage Widgets…** in the right-click menu of the desktop or of a panel): add it to the desktop or a panel. To update, run the same command with `--upgrade` instead of `--install`; to remove it, `kpackagetool6 --type Plasma/Applet --remove io.github.chaybits.aisessionusage`.

By default the widget asks Claude Code itself for its usage; a lighter source, Claude Code's status line, is chosen with **From:** in the settings (see Claude source under Configuration).

### Windows (Rainmeter)

Requires [Rainmeter](https://www.rainmeter.net/) 4.5 or newer, and Python as `python` on the `PATH` (any 3.9 or newer: the installer from python.org with "Add to PATH" ticked, or `winget install Python.Python.3.12`; a `python` that opens the Microsoft Store is not an install). Download the `.rmskin` and its `.sha256` file from the [latest release](https://github.com/chaybits/ai-session-usage/releases/latest). In PowerShell, in the folder you saved them to, this prints `True` when the file is intact (`False`: download it again):

```
(Get-FileHash ai-session-usage-*.rmskin).Hash -eq (Get-Content ai-session-usage-*.rmskin.sha256).Split()[0]
```

Then open the `.rmskin`: Rainmeter's Skin Installer shows the package (ai-session-usage, by chaybits), and **Install** puts the card on the desktop. If it does not appear, load it from Rainmeter's **Manage** window.

![The same card as a Rainmeter skin on a Windows desktop. Example values.](docs/02-windows.png)

### From source

From a clone, `python3 scripts/build_plasmoid.py` writes the same `.plasmoid` to `dist/`, or install the folder directly with `kpackagetool6 --type Plasma/Applet --install src`. For development, link the folder instead, so an edit is live after `systemctl --user restart plasma-plasmashell.service`:

```
ln -s "$PWD/src" ~/.local/share/plasma/plasmoids/io.github.chaybits.aisessionusage
```

On Windows, `python scripts/build_rmskin.py` writes the same `.rmskin` to `dist/`.

## Usage

Each row is one limit: the percentage used, a bar, and when it resets ("Resets in 2h 3m · 14:05"; a weekday or a date when it is further away). The labels are the services' own: "Session (5hr)", "Weekly (7 day)", and a per-model weekly cap such as "Weekly (Fable)" when your plan has one. With both providers logged in, the card has a Claude section and a ChatGPT section, each in the order the service reports its limits, until you choose another order (see **Order** below).

- **Click** anywhere on the card to refresh (at most once every 10 seconds); it also refreshes every 5 minutes by default (**Refresh every (minutes)** in the settings). Each refresh starts both tools (Claude Code for about two seconds, Codex for under a second), which briefly uses CPU and the network.
- **Right-click** for the widget's menu (refresh now, configure, remove).
- **Order:** in the settings, rows can be moved up and down, also between the two services: put both session rows first, say. While each service's rows stay together the card keeps its sections; once they are mixed it is one list, and each row is named "Claude · Session (5hr)".
- **In a panel** the widget shows the first two percentages of each provider, Claude | ChatGPT ("13% · 40% | 12% · 30%"), in your order; clicking opens the full card. The tooltip lists every row.
- **Colours:** a percentage turns orange at 80 % and red at 95 %. Numbers older than 15 minutes turn yellow, and a provider whose last refresh failed is dimmed with the reason underneath. All three colours can be changed.

Both session rows first, the services mixed:

![One list mixing Claude and ChatGPT rows, both session rows first, each row named with its service](docs/03-mixed-order.png)

Claude's rows reordered to Weekly (Fable), Weekly (7 day), Session (5hr):

![Claude's rows in the order Weekly (Fable), Weekly (7 day), Session (5hr)](docs/04-claude-reordered.png)

A session at 86 % in orange and a weekly limit at 97 % in red:

![Claude's rows with the session at 86 % drawn orange and the weekly limit at 97 % drawn red](docs/05-claude-levels.png)

On Windows, click the skin to refresh; it also refreshes every 5 minutes. Row order, the panel form and the settings pages exist only in the Plasma widget; the skin's settings are its variables (see Configuration).

## Configuration

Right-click the widget, **Configure AI Session Usage…**. The settings, named as the pages name them:

| Page | Setting | Default |
|---|---|---|
| General | Refresh every (minutes) | 5 |
| General | Claude Code: Show the Claude Code limits | on |
| General | Claude Code: From | Claude Code itself; or Claude Code's status line |
| General | Claude Code program | `claude`, found on the PATH |
| General | Claude Code: Login file (only checked to exist) | `$CLAUDE_CONFIG_DIR/.credentials.json` or `~/.claude/.credentials.json` |
| General | ChatGPT (Codex): Show the ChatGPT (Codex) limits | on |
| General | Codex program | `codex`, found on the PATH |
| General | ChatGPT (Codex): Login file (only checked to exist) | `$CODEX_HOME/auth.json` or `~/.codex/auth.json` |
| Rows | Untick a row to hide it (for example a per-model cap); the arrows move it; **Default order** resets the order | all shown, each service's rows in its own order |
| Appearance | Size | Fit to the widget's width (resize it to zoom); or Fixed zoom |
| Appearance | When the rows do not fit | Scroll; or Make the widget taller, Shrink the text to fit |
| Appearance | Mark numbers as outdated after; Outdated colour | 15 minutes; yellow |
| Appearance | Warning colour from; Warning colour | 80 %; orange |
| Appearance | Critical colour from; Critical colour | 95 %; red |

The two login-file fields are presence checks only; the files are never read. `CLAUDE_CONFIG_DIR` and `CODEX_HOME` are read from the environment Plasma runs in, not from your shell; if you set either in a shell profile only, enter the file in the settings instead.

### Claude source

By default the widget asks Claude Code itself for its usage: it runs `claude` once per refresh, with no prompt, so it never touches your login, and every limit Claude Code knows is shown, per-model caps included. Claude Code must be installed and logged in.

The lighter choice takes the numbers Claude Code passes to its status line instead (5-hour and weekly only, as fresh as Claude Code's last answer). Under **Claude Code**, set **From:** to **Claude Code's status line**, then add the `statusLine` entry to `~/.claude/settings.json` (the settings page shows it with your path filled in):

```json
{"statusLine": {"type": "command", "command": "python3 -B ~/.local/share/plasma/plasmoids/io.github.chaybits.aisessionusage/contents/code/statusline_tap.py"}}
```

If the file already has other keys, add only the `statusLine` entry inside its braces; do not add a second `statusLine` key. Claude Code's status bar then shows "5h 34% · 7d 61%", and the widget fills in after Claude Code's next answer. If you already have a status line, keep it by appending your command:

```
python3 -B ~/.local/share/plasma/plasmoids/io.github.chaybits.aisessionusage/contents/code/statusline_tap.py --then "<your command>"
```

### Windows

On Windows the settings are the skin's variables: in Rainmeter's **Manage** window select the skin, click **Edit**, change a value, save, and click **Refresh**. They are `RefreshMinutes` (5), `ShowClaude` and `ShowCodex` (1, or 0 to hide), `ClaudeSource` (`claudecode` or `statusline`), `ClaudeProgram` and `CodexProgram` (empty: found on the `PATH`), `WarnPercent` (80), `CriticalPercent` (95), `StaleMinutes` (15), and the colours. The status-line source needs the same `statusLine` entry in `%USERPROFILE%\.claude\settings.json`, pointing at the skin's copy of the script, `Documents\Rainmeter\Skins\AiSessionUsage\@Resources\code\statusline_tap.py` (in JSON, write each backslash twice); the numbers are kept in `%LOCALAPPDATA%\ai-session-usage\claude-statusline.json`.

## Privacy

The widget opens no connection of its own. The two command-line tools it runs contact their own services, each with its own login. No login file is read; each is only checked to exist, so that someone without that tool sees no section for it. In status-line mode one cache file is written, holding percentages and reset times only. A refresh sends no prompt and opens no conversation, so it spends none of the limits it shows. The Windows skin runs the same helper, so all of this holds there too.

### How each source works

**Claude, from Claude Code itself (the default).** The widget runs `claude` headless with one request, the usage request, and no prompt, with hooks and MCP servers turned off and the session not saved. Claude Code asks Anthropic with its own login and answers with the limits.

**Claude, from the status line.** Claude Code runs `statusline_tap.py` as its status line and hands it a description of the session. The script keeps only the usage windows in it (percentages and reset times) and the time it saw them, in `~/.cache/ai-session-usage/claude-statusline.json`; nothing else of the session is written. The widget reads that file. No request is made.

**ChatGPT, from Codex itself.** The widget runs `codex app-server` and sends one request, `account/rateLimits/read`: the numbers Codex's `/status` shows. Codex asks OpenAI with its own login and answers; the widget closes the connection and Codex exits.

The helper is `src/contents/code/`, standard-library Python only; anyone can read it. It writes nothing to disk except the status-line file above, and prints no token in any output, error or log: it never holds one.

This is not an official Anthropic or OpenAI product. The services' terms: Anthropic's [Claude Code legal and compliance](https://code.claude.com/docs/en/legal-and-compliance) and OpenAI's [Terms of Use](https://openai.com/policies/terms-of-use/). Either provider can be turned off in the settings.

## Known limitations

- Both tools are asked over requests their makers mark experimental or document only for their own clients; if one changes, that section shows "Unexpected answer" until the widget is updated.
- From Claude Code's status line, the numbers are as fresh as Claude Code's last answer: with no session running they stay as they were, shown with the time they were seen, and a window whose reset has passed shows 0 % until Claude Code reports it again. The status line carries the 5-hour and weekly limits only; per-model caps need the default source, Claude Code itself.
- KDE Plasma 6 on Linux, and Windows through Rainmeter; not macOS, where Claude Code keeps its login in the Keychain, so the check for a login file would find none.
- On Windows the skin shows times in 24-hour form whatever the regional settings, and has no row order, panel form or settings pages: those are the Plasma widget's.
- Subscription logins only: an API-key login has no subscription limits to show.
- For ChatGPT, the rows are the limits the signed-in Codex CLI reports; the message caps of ordinary ChatGPT chat are not among them.
- Usage made elsewhere (claude.ai, the ChatGPT apps) counts against the same limits but appears only at the next refresh, up to one refresh interval away, or at once on a click.
- The interface is in English only.

## License

GPL-3.0-or-later (see [`LICENSE`](LICENSE)).
