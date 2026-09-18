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
# This image intentionally uses the lightweight lemon-base base, not
# rocm-lemon: Heretek's ROCm archives bundle their required ROCm
# runtime libraries next to `llama-server` with $ORIGIN RPATH, and /opt/rocm
# LD_LIBRARY_PATH could shadow those moving TheRock nightly libraries.
#
# This Dockerfile does not hardcode a version/asset/checksum: you must pass
# all three as build args, pinned to a specific release you have verified.
#
# Example build (kingjones30 fork, gfx1151 target, release b1050):
#   docker build \
#     --build-arg ROCMFPX_VERSION=b1050 \
#     --build-arg ROCMFPX_ASSET=kingjones-rocmfpx-b1050-ubuntu-rocm-gfx1151-x64.zip \
#     --build-arg ROCMFPX_SHA256=2d39092220dadbf3cbc093274146b115af448f514a102a2347bd0a06e6470f9f \
#     -t fpx-lemon:combined-b1050-gfx1151 \
#     -f forks/rocmfpx-heretek/Dockerfile forks/rocmfpx-heretek
#
# For any other variant/GPU target, look up the exact asset filename and
# compute its sha256 yourself from the actual release download -- do not
# reuse the checksum above for a different asset.
ARG BASE_IMAGE=lemon-base:lemonade-v11.9.0
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
