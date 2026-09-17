#!/usr/bin/env bash
set -euo pipefail

manifest="${1:-.github/image-matrix.json}"
bake_file="${RUNNER_TEMP:-/tmp}/lemonade-images.bake.json"
targets_file="$(mktemp)"
trap 'rm -f "$targets_file"' EXIT

while IFS= read -r image; do
  key="$(jq -r '.key' <<<"$image")"
  package="$(jq -r '.package' <<<"$image")"
  context="$(jq -r '.context' <<<"$image")"
  dockerfile_relative="$(jq -r '.dockerfile_relative' <<<"$image")"
  default_tag="$(jq -r '.default_tag' <<<"$image")"
  cache_scope="$(jq -r '.cache_scope' <<<"$image")"
  depends_on="$(jq -r '.depends_on // ""' <<<"$image")"

  args="$(
    jq -c '
      .build_args
      | map(split("=") | {(.[0]): (.[1:] | join("="))})
      | add // {}
    ' <<<"$image"
  )"
  contexts="{}"

  if [[ "$depends_on" == "base" ]]; then
    args="$(jq -c '. + {"BASE_IMAGE": "lemonade-rocm-runtime:rocm-7.2.1"}' <<<"$args")"
    contexts='{"lemonade-rocm-runtime:rocm-7.2.1":"target:base"}'
  fi

  jq -n \
    --arg key "$key" \
    --arg context "$context" \
    --arg dockerfile "$dockerfile_relative" \
    --arg tag "local/${package}:${default_tag}" \
    --arg cache_scope "$cache_scope" \
    --argjson args "$args" \
    --argjson contexts "$contexts" \
    '{
      ($key): (
        {
          context: $context,
          dockerfile: $dockerfile,
          tags: [$tag],
          args: $args,
          "cache-from": ["type=gha,scope=" + $cache_scope],
          "cache-to": ["type=gha,mode=max,scope=" + $cache_scope],
          output: ["type=cacheonly"]
        }
        + (if ($contexts | length) > 0 then {contexts: $contexts} else {} end)
      )
    }' >> "$targets_file"
done < <(.github/scripts/manifest-images-with-paths.sh "$manifest" | jq -c '.[]')

jq -s '
  add as $targets
  | {
      group: {default: {targets: ($targets | keys)}},
      target: $targets
    }
' "$targets_file" > "$bake_file"

cat "$bake_file"

if [[ "${LEMONADE_BAKE_DRY_RUN:-}" == "1" ]]; then
  exit 0
fi

docker buildx bake --file "$bake_file"
