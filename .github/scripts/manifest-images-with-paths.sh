#!/usr/bin/env bash
set -euo pipefail

manifest="${1:-.github/image-matrix.json}"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

while IFS= read -r image; do
  key="$(jq -r '.key' <<<"$image")"
  dockerfile="$(jq -r '.dockerfile' <<<"$image")"
  context="$(jq -r '.context' <<<"$image")"

  if [[ ! -d "$context" ]]; then
    echo "Manifest image '$key' has missing context: $context" >&2
    exit 1
  fi

  if [[ ! -f "$dockerfile" ]]; then
    echo "Manifest image '$key' has missing repository-relative Dockerfile: $dockerfile" >&2
    exit 1
  fi

  context_abs="$(realpath "$context")"
  dockerfile_abs="$(realpath "$dockerfile")"

  case "$dockerfile_abs" in
    "$context_abs"/* | "$context_abs")
      ;;
    *)
      echo "Manifest image '$key' Dockerfile must be inside its build context." >&2
      echo "  context: $context" >&2
      echo "  dockerfile: $dockerfile" >&2
      exit 1
      ;;
  esac

  dockerfile_context_relative="$(realpath --relative-to="$context_abs" "$dockerfile_abs")"

  computed_abs="$(realpath "$context/$dockerfile_context_relative")"
  if [[ ! -f "$context/$dockerfile_context_relative" || "$computed_abs" != "$dockerfile_abs" ]]; then
    echo "Manifest image '$key' computed Dockerfile path does not resolve inside context." >&2
    echo "  context: $context" >&2
    echo "  dockerfile: $dockerfile" >&2
    echo "  computed: $dockerfile_context_relative" >&2
    exit 1
  fi

  jq -c --arg dockerfile_context_relative "$dockerfile_context_relative" \
    '. + {dockerfile_context_relative: $dockerfile_context_relative}' <<<"$image" >> "$tmp"
done < <(jq -c '.images[]' "$manifest")

jq -s . "$tmp"
