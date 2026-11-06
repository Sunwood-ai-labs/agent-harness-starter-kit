#!/usr/bin/env bash
# Build the lab and run every check. Works with rootless Podman on Linux, or
# Podman Desktop / podman machine on Windows and macOS.
#
#   lab/run-lab.sh                 # build, run tests, leave containers up
#   lab/run-lab.sh --clean         # remove the lab containers and volumes
#
# Environment:
#   CONTAINER_CONNECTION  podman machine/connection to use (optional)
#   LAB_E2E_OPENCODE=1    also ask a real OpenCode agent to delete files
#                         (uses OpenCode's free hosted model; sends only the
#                         test prompt)
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE=localhost/harness-kit-lab:1.0
AGENT=harness-kit-agent
T3=harness-kit-t3
NET=harness-kit-net
P=(podman)

if [ "${1:-}" = "--clean" ]; then
  "${P[@]}" rm -f "$AGENT" "$T3" >/dev/null 2>&1 || true
  "${P[@]}" volume rm -f harness-kit-protected harness-kit-work >/dev/null 2>&1 || true
  echo "removed lab containers and volumes"
  exit 0
fi

echo "== build"
"${P[@]}" build -q -t "$IMAGE" -f lab/Containerfile . >/dev/null

echo "== area C: seed the originals volume (read-only for the agent)"
"${P[@]}" volume create --ignore harness-kit-protected >/dev/null
"${P[@]}" volume create --ignore harness-kit-work >/dev/null
"${P[@]}" run --rm --user 0 -v harness-kit-protected:/protected "$IMAGE" sh -c \
  'mkdir -p /protected/2025 && for i in 1 2 3; do echo "原本 $i" > /protected/2025/master-$i.txt; done && chown -R 0:0 /protected && chmod -R a-w /protected'

echo "== start the agent container"
"${P[@]}" rm -f "$AGENT" >/dev/null 2>&1 || true
"${P[@]}" run -d --name "$AGENT" \
  --cap-drop=all --security-opt=no-new-privileges \
  --pids-limit=256 --memory=2g --cpus=2 \
  -v harness-kit-protected:/protected:ro \
  -v harness-kit-work:/workspace \
  "$IMAGE" >/dev/null

echo "== versions"
"${P[@]}" exec "$AGENT" sh -c 'echo "claude $(claude --version)"; echo "codex $(codex --version)"; echo "opencode $(opencode --version)"; echo "t3 $(t3 --version 2>/dev/null || npm ls -g t3 --depth=0 | grep t3)"; python3 --version'

echo "== accident tests"
set +e
"${P[@]}" exec "$AGENT" bash /kit/lab/accident-tests.sh
status=$?
set -e

echo
echo "== network: area A sandbox (--network none) cannot send data out"
if "${P[@]}" run --rm --network none "$IMAGE" curl -sS -m 10 -X POST https://example.com -d test >/dev/null 2>/tmp/harness-kit-net.err; then
  echo "FAIL: POST succeeded from the no-network sandbox"; status=1
else
  echo "PASS: $(head -1 /tmp/harness-kit-net.err)"
fi
echo "== network: the agent container can still read the web (search, docs, downloads)"
if code=$("${P[@]}" exec "$AGENT" curl -sS -m 20 -o /dev/null -w '%{http_code}' https://example.com); then
  echo "PASS: GET https://example.com -> $code"
else
  echo "FAIL: web access from the agent container"; status=1
fi

echo
echo "== runaway processes: throwaway container with --pids-limit=64"
# Not inside $AGENT: its cleanup used to kill the container's own sleep, and a
# runaway test should never endanger the container being tested. --rm discards
# the whole thing afterwards; the sleeps expire on their own (sleep 30).
runaway=$(timeout 240 "${P[@]}" run --rm --pids-limit=64 "$IMAGE" bash -c \
  'echo "pids.max=$(cat /sys/fs/cgroup/pids.max 2>/dev/null)"; for i in $(seq 1 600); do sleep 30 & done; wait' 2>&1 || true)
echo "$runaway" | grep -m1 -E "^pids\.max=" | sed 's/^/  runaway| /'
echo "$runaway" | grep -m1 -iE "resource|fork" | sed 's/^/  runaway| /'
if echo "$runaway" | grep -q "^pids\.max=64$" && echo "$runaway" | grep -qiE "resource temporarily unavailable|fork"; then
  echo "PASS: 600 processes cannot run past pids.max=64 (throwaway container, already removed)"
else
  echo "FAIL: the pids limit did not stop the runaway processes"; status=1
fi

echo
echo "== config files are read by the CLIs"
"${P[@]}" exec -w /workspace/demo "$AGENT" sh -c 'opencode debug config 2>/dev/null | python3 -c "import sys,json;c=json.load(sys.stdin);p=c.get(\"permission\",{});print(\"opencode permission.bash[git push*] =\",p.get(\"bash\",{}).get(\"git push*\"));print(\"opencode permission.external_directory =\",p.get(\"external_directory\"))"' || { echo "FAIL: opencode debug config"; status=1; }

if [ "${LAB_E2E_OPENCODE:-0}" = 1 ]; then
  echo
  echo "== e2e: a real OpenCode agent is asked to delete docs/ and push"
  bash lab/e2e-opencode.sh "$AGENT" || status=1
fi

echo
echo "== T3 Code in its own container"
"${P[@]}" rm -f "$T3" >/dev/null 2>&1 || true
"${P[@]}" run -d --name "$T3" --cap-drop=all --security-opt=no-new-privileges --pids-limit=512 --memory=2g \
  -p 127.0.0.1:37730:3773 "$IMAGE" t3 serve --host 0.0.0.0 --port 3773 --base-dir /home/dev/.t3 >/dev/null
t3_ok=0
for _ in $(seq 1 45); do
  if "${P[@]}" exec "$T3" curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3773/ 2>/dev/null | grep -qE '^(200|30[0-9]|401)$'; then
    echo "PASS: t3 serve answers on port 3773 inside $T3 (host: http://127.0.0.1:37730/)"
    t3_ok=1
    break
  fi
  sleep 2
done
[ "$t3_ok" = 1 ] || { echo "FAIL: t3 serve did not answer on port 3773"; status=1; }
"${P[@]}" logs --tail 15 "$T3" 2>&1 | sed 's/^/  t3| /'
echo "Pairing a browser needs a one-time link:  podman exec $T3 t3 auth pairing create --base-dir /home/dev/.t3"

exit $status
