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

jq -e '
  .images as $images
  | def image($key): $images[] | select(.key == $key);
  def keys_before($index): [range(0; $index) as $i | $images[$i].key];
  ([.images[].depends_on // empty] - [.images[].key] | length == 0)
  and all(range(0; ($images | length)) as $i;
    ($images[$i].depends_on == null)
    or ((keys_before($i) | index($images[$i].depends_on)) != null))
  and (image("runtime").depends_on == null)
  and (image("runtime").package == "lemonade-runtime")
  and (image("rocm-runtime").depends_on == "runtime")
  and (image("rocm-runtime").package == "lemonade-rocm-runtime")
  and (image("atomic-turboquant-combined").depends_on == "rocm-runtime")
  and (image("atomic-turboquant-vulkan").depends_on == "runtime")
  and (image("cachyllama-heretek-combined").depends_on == "runtime")
  and (image("cachyllama-heretek-vulkan").depends_on == "runtime")
  and (image("rocmfpx-heretek-combined").depends_on == "runtime")
' "$manifest" >/dev/null

if grep -RInE '^(ARG BASE_IMAGE=lemonade-rocm-runtime|ENV .*(/opt/rocm|rocm))' \
  forks/cachyllama-heretek forks/rocmfpx-heretek; then
  echo "Heretek Dockerfiles must not inherit or set the shared /opt/rocm runtime; their archives bundle ROCm libraries." >&2
  exit 1
fi

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

.github/scripts/check-gpu-groups.sh

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
