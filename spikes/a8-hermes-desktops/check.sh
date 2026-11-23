#!/usr/bin/env bash
set -euo pipefail

# Published Hermes v0.22.2 desktop manifest for linux/arm64 and linux/amd64.
image='nousresearch/hermes-agent@sha256:79c98751d8d772ac0f7bfc31a75b123b9cfac254c2e15e4d0ac8762d6b119212'
workers=(research developer writer operator reviewer)
prefix="jarvis-desktop-fixture-$$"
active=()
cleanup() {
  for name in "${active[@]}"; do
    docker stop --time 4 "$name" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for worker in "${workers[@]}"; do
  name="${prefix}-${worker}"
  docker run -d --rm --pull never --name "$name" --label org.superagent.purpose=desktop-fixture \
    --network none --user 10000:10000 --cap-drop ALL --security-opt no-new-privileges \
    --memory 1800m --cpus 1 --env XDG_RUNTIME_DIR=/tmp/jarvis-xdg \
    --entrypoint /bin/sleep "$image" infinity >/dev/null
  active+=("$name")
  docker exec "$name" sh -c 'test "$(id -u)" = 10000 && test ! -e /sys/class/net/eth0 && test "$(wc -l </proc/net/route)" -eq 1'
  docker exec "$name" sh -c 'printf "%s" "$1" >/opt/data/jarvis-role' marker "$worker"
  docker exec "$name" hermes computer-use screen start
done

unique_mounts="$(for name in "${active[@]}"; do docker inspect --format '{{range .Mounts}}{{.Source}}{{end}}' "$name"; done | sort -u | wc -l | tr -d ' ')"
test "$unique_mounts" = "${#workers[@]}"
for worker in "${workers[@]}"; do
  name="${prefix}-${worker}"
  docker exec "$name" sh -c 'test "$(cat /opt/data/jarvis-role)" = "$1" && test -S /opt/data/bot-desktop/rfb.sock' check "$worker"
done
printf '%s\n' 'Verified five isolated desktop sockets and five independent data volumes.'
