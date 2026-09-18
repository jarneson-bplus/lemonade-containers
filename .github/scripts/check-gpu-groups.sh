#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -gt 0 ]]; then
  dockerfiles=("$@")
else
  mapfile -d '' dockerfiles < <(find base forks -name 'Dockerfile*' -print0)
fi

failed=0

for dockerfile in "${dockerfiles[@]}"; do
  awk -v file="$dockerfile" '
    /groupadd[[:space:]][^&|;]*(-f[[:space:]]+)?render/ || /getent[[:space:]]+group[[:space:]]+render/ {
      render = 1
    }
    /groupadd[[:space:]][^&|;]*(-f[[:space:]]+)?video/ || /getent[[:space:]]+group[[:space:]]+video/ {
      video = 1
    }
    /usermod[[:space:]].*-aG[[:space:]]+render,video[[:space:]]+lemonade/ {
      if (!render || !video) {
        printf "%s:%d: usermod adds lemonade to render/video before both groups are created idempotently\n", file, NR
        failed = 1
      }
    }
    END {
      exit failed
    }
  ' "$dockerfile" || failed=1
done

if [[ "$failed" -ne 0 ]]; then
  echo "Dockerfiles must create both render and video groups before running usermod -aG render,video lemonade." >&2
  exit 1
fi
