#!/usr/bin/env bash
# Generic entrypoint for lemonade-containers images.
#
# On first start, if the user has bind-mounted an (empty) host directory onto
# ${HOME}/.config/lemonade, there will be no config.json in it yet. In that
# case we seed it from the image's baked-in default config so the container
# is immediately usable, and so the user can then edit config.json directly
# on the host afterward without ever needing to exec into the container.
#
# Subsequent restarts leave an existing config.json untouched.
set -euo pipefail

LEMONADE_CONFIG_DIR="${HOME}/.config/lemonade"
LEMONADE_CONFIG_FILE="${LEMONADE_CONFIG_DIR}/config.json"
LEMONADE_DEFAULT_CONFIG="/usr/local/share/lemonade/config.default.json"

if [ ! -f "${LEMONADE_CONFIG_FILE}" ]; then
    mkdir -p "${LEMONADE_CONFIG_DIR}"
    if [ -f "${LEMONADE_DEFAULT_CONFIG}" ]; then
        echo "[lemonade-entrypoint] No config.json found in ${LEMONADE_CONFIG_DIR}; seeding from ${LEMONADE_DEFAULT_CONFIG}"
        cp "${LEMONADE_DEFAULT_CONFIG}" "${LEMONADE_CONFIG_FILE}"
    else
        echo "[lemonade-entrypoint] WARNING: no default config found at ${LEMONADE_DEFAULT_CONFIG}; starting without config.json"
    fi
fi

exec "$@"
