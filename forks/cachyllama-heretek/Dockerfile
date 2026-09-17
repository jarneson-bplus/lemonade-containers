# Lemonade Server image bundling a CachyLLama-BUILDER llama-server release.
#
# CachyLLama-BUILDER (https://github.com/Heretek-AI/CachyLLama-BUILDER)
# publishes prebuilt, per-GPU-target release archives building
# fewtarius/CachyLLama + fewtarius/llama-ai. Each release asset is a zip
# containing `llama-server` plus its shared libraries with an $ORIGIN RPATH,
# so the *entire* zip must be extracted into one directory -- copying just
# the binary will fail to find its libs at runtime.
#
# This Dockerfile does not hardcode a version/asset/checksum: you must pass
# all three as build args, pinned to a specific release you have verified.
#
# Example build (gfx1151 target, release b1036):
#   docker build \
#     --build-arg CACHYLLAMA_VERSION=b1036 \
#     --build-arg CACHYLLAMA_ASSET=cachy-llama-b1036-ubuntu-rocm-gfx1151-x64.zip \
#     --build-arg CACHYLLAMA_SHA256=b56cf63a6895f03173b7a2e4389ea2266241ade3c87ab6557cb14909f02c75b4 \
#     -t lemonade-cachyllama:b1036-gfx1151 \
#     -f forks/cachyllama-heretek/Dockerfile forks/cachyllama-heretek
#
# For any other GPU target, look up the exact asset filename and compute its
# sha256 yourself from the actual release download -- do not reuse the
# checksum above for a different asset.
ARG BASE_IMAGE=lemonade-rocm-runtime:rocm-7.2.1
FROM ${BASE_IMAGE}

USER root

# Release tag, exact asset filename, and pinned sha256 -- must be supplied at
# build time, no defaults on purpose (see header comment).
ARG CACHYLLAMA_VERSION
ARG CACHYLLAMA_ASSET
ARG CACHYLLAMA_SHA256

RUN test -n "${CACHYLLAMA_VERSION}" || (echo "CACHYLLAMA_VERSION build-arg is required" >&2 && false) \
    && test -n "${CACHYLLAMA_ASSET}" || (echo "CACHYLLAMA_ASSET build-arg is required" >&2 && false) \
    && test -n "${CACHYLLAMA_SHA256}" || (echo "CACHYLLAMA_SHA256 build-arg is required" >&2 && false)

RUN mkdir -p /opt/lemonade/custom-bin/cachyllama \
    && cd /tmp \
    && curl -fsSL -o cachyllama.zip \
        "https://github.com/Heretek-AI/CachyLLama-BUILDER/releases/download/${CACHYLLAMA_VERSION}/${CACHYLLAMA_ASSET}" \
    && echo "${CACHYLLAMA_SHA256}  cachyllama.zip" | sha256sum --check --strict \
    && unzip -o cachyllama.zip -d /opt/lemonade/custom-bin/cachyllama \
    && rm -f cachyllama.zip \
    && chmod +x /opt/lemonade/custom-bin/cachyllama/llama-server \
    && chown -R lemonade:lemonade /opt/lemonade/custom-bin/cachyllama

COPY config.default.json /usr/local/share/lemonade/config.default.json
RUN chown lemonade:lemonade /usr/local/share/lemonade/config.default.json

USER lemonade

# ENTRYPOINT/CMD inherited from the base runtime image.
