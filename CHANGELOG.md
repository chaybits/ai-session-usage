# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows
[Semantic Versioning](https://semver.org/).

## [0.1.2] - 2026-10-16

### Added
- A Windows 11 Widgets Board version, for the Microsoft Store: the same helper inside a packaged app with its own Python, an Adaptive Card with the rows, bars and reset times in three sizes; a click on it refreshes.

### Changed
- The widget has its own icon instead of a generic system-monitor one: three usage bars filled to a third, two thirds and the whole way, in white, orange and red.

## [0.1.1] - 2026-10-11

### Fixed
- Claude, from the status line: after `/logout` the section stayed alive from the file the status line had left; it is left out now. A window whose reset time has passed showed its old percentage for up to eight days; it shows 0 % with its "Reset at" until Claude Code reports it again.
- Claude, from Claude Code itself: an answer without `rate_limits` hid the section as "no login"; it reads "Unexpected answer" now.
- The status-line command decoded Claude Code's input in the system code page; on a Windows machine with a non-UTF-8 code page (Turkish, for one) a non-ASCII path broke it before anything was written. It reads UTF-8 now, and still prints the status bar's line when the file cannot be written.
- A CLI that ran but gave no answer (offline, a server error) was retried only at the next refresh interval; it is retried after 30 seconds, doubling up to the interval.
- The status-line command the settings page shows for pasting had its path unquoted; a home folder with a space split it.
- A row printing "95%" could wear the warning colour (the level was judged on the unrounded number); the colour follows the printed number, in the widget and in the skin.
- Windows skin: for some failures the message named the program instead of saying what went wrong; a provider that recovered from a failure kept its message on screen; before the first answer "Loading" was drawn over the title; numbers from Claude Code's status line never aged.
- The Codex program's Windows fallback could be a relative path when `APPDATA` was unset; the helper inside the skin told Codex its version was unknown.
- A `.plasmoid` built on Windows differed from the release (the entries were sorted case-insensitively there).

### Changed
- The README: requirements before the install commands, the status-line setup under Configuration, Privacy opening with what is and is not read or sent, the settings named as the pages name them; a Turkish README beside it.

## [0.1.0] - 2026-10-10

First release.

### Added
- One card with the subscription limits of Claude Code (session, weekly and per-model caps, such as a weekly cap for one model) and of ChatGPT's Codex (the plan's windows), each with a bar, the percentage used and the time it resets.
- Claude's numbers come from Claude Code itself (asked headless, with no prompt) or, as a lighter choice, from what Claude Code passes to its status line; the widget never reads Claude Code's login.
- ChatGPT's numbers come from Codex itself, asked over its own protocol. The widget reads neither login and talks to no server.
- Rows can be hidden and reordered, also across the two services; colours for outdated, warning (80 %) and critical (95 %) numbers; fit-to-width or fixed zoom; scroll, make the widget taller or shrink the text when rows do not fit; a panel form showing the first two percentages of each service.
- Windows: the same card as a Rainmeter skin, running the same helper; it needs Rainmeter 4.5 or newer and Python 3.9 or newer.
- Installable packages on every release, built from the tag: a `.plasmoid` for KDE Plasma and an `.rmskin` for Rainmeter, each with a SHA-256 file and a build-provenance attestation.
