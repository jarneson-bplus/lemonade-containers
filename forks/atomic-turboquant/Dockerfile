# Lemonade Server image bundling the ROCm build of AtomicBot-ai's
# atomic-llama-cpp-turboquant fork (https://github.com/AtomicBot-ai/atomic-llama-cpp-turboquant).
#
# Release assets are tar.gz archives (not zip), one per backend, e.g.
# llama-turboquant-linux-x64-rocm.tar.gz / -vulkan.tar.gz / -cuda-12.4.tar.gz /
# -cpu.tar.gz, under a shared release tag like `b10269-1.6.0`.
#
# This Dockerfile targets the ROCm asset and layers on top of the shared
# lemonade-rocm-runtime base image. See Dockerfile.vulkan in this same
# directory for the Vulkan variant, which needs no ROCm userspace runtime and
# so builds FROM the plain upstream lemonade-server image instead.
#
# No version/asset/checksum defaults are hardcoded on purpose -- pass all
# three as build args, pinned to a release you have verified yourself.
#
# Example build (rocm asset, release b10269-1.6.0):
#   docker build \
#     --build-arg TURBOQUANT_VERSION=b10269-1.6.0 \
#     --build-arg TURBOQUANT_ASSET=llama-turboquant-linux-x64-rocm.tar.gz \
#     --build-arg TURBOQUANT_SHA256=e7758e3191827460de13976284160878d02920acb17d54007bd548521def7dc9 \
#     -t lemonade-atomic-turboquant:rocm-b10269-1.6.0 \
#     -f forks/atomic-turboquant/Dockerfile forks/atomic-turboquant
#
# For any other release/backend asset, look up the exact filename and compute
# its sha256 yourself -- do not reuse the checksum above for a different file.
ARG BASE_IMAGE=lemonade-rocm-runtime:rocm-7.2.1
FROM ${BASE_IMAGE}

USER root

ARG TURBOQUANT_VERSION
ARG TURBOQUANT_ASSET
ARG TURBOQUANT_SHA256

RUN test -n "${TURBOQUANT_VERSION}" || (echo "TURBOQUANT_VERSION build-arg is required" >&2 && false) \
    && test -n "${TURBOQUANT_ASSET}" || (echo "TURBOQUANT_ASSET build-arg is required" >&2 && false) \
    && test -n "${TURBOQUANT_SHA256}" || (echo "TURBOQUANT_SHA256 build-arg is required" >&2 && false)

RUN mkdir -p /opt/lemonade/custom-bin/turboquant \
    && cd /tmp \
    && curl -fsSL -o turboquant.tar.gz \
        "https://github.com/AtomicBot-ai/atomic-llama-cpp-turboquant/releases/download/${TURBOQUANT_VERSION}/${TURBOQUANT_ASSET}" \
    && echo "${TURBOQUANT_SHA256}  turboquant.tar.gz" | sha256sum --check --strict \
    && tar -xzf turboquant.tar.gz -C /opt/lemonade/custom-bin/turboquant \
    && rm -f turboquant.tar.gz \
    && chmod +x /opt/lemonade/custom-bin/turboquant/llama-server \
    && chown -R lemonade:lemonade /opt/lemonade/custom-bin/turboquant

COPY config.default.rocm.json /usr/local/share/lemonade/config.default.json
RUN chown lemonade:lemonade /usr/local/share/lemonade/config.default.json

USER lemonade

# ENTRYPOINT/CMD inherited from the base runtime image.
