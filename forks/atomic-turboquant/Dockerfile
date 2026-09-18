# Lemonade Server image bundling both ROCm and Vulkan builds of AtomicBot-ai's
# atomic-llama-cpp-turboquant fork (https://github.com/AtomicBot-ai/atomic-llama-cpp-turboquant).
#
# Release assets are tar.gz archives (not zip), one per backend, e.g.
# llama-turboquant-linux-x64-rocm.tar.gz / -vulkan.tar.gz / -cuda-12.4.tar.gz /
# -cpu.tar.gz, under a shared release tag like `b10269-1.6.0`.
#
# This Dockerfile builds the combined ROCm+Vulkan image. Atomic's ROCm asset
# does not bundle full ROCm userspace, so this image intentionally layers on
# the lemonade-rocm-runtime base. It downloads the separately published ROCm
# and Vulkan tarballs into distinct directories so users can switch
# `llamacpp.backend` from `rocm` to `vulkan` in the seeded config.json without
# rebuilding the image. See Dockerfile.vulkan for the smaller Vulkan-only image.
#
# No version/asset/checksum defaults are hardcoded on purpose -- pass all
# backend assets and checksums as build args, pinned to a release you have
# verified yourself.
#
# Example build (combined rocm+vulkan assets, release b10269-1.6.0):
#   docker build \
#     --build-arg TURBOQUANT_VERSION=b10269-1.6.0 \
#     --build-arg TURBOQUANT_ROCM_ASSET=llama-turboquant-linux-x64-rocm.tar.gz \
#     --build-arg TURBOQUANT_ROCM_SHA256=e7758e3191827460de13976284160878d02920acb17d54007bd548521def7dc9 \
#     --build-arg TURBOQUANT_VULKAN_ASSET=llama-turboquant-linux-x64-vulkan.tar.gz \
#     --build-arg TURBOQUANT_VULKAN_SHA256=a0a3bc7b067fbac5e402ff3d603c50eaeffe505c5f576e6affb98ecaa9706aa3 \
#     -t lemonade-atomic-turboquant:combined-b10269-1.6.0 \
#     -f forks/atomic-turboquant/Dockerfile forks/atomic-turboquant
#
# For any other release/backend asset, look up the exact filename and compute
# its sha256 yourself -- do not reuse the checksums above for different files.
ARG BASE_IMAGE=lemonade-rocm-runtime:rocm-7.2.1
FROM ${BASE_IMAGE}

USER root

ARG TURBOQUANT_VERSION
ARG TURBOQUANT_ROCM_ASSET
ARG TURBOQUANT_ROCM_SHA256
ARG TURBOQUANT_VULKAN_ASSET
ARG TURBOQUANT_VULKAN_SHA256

RUN test -n "${TURBOQUANT_VERSION}" || (echo "TURBOQUANT_VERSION build-arg is required" >&2 && false) \
    && test -n "${TURBOQUANT_ROCM_ASSET}" || (echo "TURBOQUANT_ROCM_ASSET build-arg is required" >&2 && false) \
    && test -n "${TURBOQUANT_ROCM_SHA256}" || (echo "TURBOQUANT_ROCM_SHA256 build-arg is required" >&2 && false) \
    && test -n "${TURBOQUANT_VULKAN_ASSET}" || (echo "TURBOQUANT_VULKAN_ASSET build-arg is required" >&2 && false) \
    && test -n "${TURBOQUANT_VULKAN_SHA256}" || (echo "TURBOQUANT_VULKAN_SHA256 build-arg is required" >&2 && false)

RUN mkdir -p /opt/lemonade/custom-bin/turboquant/rocm /opt/lemonade/custom-bin/turboquant/vulkan \
    && cd /tmp \
    && curl -fsSL -o turboquant-rocm.tar.gz \
        "https://github.com/AtomicBot-ai/atomic-llama-cpp-turboquant/releases/download/${TURBOQUANT_VERSION}/${TURBOQUANT_ROCM_ASSET}" \
    && echo "${TURBOQUANT_ROCM_SHA256}  turboquant-rocm.tar.gz" | sha256sum --check --strict \
    && tar -xzf turboquant-rocm.tar.gz --strip-components=3 -C /opt/lemonade/custom-bin/turboquant/rocm \
    && curl -fsSL -o turboquant-vulkan.tar.gz \
        "https://github.com/AtomicBot-ai/atomic-llama-cpp-turboquant/releases/download/${TURBOQUANT_VERSION}/${TURBOQUANT_VULKAN_ASSET}" \
    && echo "${TURBOQUANT_VULKAN_SHA256}  turboquant-vulkan.tar.gz" | sha256sum --check --strict \
    && tar -xzf turboquant-vulkan.tar.gz --strip-components=3 -C /opt/lemonade/custom-bin/turboquant/vulkan \
    && rm -f turboquant-rocm.tar.gz turboquant-vulkan.tar.gz \
    && chmod +x /opt/lemonade/custom-bin/turboquant/rocm/llama-server \
    && chmod +x /opt/lemonade/custom-bin/turboquant/vulkan/llama-server \
    && chown -R lemonade:lemonade /opt/lemonade/custom-bin/turboquant

COPY config.default.combined.json /usr/local/share/lemonade/config.default.json
RUN chown lemonade:lemonade /usr/local/share/lemonade/config.default.json

USER lemonade

# ENTRYPOINT/CMD inherited from the base runtime image.
