#!/usr/bin/env bash
# Runs every automatic test of the AI Session Usage widget; exits non-zero on any failure.
# test_qml_load.py loads the QML in a sandboxed plasmawindowed (about 15 s); test_desktop.py puts the widget on a
# real desktop in a throwaway plasmashell inside a headless KWin and sends it mouse input (about 20 s). Both say
# SKIPPED without Plasma 6. test_config_pages.py opens the settings pages in Qt's qml runtime and clicks them
# (about 2 s). test_package.py builds the .plasmoid and, with kpackagetool6, installs it into a clean data folder.
# test_msix_stage.py checks the Widgets Board package's staging and version carriers; its C# logic tests run under
# dotnet test when a .NET SDK is present. panel_check.py (the panel form, pictures to look at) and install_check.sh (a
# clean Arch container, Docker) are run by hand, not from here.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 -B "$HERE/test_package.py"
python3 -B "$HERE/test_rmskin.py"
python3 -B "$HERE/test_skin_lua.py"
python3 -B "$HERE/test_msix_stage.py"
# The Widgets Board logic (C#) under dotnet test; without a .NET SDK it only says so (the Windows CI job runs it).
if command -v dotnet >/dev/null 2>&1; then
    (cd "$HERE/../widgets-board" && dotnet test AiSessionUsage.Core.Tests)  # widgets-board/global.json opts into Microsoft.Testing.Platform
else
    echo "SKIPPED: dotnet not found, the Widgets Board logic tests (widgets-board/AiSessionUsage.Core.Tests) did not run"
fi
python3 -B "$HERE/test_fetch_usage.py"
python3 -B "$HERE/test_statusline.py"
python3 -B "$HERE/test_claudecode.py"
python3 -B "$HERE/test_codex.py"
node "$HERE/test_usage_logic.js"
python3 -B "$HERE/test_qml_load.py"
python3 -B "$HERE/test_config_pages.py"
python3 -B "$HERE/test_desktop.py"
