#!/usr/bin/env bash
set -euo pipefail

manifest="${1:-.github/image-matrix.json}"

# Derived images normally build FROM a locally built base; for a syntax-only
# check, substitute the pinned upstream Lemonade image from the manifest.
base_image="$(jq -r '.upstream.lemonade_server.image' "$manifest")"

while IFS= read -r image; do
  key="$(jq -r '.key' <<<"$image")"
  dockerfile="$(jq -r '.dockerfile' <<<"$image")"
  context="$(jq -r '.context' <<<"$image")"

  build_args=()
  while IFS= read -r arg; do
    build_args+=(--build-arg "$arg")
  done < <(jq -r '.build_args[]' <<<"$image")

  if [[ "$(jq -r '.depends_on // ""' <<<"$image")" != "" ]]; then
    build_args+=(--build-arg "BASE_IMAGE=${base_image}")
  fi

  echo "::group::BuildKit check: $key"
  docker buildx build \
    --call=check \
    --file "$dockerfile" \
    "${build_args[@]}" \
    "$context"
  echo "::endgroup::"
done < <(.github/scripts/manifest-images-with-paths.sh "$manifest" | jq -c '.[]')
