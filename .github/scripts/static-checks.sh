#!/usr/bin/env bash
set -euo pipefail

manifest="${1:-.github/image-matrix.json}"

jq -e . "$manifest" >/dev/null

jq -e '
  .schema_version == 1
  and (.upstream.lemonade_server.image == "ghcr.io/lemonade-sdk/lemonade-server:v11.9.0")
  and (.upstream.rocm.version == "7.2.1")
  and (.images | length > 0)
  and ([.images[].key] | length == (unique | length))
  and ([.images[].cache_scope] | length == (unique | length))
  and all(.images[]; (.key | length > 0)
    and (.package | length > 0)
    and (.dockerfile | length > 0)
    and (.context | length > 0)
    and (.default_tag | length > 0)
    and (.build_args | type == "array")
    and all(.build_args[]; test("^[A-Z0-9_]+=")))
' "$manifest" >/dev/null

images_with_paths="$(.github/scripts/manifest-images-with-paths.sh "$manifest")"

bake_json="$(LEMONADE_BAKE_DRY_RUN=1 .github/scripts/full-build-no-push.sh "$manifest")"
jq -e --argjson images "$images_with_paths" '
  . as $bake
  | all($images[]; $bake.target[.key].dockerfile == .dockerfile_context_relative)
' <<<"$bake_json" >/dev/null

while IFS= read -r -d '' file; do
  jq -e . "$file" >/dev/null
done < <(find base forks -name '*.json' -print0)

sh -n base/docker-entrypoint.sh

if grep -RIn --include='Dockerfile*' --include='*.yml' --include='*.yaml' --include='*.json' \
  'lemonade-server:[l]atest' base forks .github; then
  echo "Floating Lemonade Server image tags are not allowed; pin an explicit release tag." >&2
  exit 1
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  docker compose -f docker-compose.yml config >/dev/null
else
  echo "docker compose is not available; skipping Compose parser validation."
fi

if command -v actionlint >/dev/null 2>&1; then
  actionlint
else
  echo "actionlint is not available; skipping workflow semantic validation."
fi
