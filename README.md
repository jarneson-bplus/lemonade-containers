# lemonade-containers

Build custom Docker images that run [Lemonade Server](https://github.com/lemonade-sdk/lemonade)
with swappable, custom llama.cpp forks/binaries baked in -- so you can build
and test many fork/backend/GPU-target variants side by side without execing
into containers, editing `PATH`, or juggling bind mounts for the binary
itself.

Instead of one container that you keep reconfiguring, this repo builds one
small, immutable image per fork + version + GPU target. Swapping variants is
`docker run <different image tag>`, not surgery inside a running container.

## How it's laid out

```
base/
  Dockerfile            # shared runtime: lemonade-server + ROCm userspace + entrypoint
  docker-entrypoint.sh  # seeds config.json into the mounted config dir on first run
forks/
  rocmfpx-heretek/
    Dockerfile           # Heretek-AI/ROCmFPX-BUILDER release (ROCm)
    config.default.json
  atomic-turboquant/
    Dockerfile              # AtomicBot-ai/atomic-llama-cpp-turboquant, ROCm asset
    Dockerfile.vulkan       # same fork, Vulkan asset, no ROCm layer needed
    config.default.rocm.json
    config.default.vulkan.json
docker-compose.yml
config/                 # example bind-mount targets for docker-compose.yml (gitignored contents)
```

### Layer 1: shared base runtime (`base/Dockerfile`)

Builds `FROM ghcr.io/lemonade-sdk/lemonade-server` and adds:

- A ROCm 7.2.1 userspace runtime (adds the `repo.radeon.com` apt repo, then
  installs `rocm-libs hip-runtime-amd rocblas hipblas`; sets
  `LD_LIBRARY_PATH=/opt/rocm/lib` and appends `/opt/rocm/bin` to `PATH`). The
  ROCm version and Ubuntu codename used for the apt repo are build args
  (`ROCM_VERSION`, `UBUNTU_CODENAME`) so you can bump them without editing the
  Dockerfile. This layer only adds userspace libraries -- the host's amdgpu
  kernel driver and `/dev/kfd`/`/dev/dri` are passed through at `docker run`
  time, they are not part of the image.
- `usermod -aG render,video lemonade`, so the unprivileged `lemonade` user
  (UID 10001, created by the upstream image) can actually use the ROCm/DRI
  devices once they're passed through.
- A generic entrypoint, `/usr/local/bin/lemonade-entrypoint`
  (from `docker-entrypoint.sh`): on container start, if
  `${HOME}/.config/lemonade/config.json` doesn't exist yet, it's copied from
  a baked-in `/usr/local/share/lemonade/config.default.json`, then the
  container's real command runs. This means you bind-mount a *directory* (not
  a single file) onto `/opt/lemonade/.config/lemonade`; the first run
  auto-creates `config.json` in it from the image's default, and after that
  you can edit `config.json` directly on the host and restart the container
  to pick up changes -- no execing into the container required.
- `ENTRYPOINT ["/usr/local/bin/lemonade-entrypoint"]`,
  `CMD ["./lemond", "--host", "0.0.0.0"]` (same default command as the
  upstream image).

Build it once and reuse it as the base for every fork image:

```sh
docker build \
  -t lemonade-rocm-runtime:rocm-7.2.1 \
  -f base/Dockerfile base
```

### Layer 2: one Dockerfile per fork (`forks/<fork>/`)

Each fork directory has its own Dockerfile that layers `FROM` the shared
runtime image above, downloads one pinned release asset over HTTPS,
`sha256sum --check --strict`s it, extracts it into
`/opt/lemonade/custom-bin/<fork>/`, and copies in a small
`config.default.json` that points Lemonade's `llamacpp` config at that
binary. None of the fork Dockerfiles hardcode a version, asset filename, or
"latest" -- you always pass the release version, exact asset filename, and
its sha256 as build args, pinned to a release you've verified yourself.

#### `forks/rocmfpx-heretek/` -- Heretek-AI/ROCmFPX-BUILDER

[Heretek-AI/ROCmFPX-BUILDER](https://github.com/Heretek-AI/ROCmFPX-BUILDER)
builds and publishes prebuilt, per-GPU-target release archives for four
llama.cpp forks (upstream `charlie12345/ROCmFPX`, `ciru-ai/ROCmFPX`,
`julianmb/q38rocm`, `kingjones30/ROCmFPX`). Release assets look like
`kingjones-rocmfpx-<tag>-ubuntu-rocm-<gfxtarget>-x64.zip` and contain
`llama-server` plus shared libraries with an `$ORIGIN` RPATH, so the whole
zip must be extracted (not just the binary).

Example build, for the `kingjones30` fork targeting `gfx1151`, release
`b1045`:

```sh
docker build \
  --build-arg ROCMFPX_VERSION=b1045 \
  --build-arg ROCMFPX_ASSET=kingjones-rocmfpx-b1045-ubuntu-rocm-gfx1151-x64.zip \
  --build-arg ROCMFPX_SHA256=75ecc080e75e59f55c047eff9023d41ff0c085fc2d8ac83cb953ebd810e51b28 \
  -t lemonade-rocmfpx-kingjones30:b1045-gfx1151 \
  -f forks/rocmfpx-heretek/Dockerfile forks/rocmfpx-heretek
```

For any other fork variant or GPU target from that same builder repo, look
up the exact release tag and asset filename on its Releases page, download
it, and compute the sha256 yourself (`sha256sum <file>`) -- don't reuse the
checksum above for a different asset.

#### `forks/atomic-turboquant/` -- AtomicBot-ai/atomic-llama-cpp-turboquant

[AtomicBot-ai/atomic-llama-cpp-turboquant](https://github.com/AtomicBot-ai/atomic-llama-cpp-turboquant)
publishes one `tar.gz` per backend per release tag (e.g. tag
`b10269-1.6.0`, assets `llama-turboquant-linux-x64-rocm.tar.gz`,
`-vulkan.tar.gz`, `-cuda-12.4.tar.gz`, `-cpu.tar.gz`).

**ROCm build** (`forks/atomic-turboquant/Dockerfile`, layers on the shared
`lemonade-rocm-runtime` base):

```sh
docker build \
  --build-arg TURBOQUANT_VERSION=b10269-1.6.0 \
  --build-arg TURBOQUANT_ASSET=llama-turboquant-linux-x64-rocm.tar.gz \
  --build-arg TURBOQUANT_SHA256=e7758e3191827460de13976284160878d02920acb17d54007bd548521def7dc9 \
  -t lemonade-atomic-turboquant:rocm-b10269-1.6.0 \
  -f forks/atomic-turboquant/Dockerfile forks/atomic-turboquant
```

**Vulkan build** (`forks/atomic-turboquant/Dockerfile.vulkan`): Vulkan needs
no ROCm userspace runtime, so this variant builds `FROM` the plain upstream
`lemonade-server` image instead (Vulkan libraries are already part of that
image), and re-applies the small bits the shared base normally provides
(device group membership + the config-seeding entrypoint) directly. Build it
with the *repo root* as context so it can reach `base/docker-entrypoint.sh`:

```sh
docker build \
  --build-arg TURBOQUANT_VERSION=<release-tag> \
  --build-arg TURBOQUANT_ASSET=llama-turboquant-linux-x64-vulkan.tar.gz \
  --build-arg TURBOQUANT_SHA256=<sha256-you-computed> \
  -t lemonade-atomic-turboquant:vulkan-<release-tag> \
  -f forks/atomic-turboquant/Dockerfile.vulkan .
```

Only the two checksums documented above (kingjones30 gfx1151 `b1045`, and
atomic-turboquant ROCm `b10269-1.6.0`) are pinned/verified in this repo. For
the Vulkan example (or any other release/asset), download the asset
yourself and run `sha256sum` on it -- do not reuse or guess a checksum for a
file you haven't downloaded.

## Config: auto-created on first run, then yours to edit

Every image's entrypoint checks `${HOME}/.config/lemonade/config.json`
(`HOME` is `/opt/lemonade` in the upstream image) on startup. If it's
missing, it's copied there from the image's baked-in
`/usr/local/share/lemonade/config.default.json`. So:

1. Bind-mount an empty (or existing) host directory onto
   `/opt/lemonade/.config/lemonade`, e.g. `./config/<image-name>`.
2. Start the container. On first boot, `config.json` appears in that host
   directory, already pointed at the right `llama-server` binary and backend
   for that image.
3. Edit `./config/<image-name>/config.json` directly on the host at any
   time and restart the container -- your edits are preserved, since the
   entrypoint only seeds the file when it doesn't exist yet.

See `docker-compose.yml` for worked examples (ROCm + Vulkan), including the
`--device=/dev/kfd --device=/dev/dri --group-add video --group-add render`
flags ROCm containers need, and a note about preferring
`127.0.0.1:13305:13305` over `0.0.0.0:13305:13305` when publishing the port.

## Publishing to GHCR

Public container image storage and bandwidth are currently free on GHCR.
Keep individual layers under roughly 10 GB, and prefer the shared-base +
small-derived-image structure this repo already uses -- one
`lemonade-rocm-runtime` base layer shared by every ROCm fork image avoids
duplicating the ROCm install across every tag. A reasonable tag scheme:

```
ghcr.io/<you>/lemonade-rocm-runtime:rocm-7.2.1
ghcr.io/<you>/lemonade-rocmfpx-kingjones30:b1045-gfx1151
ghcr.io/<you>/lemonade-atomic-turboquant:rocm-b10269-1.6.0
ghcr.io/<you>/lemonade-atomic-turboquant:vulkan-b10269-1.6.0
```

```sh
docker tag lemonade-atomic-turboquant:rocm-b10269-1.6.0 \
  ghcr.io/<you>/lemonade-atomic-turboquant:rocm-b10269-1.6.0
docker push ghcr.io/<you>/lemonade-atomic-turboquant:rocm-b10269-1.6.0
```
