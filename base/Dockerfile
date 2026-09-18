# Lightweight shared runtime base for lemonade-containers fork images.
#
# This image intentionally does not install ROCm. It provides only the pinned
# Lemonade Server base, common archive/download utilities, device group setup,
# and the config-seeding entrypoint inherited by all fork images.
#
# Build:
#   docker build -t lemonade-runtime:lemonade-v11.9.0 -f base/Dockerfile base
ARG BASE_IMAGE=ghcr.io/lemonade-sdk/lemonade-server:v11.9.0
FROM ${BASE_IMAGE}

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        unzip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# The lemonade user (UID 10001, created by the upstream image) needs to be a
# member of `render`/`video` so it can access /dev/kfd and /dev/dri when the
# host passes those devices through with `docker run --device=...`.
RUN groupadd -f render \
    && groupadd -f video \
    && usermod -aG render,video lemonade

COPY docker-entrypoint.sh /usr/local/bin/lemonade-entrypoint
RUN chmod +x /usr/local/bin/lemonade-entrypoint

USER lemonade

ENTRYPOINT ["/usr/local/bin/lemonade-entrypoint"]
CMD ["./lemond", "--host", "0.0.0.0"]
