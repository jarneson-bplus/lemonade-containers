#!/usr/bin/env bash
set -euo pipefail

manifest="${1:-.github/image-matrix.json}"
bake_file="${RUNNER_TEMP:-/tmp}/lemonade-images.bake.json"

jq '
  def args_object:
    (.build_args
      | map(split("=") | {(.[0]): (.[1:] | join("="))})
      | add // {});

  {
    group: {
      default: {
        targets: [.images[].key]
      }
    },
    target: (
      reduce .images[] as $image ({};
        .[$image.key] = (
          {
            context: $image.context,
            dockerfile: $image.dockerfile,
            tags: ["local/" + $image.package + ":" + $image.default_tag],
            args: (
              ($image | args_object)
              + (if $image.depends_on == "base" then
                  {"BASE_IMAGE": "lemonade-rocm-runtime:rocm-7.2.1"}
                else
                  {}
                end)
            ),
            "cache-from": ["type=gha,scope=" + $image.cache_scope],
            "cache-to": ["type=gha,mode=max,scope=" + $image.cache_scope],
            output: ["type=cacheonly"]
          }
          + (if $image.depends_on == "base" then
              {
                contexts: {
                  "lemonade-rocm-runtime:rocm-7.2.1": "target:base"
                }
              }
            else
              {}
            end)
        )
      )
    )
  }
' "$manifest" > "$bake_file"

cat "$bake_file"
docker buildx bake --file "$bake_file"
