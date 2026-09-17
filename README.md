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
    Dockerfile           # Heretek-AI/ROCmFPX-BUILDER release (combined ROCm+Vulkan)
    config.default.json
  cachyllama-heretek/
    Dockerfile           # Heretek-AI/CachyLLama-BUILDER release (combined ROCm+Vulkan)
    Dockerfile.vulkan    # same fork, Vulkan-only asset, no ROCm layer needed
    config.default.json
    config.default.vulkan.json
  atomic-turboquant/
    Dockerfile              # AtomicBot-ai/atomic-llama-cpp-turboquant, combined ROCm+Vulkan
    Dockerfile.vulkan       # same fork, Vulkan asset, no ROCm layer needed
    config.default.combined.json
    config.default.vulkan.json
docker-compose.yml
config/                 # example bind-mount targets for docker-compose.yml (gitignored contents)
```

### Layer 1: shared base runtime (`base/Dockerfile`)

Builds `FROM ghcr.io/lemonade-sdk/lemonade-server:v11.9.0` by default and adds:

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

### Layer 2: one Dockerfile per fork/backend matrix (`forks/<fork>/`)

Each fork directory has one or more Dockerfiles that download pinned upstream
release assets over HTTPS, `sha256sum --check --strict` each archive, extract
each upstream distribution whole into its own `/opt/lemonade/custom-bin/<fork>/<backend>/`
directory when needed, and copy in a small default config for Lemonade.

For forks with both ROCm and Vulkan upstream builds, this repo provides:

- a **combined ROCm+Vulkan image** (`Dockerfile`) that layers `FROM` the
  shared `lemonade-rocm-runtime` base and bundles both backend distributions;
  `llamacpp.backend` defaults to `rocm`, but the seeded config also includes
  `vulkan_bin`, so users can edit `config.json` and switch to `vulkan`
  without rebuilding.
- a **Vulkan-only image** (`Dockerfile.vulkan`) that builds directly from the
  pinned `ghcr.io/lemonade-sdk/lemonade-server:v11.9.0` base and does not add
  ROCm userspace.

Combined ROCm+Vulkan images are intentionally larger because they bundle two
upstream distributions and preserve each archive's sibling shared libraries /
`$ORIGIN` RPATH layout. None of the fork Dockerfiles hardcode a fork version,
asset filename, checksum, or floating "latest" asset -- you always pass the
release version, exact asset filename(s), and sha256(s) as build args, pinned
to releases you've verified yourself.

#### `forks/rocmfpx-heretek/` -- Heretek-AI/ROCmFPX-BUILDER

[Heretek-AI/ROCmFPX-BUILDER](https://github.com/Heretek-AI/ROCmFPX-BUILDER)
builds and publishes prebuilt, per-GPU-target release archives for four
llama.cpp forks (upstream `charlie12345/ROCmFPX`, `ciru-ai/ROCmFPX`,
`julianmb/q38rocm`, `kingjones30/ROCmFPX`). Release assets look like
`kingjones-rocmfpx-<tag>-ubuntu-rocm-<gfxtarget>-x64.zip` and contain
`llama-server` plus shared libraries with an `$ORIGIN` RPATH, so the whole
zip must be extracted (not just the binary).

ROCmFPX-BUILDER's latest release publishes ROCm zip assets only (no standalone
Linux Vulkan-only tarball). The `build-kingjones-rocmfpx.yml` workflow builds
the Linux binaries with both `-DGGML_HIP=ON` and `-DGGML_VULKAN=ON`, so this
repo exposes the same bundled `llama-server` as both `rocm_bin` and
`vulkan_bin` in the combined config. There is no ROCmFPX `Dockerfile.vulkan`
until upstream publishes a suitable standalone Vulkan artifact.

Example build, for the `kingjones30` fork targeting `gfx1151`, release
`b1045`:

```sh
docker build \
  --build-arg ROCMFPX_VERSION=b1045 \
  --build-arg ROCMFPX_ASSET=kingjones-rocmfpx-b1045-ubuntu-rocm-gfx1151-x64.zip \
  --build-arg ROCMFPX_SHA256=75ecc080e75e59f55c047eff9023d41ff0c085fc2d8ac83cb953ebd810e51b28 \
  -t lemonade-rocmfpx-kingjones30:combined-b1045-gfx1151 \
  -f forks/rocmfpx-heretek/Dockerfile forks/rocmfpx-heretek
```

For any other fork variant or GPU target from that same builder repo, look
up the exact release tag and asset filename on its Releases page, download
it, and compute the sha256 yourself (`sha256sum <file>`) -- don't reuse the
checksum above for a different asset.

#### `forks/cachyllama-heretek/` -- Heretek-AI/CachyLLama-BUILDER

[Heretek-AI/CachyLLama-BUILDER](https://github.com/Heretek-AI/CachyLLama-BUILDER)
builds and publishes prebuilt, per-GPU-target release archives for
`fewtarius/CachyLLama` + `fewtarius/llama-ai`. Release assets look like
`cachy-llama-<tag>-ubuntu-rocm-<gfxtarget>-x64.zip` and, like ROCmFPX-BUILDER
above, contain `llama-server` plus shared libraries with an `$ORIGIN` RPATH,
so the whole zip must be extracted (not just the binary).

**Combined ROCm+Vulkan build** (`forks/cachyllama-heretek/Dockerfile`),
targeting `gfx1151` (Strix Halo) for the ROCm half and the generic Linux
Vulkan tarball for the Vulkan half, release `b1036`:

```sh
docker build \
  --build-arg CACHYLLAMA_VERSION=b1036 \
  --build-arg CACHYLLAMA_ROCM_ASSET=cachy-llama-b1036-ubuntu-rocm-gfx1151-x64.zip \
  --build-arg CACHYLLAMA_ROCM_SHA256=b56cf63a6895f03173b7a2e4389ea2266241ade3c87ab6557cb14909f02c75b4 \
  --build-arg CACHYLLAMA_VULKAN_ASSET=cachy-llama-bin-ubuntu-vulkan-x64.tar.gz \
  --build-arg CACHYLLAMA_VULKAN_SHA256=7241a3611f3bbea1e3a852178f73ed8376017c21fce5c116094cc8380e476604 \
  -t lemonade-cachyllama:combined-b1036-gfx1151 \
  -f forks/cachyllama-heretek/Dockerfile forks/cachyllama-heretek
```

**Vulkan-only build** (`forks/cachyllama-heretek/Dockerfile.vulkan`):

```sh
docker build \
  --build-arg CACHYLLAMA_VERSION=b1036 \
  --build-arg CACHYLLAMA_ASSET=cachy-llama-bin-ubuntu-vulkan-x64.tar.gz \
  --build-arg CACHYLLAMA_SHA256=7241a3611f3bbea1e3a852178f73ed8376017c21fce5c116094cc8380e476604 \
  -t lemonade-cachyllama:vulkan-b1036 \
  -f forks/cachyllama-heretek/Dockerfile.vulkan .
```

The exact latest `b1036` Vulkan asset name and sha256 above were verified from
the GitHub Releases API for
[CachyLLama-BUILDER's latest release](https://github.com/Heretek-AI/CachyLLama-BUILDER/releases/latest).
Other ROCm GPU targets (`gfx1150`, `gfx110X`, `gfx103X`, `gfx90a`, `gfx908`,
`gfx120X`) are published from the same release -- grab the matching asset name
and compute its own sha256 yourself from the release asset you download.

#### `forks/atomic-turboquant/` -- AtomicBot-ai/atomic-llama-cpp-turboquant

[AtomicBot-ai/atomic-llama-cpp-turboquant](https://github.com/AtomicBot-ai/atomic-llama-cpp-turboquant)
publishes one `tar.gz` per backend per release tag (e.g. tag
`b10269-1.6.0`, assets `llama-turboquant-linux-x64-rocm.tar.gz`,
`-vulkan.tar.gz`, `-cuda-12.4.tar.gz`, `-cpu.tar.gz`).

**Combined ROCm+Vulkan build** (`forks/atomic-turboquant/Dockerfile`, layers
on the shared `lemonade-rocm-runtime` base):

```sh
docker build \
  --build-arg TURBOQUANT_VERSION=b10269-1.6.0 \
  --build-arg TURBOQUANT_ROCM_ASSET=llama-turboquant-linux-x64-rocm.tar.gz \
  --build-arg TURBOQUANT_ROCM_SHA256=e7758e3191827460de13976284160878d02920acb17d54007bd548521def7dc9 \
  --build-arg TURBOQUANT_VULKAN_ASSET=llama-turboquant-linux-x64-vulkan.tar.gz \
  --build-arg TURBOQUANT_VULKAN_SHA256=a0a3bc7b067fbac5e402ff3d603c50eaeffe505c5f576e6affb98ecaa9706aa3 \
  -t lemonade-atomic-turboquant:combined-b10269-1.6.0 \
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
  --build-arg TURBOQUANT_VERSION=b10269-1.6.0 \
  --build-arg TURBOQUANT_ASSET=llama-turboquant-linux-x64-vulkan.tar.gz \
  --build-arg TURBOQUANT_SHA256=a0a3bc7b067fbac5e402ff3d603c50eaeffe505c5f576e6affb98ecaa9706aa3 \
  -t lemonade-atomic-turboquant:vulkan-b10269-1.6.0 \
  -f forks/atomic-turboquant/Dockerfile.vulkan .
```

Only the checksums documented above (kingjones30 gfx1151 `b1045`, cachyllama
gfx1151 ROCm `b1036`, cachyllama Vulkan `b1036`, atomic-turboquant ROCm
`b10269-1.6.0`, and atomic-turboquant Vulkan `b10269-1.6.0`) are pinned and
verified in this repo. For any other release/asset, download the asset
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
   directory, already pointed at the right `llama-server` binary and default
   backend for that image.
3. Edit `./config/<image-name>/config.json` directly on the host at any
   time and restart the container -- your edits are preserved, since the
   entrypoint only seeds the file when it doesn't exist yet.

For combined ROCm+Vulkan images, the seeded config defaults to
`llamacpp.backend = "rocm"` and includes both `rocm_bin` and `vulkan_bin`.
To test the Vulkan backend from the same image, edit the mounted
`config.json`, change `backend` to `vulkan`, and restart the container.

See `docker-compose.yml` for worked examples (combined ROCm+Vulkan and
Vulkan-only images), including the
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
ghcr.io/<you>/lemonade-rocmfpx-kingjones30:combined-b1045-gfx1151
ghcr.io/<you>/lemonade-cachyllama:combined-b1036-gfx1151
ghcr.io/<you>/lemonade-cachyllama:vulkan-b1036
ghcr.io/<you>/lemonade-atomic-turboquant:combined-b10269-1.6.0
ghcr.io/<you>/lemonade-atomic-turboquant:vulkan-b10269-1.6.0
```

```sh
docker tag lemonade-atomic-turboquant:combined-b10269-1.6.0 \
  ghcr.io/<you>/lemonade-atomic-turboquant:combined-b10269-1.6.0
docker push ghcr.io/<you>/lemonade-atomic-turboquant:combined-b10269-1.6.0
```
