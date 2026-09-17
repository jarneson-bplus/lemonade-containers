# Lemonade Server image bundling a ROCmFPX-BUILDER llama-server release.
#
# ROCmFPX-BUILDER (https://github.com/Heretek-AI/ROCmFPX-BUILDER) publishes
# prebuilt, per-GPU-target release archives for four llama.cpp forks
# (upstream charlie12345/ROCmFPX, ciru-ai/ROCmFPX, julianmb/q38rocm,
# kingjones30/ROCmFPX). Each release asset is a zip containing `llama-server`
# plus its shared libraries with an $ORIGIN RPATH, so the *entire* zip must be
# extracted into one directory -- copying just the binary will fail to find
# its libs at runtime.
#
# The Heretek-AI/ROCmFPX-BUILDER Linux workflow builds this binary with both
# GGML_HIP and GGML_VULKAN enabled, and the release does not currently publish
# a standalone Linux Vulkan-only artifact. The paired config.default.json
# therefore exposes the same llama-server path as both rocm_bin and vulkan_bin.
#
# This Dockerfile does not hardcode a version/asset/checksum: you must pass
# all three as build args, pinned to a specific release you have verified.
#
# Example build (kingjones30 fork, gfx1151 target, release b1045):
#   docker build \
#     --build-arg ROCMFPX_VERSION=b1045 \
#     --build-arg ROCMFPX_ASSET=kingjones-rocmfpx-b1045-ubuntu-rocm-gfx1151-x64.zip \
#     --build-arg ROCMFPX_SHA256=75ecc080e75e59f55c047eff9023d41ff0c085fc2d8ac83cb953ebd810e51b28 \
#     -t lemonade-rocmfpx-kingjones30:combined-b1045-gfx1151 \
#     -f forks/rocmfpx-heretek/Dockerfile forks/rocmfpx-heretek
#
# For any other variant/GPU target, look up the exact asset filename and
# compute its sha256 yourself from the actual release download -- do not
# reuse the checksum above for a different asset.
ARG BASE_IMAGE=lemonade-rocm-runtime:rocm-7.2.1
FROM ${BASE_IMAGE}

USER root

# Release tag, exact asset filename, and pinned sha256 -- must be supplied at
# build time, no defaults on purpose (see header comment).
ARG ROCMFPX_VERSION
ARG ROCMFPX_ASSET
ARG ROCMFPX_SHA256

RUN test -n "${ROCMFPX_VERSION}" || (echo "ROCMFPX_VERSION build-arg is required" >&2 && false) \
    && test -n "${ROCMFPX_ASSET}" || (echo "ROCMFPX_ASSET build-arg is required" >&2 && false) \
    && test -n "${ROCMFPX_SHA256}" || (echo "ROCMFPX_SHA256 build-arg is required" >&2 && false)

RUN mkdir -p /opt/lemonade/custom-bin/rocmfpx \
    && cd /tmp \
    && curl -fsSL -o rocmfpx.zip \
        "https://github.com/Heretek-AI/ROCmFPX-BUILDER/releases/download/${ROCMFPX_VERSION}/${ROCMFPX_ASSET}" \
    && echo "${ROCMFPX_SHA256}  rocmfpx.zip" | sha256sum --check --strict \
    && unzip -o rocmfpx.zip -d /opt/lemonade/custom-bin/rocmfpx \
    && rm -f rocmfpx.zip \
    && chmod +x /opt/lemonade/custom-bin/rocmfpx/llama-server \
    && chown -R lemonade:lemonade /opt/lemonade/custom-bin/rocmfpx

COPY config.default.json /usr/local/share/lemonade/config.default.json
RUN chown lemonade:lemonade /usr/local/share/lemonade/config.default.json

USER lemonade

# ENTRYPOINT/CMD inherited from the base runtime image.
