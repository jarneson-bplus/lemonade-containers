#!/usr/bin/env bash
set -euo pipefail

manifest="${1:-.github/image-matrix.json}"

jq -e . "$manifest" >/dev/null

jq -e '
  .schema_version == 1
  and (.upstream.lemonade_server.version | test("^v[0-9]+\\.[0-9]+\\.[0-9]+$"))
  and (.upstream.lemonade_server.image
    == "ghcr.io/lemonade-sdk/lemonade-server:" + .upstream.lemonade_server.version)
  and (.upstream.rocm.version | test("^[0-9]+\\.[0-9]+\\.[0-9]+$"))
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

# Version pins must stay consistent across upstream, tags, and the BASE_IMAGE
# references that chain the images together.
jq -e '
  .upstream.lemonade_server as $lemonade
  | .upstream.rocm as $rocm
  | .images as $images
  | def image($key): ($images[] | select(.key == $key));
  def build_arg($img; $name): ($img.build_args[] | select(startswith($name + "=")) | ltrimstr($name + "="));
  (image("runtime").default_tag == "lemonade-" + $lemonade.version)
  and (build_arg(image("runtime"); "BASE_IMAGE") == $lemonade.image)
  and (image("rocm-runtime").default_tag == "rocm-" + $rocm.version)
  and (build_arg(image("rocm-runtime"); "ROCM_VERSION") == $rocm.version)
  and (build_arg(image("rocm-runtime"); "UBUNTU_CODENAME") == $rocm.ubuntu_codename)
  and all($images[] | select(.depends_on != null);
    . as $img
    | build_arg($img; "BASE_IMAGE") == (image($img.depends_on) | .package + ":" + .default_tag))
  and all($images[];
    all(.build_args[] | select(test("_SHA256=")); split("=")[1] | test("^[0-9a-f]{64}$")))
' "$manifest" >/dev/null

jq -e '
  .images as $images
  | def image($key): $images[] | select(.key == $key);
  def keys_before($index): [range(0; $index) as $i | $images[$i].key];
  ([.images[].depends_on // empty] - [.images[].key] | length == 0)
  and all(range(0; ($images | length)); . as $i |
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

# Each Dockerfile's ARG BASE_IMAGE default must match the manifest, so a
# dependency bump that rewrites the manifest cannot leave stale documentation
# defaults behind.
while IFS= read -r image; do
  key="$(jq -r '.key' <<<"$image")"
  dockerfile="$(jq -r '.dockerfile' <<<"$image")"
  depends_on="$(jq -r '.depends_on // ""' <<<"$image")"

  if [[ -n "$depends_on" ]]; then
    expected="$(jq -r --arg key "$depends_on" '.[] | select(.key == $key) | .package + ":" + .default_tag' <<<"$images_with_paths")"
  else
    expected="$(jq -r '.upstream.lemonade_server.image' "$manifest")"
  fi

  actual="$(sed -n 's/^ARG BASE_IMAGE=//p' "$dockerfile" | head -n 1)"
  if [[ "$actual" != "$expected" ]]; then
    echo "Image '$key' Dockerfile $dockerfile has ARG BASE_IMAGE default '$actual', expected '$expected'." >&2
    exit 1
  fi
done < <(jq -c '.[]' <<<"$images_with_paths")

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

if command -v python3 >/dev/null 2>&1; then
  python3 .github/scripts/update_dependencies.py --manifest "$manifest" --validate-config
else
  echo "python3 is not available; skipping update_sources configuration validation."
fi

if command -v actionlint >/dev/null 2>&1; then
  actionlint
else
  echo "actionlint is not available; skipping workflow semantic validation."
fi
