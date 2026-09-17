# Shared runtime base for lemonade-containers fork images.
#
# Adds a ROCm userspace runtime on top of the upstream Lemonade Server image
# so downstream fork Dockerfiles (see ../forks/*) only need to add their own
# llama.cpp binary + config.default.json. Also installs a generic entrypoint
# that seeds ${HOME}/.config/lemonade/config.json from a baked-in default the
# first time the container runs, so users can bind-mount a whole config
# directory (not a single file) and edit config.json on the host afterward.
#
# Build:
#   docker build -t lemonade-rocm-runtime:rocm-7.2.1 -f base/Dockerfile base
#
# Optionally override the ROCm version / Ubuntu codename used for the
# repo.radeon.com apt repo:
#   docker build \
#     --build-arg ROCM_VERSION=7.2.1 \
#     --build-arg UBUNTU_CODENAME=noble \
#     -t lemonade-rocm-runtime:rocm-7.2.1 -f base/Dockerfile base
ARG BASE_IMAGE=ghcr.io/lemonade-sdk/lemonade-server:latest
FROM ${BASE_IMAGE}

ARG ROCM_VERSION=7.2.1
ARG UBUNTU_CODENAME=noble

USER root

# --- ROCm userspace runtime -------------------------------------------------
# Adds the AMD ROCm apt repository and installs just the userspace runtime
# libraries needed to run prebuilt ROCm llama.cpp binaries (no kernel driver,
# no dev headers) -- the host's amdgpu kernel driver + /dev/kfd + /dev/dri
# are passed through at `docker run` time instead.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        unzip \
    && mkdir -p --mode=0755 /etc/apt/keyrings \
    && curl -fsSL https://repo.radeon.com/rocm/rocm.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/rocm.gpg \
    && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/rocm.gpg] https://repo.radeon.com/rocm/apt/${ROCM_VERSION} ${UBUNTU_CODENAME} main" \
        > /etc/apt/sources.list.d/rocm.list \
    && echo "Package: *" > /etc/apt/preferences.d/rocm-pin-600 \
    && echo "Pin: release o=repo.radeon.com" >> /etc/apt/preferences.d/rocm-pin-600 \
    && echo "Pin-Priority: 600" >> /etc/apt/preferences.d/rocm-pin-600 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        rocm-libs \
        hip-runtime-amd \
        rocblas \
        hipblas \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV LD_LIBRARY_PATH="/opt/rocm/lib" \
    PATH="/opt/rocm/bin:${PATH}"

# --- device group access ----------------------------------------------------
# The lemonade user (UID 10001, created by the upstream image) needs to be a
# member of `render`/`video` so it can access /dev/kfd and /dev/dri when the
# host passes those devices through with `docker run --device=...`.
RUN usermod -aG render,video lemonade

# --- generic config-seeding entrypoint --------------------------------------
COPY docker-entrypoint.sh /usr/local/bin/lemonade-entrypoint
RUN chmod +x /usr/local/bin/lemonade-entrypoint

USER lemonade

ENTRYPOINT ["/usr/local/bin/lemonade-entrypoint"]
CMD ["./lemond", "--host", "0.0.0.0"]
