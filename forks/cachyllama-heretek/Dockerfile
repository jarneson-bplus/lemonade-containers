# Lemonade Server image bundling both ROCm and Vulkan CachyLLama-BUILDER
# llama-server releases.
#
# CachyLLama-BUILDER (https://github.com/Heretek-AI/CachyLLama-BUILDER)
# publishes prebuilt, per-GPU-target ROCm zip archives plus a generic Linux
# Vulkan tarball for fewtarius/CachyLLama + fewtarius/llama-ai. Each upstream
# distribution contains `llama-server` plus sibling shared libraries with an
# $ORIGIN RPATH, so each archive must be extracted whole into its own
# directory -- copying just the binary will fail to find its libs at runtime.
#
# This Dockerfile builds the combined ROCm+Vulkan image. It intentionally uses
# the lightweight lemonade-runtime base, not lemonade-rocm-runtime: Heretek's
# ROCm archives bundle their required ROCm runtime libraries next to
# `llama-server` with $ORIGIN RPATH, and /opt/rocm LD_LIBRARY_PATH could shadow
# those moving TheRock nightly libraries. The ROCm and Vulkan archives are
# extracted whole into distinct directories so users can switch
# `llamacpp.backend` from `rocm` to `vulkan` in the seeded config.json without
# rebuilding. See Dockerfile.vulkan for the smaller Vulkan-only image.
#
# This Dockerfile does not hardcode versions/assets/checksums: you must pass
# all backend build args, pinned to a specific release you have verified.
#
# Example build (gfx1151 ROCm + generic Vulkan, release b1036):
#   docker build \
#     --build-arg CACHYLLAMA_VERSION=b1036 \
#     --build-arg CACHYLLAMA_ROCM_ASSET=cachy-llama-b1036-ubuntu-rocm-gfx1151-x64.zip \
#     --build-arg CACHYLLAMA_ROCM_SHA256=b56cf63a6895f03173b7a2e4389ea2266241ade3c87ab6557cb14909f02c75b4 \
#     --build-arg CACHYLLAMA_VULKAN_ASSET=cachy-llama-bin-ubuntu-vulkan-x64.tar.gz \
#     --build-arg CACHYLLAMA_VULKAN_SHA256=7241a3611f3bbea1e3a852178f73ed8376017c21fce5c116094cc8380e476604 \
#     -t lemonade-cachyllama:combined-b1036-gfx1151 \
#     -f forks/cachyllama-heretek/Dockerfile forks/cachyllama-heretek
#
# For any other GPU target or release, look up the exact asset filename and
# compute its sha256 yourself from the actual release download -- do not
# reuse the checksums above for different assets.
ARG BASE_IMAGE=lemonade-runtime:lemonade-v11.9.0
FROM ${BASE_IMAGE}

USER root

# Release tag, exact asset filenames, and pinned sha256s -- must be supplied
# at build time, no defaults on purpose (see header comment).
ARG CACHYLLAMA_VERSION
ARG CACHYLLAMA_ROCM_ASSET
ARG CACHYLLAMA_ROCM_SHA256
ARG CACHYLLAMA_VULKAN_ASSET
ARG CACHYLLAMA_VULKAN_SHA256

RUN test -n "${CACHYLLAMA_VERSION}" || (echo "CACHYLLAMA_VERSION build-arg is required" >&2 && false) \
    && test -n "${CACHYLLAMA_ROCM_ASSET}" || (echo "CACHYLLAMA_ROCM_ASSET build-arg is required" >&2 && false) \
    && test -n "${CACHYLLAMA_ROCM_SHA256}" || (echo "CACHYLLAMA_ROCM_SHA256 build-arg is required" >&2 && false) \
    && test -n "${CACHYLLAMA_VULKAN_ASSET}" || (echo "CACHYLLAMA_VULKAN_ASSET build-arg is required" >&2 && false) \
    && test -n "${CACHYLLAMA_VULKAN_SHA256}" || (echo "CACHYLLAMA_VULKAN_SHA256 build-arg is required" >&2 && false)

RUN mkdir -p /opt/lemonade/custom-bin/cachyllama/rocm /opt/lemonade/custom-bin/cachyllama/vulkan \
    && cd /tmp \
    && curl -fsSL -o cachyllama-rocm.zip \
        "https://github.com/Heretek-AI/CachyLLama-BUILDER/releases/download/${CACHYLLAMA_VERSION}/${CACHYLLAMA_ROCM_ASSET}" \
    && echo "${CACHYLLAMA_ROCM_SHA256}  cachyllama-rocm.zip" | sha256sum --check --strict \
    && unzip -o cachyllama-rocm.zip -d /opt/lemonade/custom-bin/cachyllama/rocm \
    && curl -fsSL -o cachyllama-vulkan.tar.gz \
        "https://github.com/Heretek-AI/CachyLLama-BUILDER/releases/download/${CACHYLLAMA_VERSION}/${CACHYLLAMA_VULKAN_ASSET}" \
    && echo "${CACHYLLAMA_VULKAN_SHA256}  cachyllama-vulkan.tar.gz" | sha256sum --check --strict \
    && tar -xzf cachyllama-vulkan.tar.gz -C /opt/lemonade/custom-bin/cachyllama/vulkan \
    && rm -f cachyllama-rocm.zip cachyllama-vulkan.tar.gz \
    && chmod +x /opt/lemonade/custom-bin/cachyllama/rocm/llama-server \
    && chmod +x /opt/lemonade/custom-bin/cachyllama/vulkan/llama-server \
    && chown -R lemonade:lemonade /opt/lemonade/custom-bin/cachyllama

COPY config.default.json /usr/local/share/lemonade/config.default.json
RUN chown lemonade:lemonade /usr/local/share/lemonade/config.default.json

USER lemonade

# ENTRYPOINT/CMD inherited from the base runtime image.
