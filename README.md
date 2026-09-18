# lemonade-containers

Build custom Docker images that run [Lemonade Server](https://github.com/lemonade-sdk/lemonade)
with swappable llama.cpp forks/binaries baked in. The goal is one immutable
image per fork/version/backend/GPU-target variant, so testing another fork is
`docker run <different image tag>` instead of execing into containers or
juggling bind-mounted binaries/config files.

No GHCR images have been published from this repository yet, so the base-image
package split in this version is a safe pre-publication correction.

## Layout

```
base/
  Dockerfile            # lemonade-runtime: pinned Lemonade + entrypoint + groups
  Dockerfile.rocm       # lemonade-rocm-runtime: common runtime + ROCm apt userspace
  docker-entrypoint.sh  # seeds config.json into mounted config dir on first run
forks/
  rocmfpx-heretek/
    Dockerfile           # Heretek-AI/ROCmFPX-BUILDER combined HIP+Vulkan
    config.default.json
  cachyllama-heretek/
    Dockerfile           # Heretek-AI/CachyLLama-BUILDER combined ROCm+Vulkan
    Dockerfile.vulkan    # same fork, Vulkan-only asset
    config.default.json
    config.default.vulkan.json
  atomic-turboquant/
    Dockerfile              # AtomicBot-ai/atomic-llama-cpp-turboquant ROCm+Vulkan
    Dockerfile.vulkan       # same fork, Vulkan-only asset
    config.default.combined.json
    config.default.vulkan.json
docker-compose.yml
config/                 # example bind-mount targets for docker-compose.yml
```

## Runtime base layers

### `lemonade-runtime` (`base/Dockerfile`)

Builds `FROM ghcr.io/lemonade-sdk/lemonade-server:v11.9.0`, a pinned Lemonade
release tag. It adds only shared runtime behavior:

- common build/download tools used by derived Dockerfiles (`ca-certificates`,
  `curl`, `unzip`);
- idempotent `render`/`video` group creation plus `usermod -aG render,video
  lemonade`, so the unprivileged Lemonade user can use `/dev/kfd` and
  `/dev/dri` when devices/groups are passed at runtime;
- `/usr/local/bin/lemonade-entrypoint`, which seeds
  `${HOME}/.config/lemonade/config.json` from the image's
  `/usr/local/share/lemonade/config.default.json` on first start;
- the inherited server command:
  `ENTRYPOINT ["/usr/local/bin/lemonade-entrypoint"]` and
  `CMD ["./lemond", "--host", "0.0.0.0"]`.

It intentionally contains **no ROCm apt repository/packages** and sets no
`/opt/rocm` `LD_LIBRARY_PATH`.

```sh
docker build \
  -t lemonade-runtime:lemonade-v11.9.0 \
  -f base/Dockerfile base
```

### `lemonade-rocm-runtime` (`base/Dockerfile.rocm`)

Builds `FROM lemonade-runtime:lemonade-v11.9.0` and adds ROCm 7.2.1 userspace
libraries from `repo.radeon.com`: `rocm-libs hip-runtime-amd rocblas hipblas`.
It sets `LD_LIBRARY_PATH=/opt/rocm/lib` and prepends `/opt/rocm/bin` to `PATH`.
Use this base only for upstream fork distributions that require ROCm libraries
from the container.

```sh
docker build \
  --build-arg BASE_IMAGE=lemonade-runtime:lemonade-v11.9.0 \
  --build-arg ROCM_VERSION=7.2.1 \
  --build-arg UBUNTU_CODENAME=noble \
  -t lemonade-rocm-runtime:rocm-7.2.1 \
  -f base/Dockerfile.rocm base
```

## Which fork uses which base?

| Image | Base | Why |
| --- | --- | --- |
| Atomic TurboQuant combined ROCm+Vulkan | `lemonade-rocm-runtime` | Atomic's ROCm release does not bundle full ROCm userspace, so the container must provide ROCm libraries. |
| Atomic TurboQuant Vulkan-only | `lemonade-runtime` | Vulkan needs no ROCm apt runtime. |
| CachyLlama Heretek combined ROCm+Vulkan | `lemonade-runtime` | Heretek ROCm archives bundle sibling ROCm libraries with `$ORIGIN` RPATH. |
| CachyLlama Heretek Vulkan-only | `lemonade-runtime` | Vulkan needs no ROCm apt runtime. |
| ROCmFPX Heretek combined HIP+Vulkan | `lemonade-runtime` | Heretek ROCm archives bundle sibling ROCm libraries with `$ORIGIN` RPATH. |

The Heretek ROCm images deliberately avoid `lemonade-rocm-runtime`; a global
`LD_LIBRARY_PATH=/opt/rocm/lib` could shadow the bundled libraries that were
built against moving TheRock nightly versions.

## Fork builds

Every fork Dockerfile downloads pinned upstream release assets over HTTPS,
verifies them with `sha256sum --check --strict`, extracts each upstream archive
whole so sibling shared libraries and `$ORIGIN` RPATH continue to work, and
copies a backend-specific `config.default.json`.

### ROCmFPX Heretek combined HIP+Vulkan

[Heretek-AI/ROCmFPX-BUILDER](https://github.com/Heretek-AI/ROCmFPX-BUILDER)
publishes per-GPU-target zip archives for multiple ROCmFPX forks. The current
Linux build enables both `GGML_HIP` and `GGML_VULKAN`, but upstream does not
publish a standalone Vulkan-only Linux artifact, so the same `llama-server`
path is exposed as both `rocm_bin` and `vulkan_bin`.

```sh
docker build \
  --build-arg BASE_IMAGE=lemonade-runtime:lemonade-v11.9.0 \
  --build-arg ROCMFPX_VERSION=b1045 \
  --build-arg ROCMFPX_ASSET=kingjones-rocmfpx-b1045-ubuntu-rocm-gfx1151-x64.zip \
  --build-arg ROCMFPX_SHA256=75ecc080e75e59f55c047eff9023d41ff0c085fc2d8ac83cb953ebd810e51b28 \
  -t lemonade-rocmfpx:combined-b1045-gfx1151 \
  -f forks/rocmfpx-heretek/Dockerfile forks/rocmfpx-heretek
```

### CachyLlama Heretek combined ROCm+Vulkan

[Heretek-AI/CachyLLama-BUILDER](https://github.com/Heretek-AI/CachyLLama-BUILDER)
wraps `fewtarius/CachyLLama` + `fewtarius/llama-ai`. Its ROCm zip bundles the
runtime libraries it was built with, so this image uses the common runtime base.

```sh
docker build \
  --build-arg BASE_IMAGE=lemonade-runtime:lemonade-v11.9.0 \
  --build-arg CACHYLLAMA_VERSION=b1036 \
  --build-arg CACHYLLAMA_ROCM_ASSET=cachy-llama-b1036-ubuntu-rocm-gfx1151-x64.zip \
  --build-arg CACHYLLAMA_ROCM_SHA256=b56cf63a6895f03173b7a2e4389ea2266241ade3c87ab6557cb14909f02c75b4 \
  --build-arg CACHYLLAMA_VULKAN_ASSET=cachy-llama-bin-ubuntu-vulkan-x64.tar.gz \
  --build-arg CACHYLLAMA_VULKAN_SHA256=7241a3611f3bbea1e3a852178f73ed8376017c21fce5c116094cc8380e476604 \
  -t lemonade-cachyllama:combined-b1036-gfx1151 \
  -f forks/cachyllama-heretek/Dockerfile forks/cachyllama-heretek
```

Other ROCm GPU targets (`gfx1150`, `gfx110X`, `gfx103X`, `gfx90a`, `gfx908`,
`gfx120X`) are available from the same release; download the matching asset
and compute its sha256 yourself.

### CachyLlama Heretek Vulkan-only

```sh
docker build \
  --build-arg BASE_IMAGE=lemonade-runtime:lemonade-v11.9.0 \
  --build-arg CACHYLLAMA_VERSION=b1036 \
  --build-arg CACHYLLAMA_ASSET=cachy-llama-bin-ubuntu-vulkan-x64.tar.gz \
  --build-arg CACHYLLAMA_SHA256=7241a3611f3bbea1e3a852178f73ed8376017c21fce5c116094cc8380e476604 \
  -t lemonade-cachyllama:vulkan-b1036 \
  -f forks/cachyllama-heretek/Dockerfile.vulkan .
```

### Atomic TurboQuant combined ROCm+Vulkan

[AtomicBot-ai/atomic-llama-cpp-turboquant](https://github.com/AtomicBot-ai/atomic-llama-cpp-turboquant)
publishes one tarball per backend. Its ROCm tarball requires ROCm libraries
from the container, so the combined image uses `lemonade-rocm-runtime`.

```sh
docker build \
  --build-arg BASE_IMAGE=lemonade-rocm-runtime:rocm-7.2.1 \
  --build-arg TURBOQUANT_VERSION=b10269-1.6.0 \
  --build-arg TURBOQUANT_ROCM_ASSET=llama-turboquant-linux-x64-rocm.tar.gz \
  --build-arg TURBOQUANT_ROCM_SHA256=e7758e3191827460de13976284160878d02920acb17d54007bd548521def7dc9 \
  --build-arg TURBOQUANT_VULKAN_ASSET=llama-turboquant-linux-x64-vulkan.tar.gz \
  --build-arg TURBOQUANT_VULKAN_SHA256=a0a3bc7b067fbac5e402ff3d603c50eaeffe505c5f576e6affb98ecaa9706aa3 \
  -t lemonade-atomic-turboquant:combined-b10269-1.6.0 \
  -f forks/atomic-turboquant/Dockerfile forks/atomic-turboquant
```

### Atomic TurboQuant Vulkan-only

```sh
docker build \
  --build-arg BASE_IMAGE=lemonade-runtime:lemonade-v11.9.0 \
  --build-arg TURBOQUANT_VERSION=b10269-1.6.0 \
  --build-arg TURBOQUANT_ASSET=llama-turboquant-linux-x64-vulkan.tar.gz \
  --build-arg TURBOQUANT_SHA256=a0a3bc7b067fbac5e402ff3d603c50eaeffe505c5f576e6affb98ecaa9706aa3 \
  -t lemonade-atomic-turboquant:vulkan-b10269-1.6.0 \
  -f forks/atomic-turboquant/Dockerfile.vulkan .
```

Only the checksums shown above are pinned and verified in this repo. For any
other release/asset, download the asset and run `sha256sum` yourself; do not
reuse or guess a checksum for a different file.

## Config: auto-created on first run

Every image's entrypoint checks `${HOME}/.config/lemonade/config.json`
(`HOME` is `/opt/lemonade` in the upstream image). If it is missing, the file
is copied from `/usr/local/share/lemonade/config.default.json`.

Bind-mount a directory such as `./config/<image-name>` onto
`/opt/lemonade/.config/lemonade`. The first run creates `config.json` in that
host directory; after that, edit it directly on the host and restart the
container. Combined ROCm+Vulkan images default `llamacpp.backend` to `rocm` and
include both `rocm_bin` and `vulkan_bin`, so switching to Vulkan is a config
edit, not an image rebuild.

See `docker-compose.yml` for examples. Binding ports to `127.0.0.1` is safer
than `0.0.0.0` unless you intentionally need LAN access.

## GitHub Actions validation and publishing

`.github/image-matrix.json` is the single source of truth for image keys,
Dockerfile/context paths, GHCR package names, deterministic tags, dependency
keys, cache scopes, and pinned upstream build args/checksums.

- **Validate container images** runs on PRs touching Dockerfiles, configs,
  workflows, the manifest, README, or compose file. It runs static checks,
  validates generated Bake Dockerfile paths, checks GPU group setup, and runs
  BuildKit `--call=check` for every manifest image. Full image builds are
  large because they download ROCm/fork archives, so PRs skip them by default;
  maintainers can run the workflow manually with `full_build=true`.
- **Publish container images** runs on manual dispatch and pushed repository
  version tags matching `v*`. It publishes `lemonade-runtime` first, then
  `lemonade-rocm-runtime` from the runtime digest, then derived images from
  the exact dependency digest declared by the manifest. It uses `GITHUB_TOKEN`
  for GHCR, per-image GitHub Actions cache scopes, OCI labels, provenance, and
  SBOM attestations. It does not publish `latest`.

Default package/tag scheme:

| Image | Package | Default tag | Repo-release tag example |
| --- | --- | --- | --- |
| Common runtime | `ghcr.io/${OWNER}/lemonade-runtime` | `lemonade-v11.9.0` | `v1.0.0-lemonade-v11.9.0` |
| ROCm runtime | `ghcr.io/${OWNER}/lemonade-rocm-runtime` | `rocm-7.2.1` | `v1.0.0-rocm-7.2.1` |
| Atomic TurboQuant combined | `ghcr.io/${OWNER}/lemonade-atomic-turboquant` | `combined-b10269-1.6.0` | `v1.0.0-combined-b10269-1.6.0` |
| Atomic TurboQuant Vulkan-only | `ghcr.io/${OWNER}/lemonade-atomic-turboquant` | `vulkan-b10269-1.6.0` | `v1.0.0-vulkan-b10269-1.6.0` |
| CachyLlama combined | `ghcr.io/${OWNER}/lemonade-cachyllama` | `combined-b1036-gfx1151` | `v1.0.0-combined-b1036-gfx1151` |
| CachyLlama Vulkan-only | `ghcr.io/${OWNER}/lemonade-cachyllama` | `vulkan-b1036` | `v1.0.0-vulkan-b1036` |
| ROCmFPX combined | `ghcr.io/${OWNER}/lemonade-rocmfpx` | `combined-b1045-gfx1151` | `v1.0.0-combined-b1045-gfx1151` |

Example pulls:

```sh
OWNER=<github-owner>
docker pull ghcr.io/${OWNER}/lemonade-runtime:lemonade-v11.9.0
docker pull ghcr.io/${OWNER}/lemonade-rocm-runtime:rocm-7.2.1
docker pull ghcr.io/${OWNER}/lemonade-atomic-turboquant:combined-b10269-1.6.0
docker pull ghcr.io/${OWNER}/lemonade-atomic-turboquant:vulkan-b10269-1.6.0
docker pull ghcr.io/${OWNER}/lemonade-cachyllama:combined-b1036-gfx1151
docker pull ghcr.io/${OWNER}/lemonade-cachyllama:vulkan-b1036
docker pull ghcr.io/${OWNER}/lemonade-rocmfpx:combined-b1045-gfx1151
```

To publish a repository release build:

```sh
git tag v1.0.0
git push origin v1.0.0
```

Or run **Publish container images** manually from the Actions tab and set
`publish_tag` to add `<publish_tag>-<default_tag>` tags alongside default tags.
GHCR packages may initially be private depending on account/repository
settings; make them public in package settings if desired.

`v11.9.0` is pinned because the upstream Lemonade workflow publishes a
`vX.Y.Z` image tag for every pushed Lemonade git tag. Periodically check
<https://github.com/lemonade-sdk/lemonade/releases> and bump this pin manually
instead of using floating `:latest`.
