#!/usr/bin/env bash
# The install test on a machine that is not this one, by hand: a clean Arch Linux container with Plasma 6 from
# its repositories, a fresh user, the README's install steps on the built package (checksum, kpackagetool6),
# and the widget loaded headless for 30 s; the widget itself must have run the helper for both providers,
# which is seen through a python3 wrapper on the user's PATH that records every run. Needs Docker; about 1 GB
# is downloaded into a throwaway container (the base image stays unless --rm-image is given).
# Usage: bash tests/install_check.sh [--rm-image]    (about 10 min; prints one verdict line and the log's path)
# publish-safe:path-placeholders: /home/tester is the container's throwaway user, not a machine of anyone's.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
OUT="${TMPDIR:-/tmp}/ai-session-usage-install-check"
rm -rf "$OUT"
mkdir -p "$OUT/dist"
python3 -B "$ROOT/scripts/build_plasmoid.py" --out "$OUT/dist" >/dev/null

cat > "$OUT/inside.sh" <<'EOF'
set -eu
pacman -Syu --noconfirm --needed plasma-workspace plasma5support kcmutils kirigami kpackage python dbus ttf-dejavu \
  > /pkg/pacman.log 2>&1
useradd -m tester
mkdir -p /home/tester/bin
# the widget runs "python3 -B <helper>"; this wrapper is found first, records the run, and hands over
cat > /home/tester/bin/python3 <<'PY'
#!/bin/sh
echo "$@" >> /home/tester/python3-runs.log
exec /usr/bin/python3 "$@"
PY
chmod 755 /home/tester/bin/python3
chown -R tester:tester /home/tester
su tester -c '
set -eu
cd /home/tester
export PATH=/home/tester/bin:$PATH XDG_RUNTIME_DIR=/tmp/run-tester
export QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software QT_FORCE_STDERR_LOGGING=1
mkdir -p -m 700 "$XDG_RUNTIME_DIR"
echo "--- checksum"; (cd /pkg && sha256sum -c ./*.sha256)
echo "--- install"; kpackagetool6 --type Plasma/Applet --install /pkg/ai-session-usage-*.plasmoid
echo "--- show"; kpackagetool6 --type Plasma/Applet --show io.github.chaybits.aisessionusage
echo "--- plasmawindowed (30 s)"
dbus-run-session -- timeout 30 plasmawindowed io.github.chaybits.aisessionusage > /home/tester/plasmawindowed.log 2>&1 || true
cat /home/tester/plasmawindowed.log
echo "--- helper runs:"; cat /home/tester/python3-runs.log 2>/dev/null || echo none
'
EOF

status=0
docker run --rm -v "$OUT/dist:/pkg" -v "$OUT/inside.sh:/inside.sh:ro" archlinux:latest bash /inside.sh \
  > "$OUT/run.log" 2>&1 || status=$?
[ "${1:-}" = "--rm-image" ] && docker rmi archlinux:latest >/dev/null 2>&1 || true

verdict=PASS
[ "$status" = 0 ] || verdict="FAIL (container exit $status)"
grep -q "error when loading applet" "$OUT/run.log" && verdict="FAIL (QML error)"
grep -q -- "fetch_usage.py --provider claude" "$OUT/run.log" || verdict="FAIL (the widget never ran the Claude helper)"
grep -q -- "fetch_usage.py --provider codex" "$OUT/run.log" || verdict="FAIL (the widget never ran the Codex helper)"
echo "$verdict  log: $OUT/run.log"
[ "$verdict" = PASS ]
