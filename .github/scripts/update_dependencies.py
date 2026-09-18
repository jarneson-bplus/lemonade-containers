#!/usr/bin/env python3
"""Check upstream releases and update pinned versions, assets, and checksums.

This script is the maintenance half of `.github/image-matrix.json`. It reads the
`update_sources` block, asks GitHub for newer releases of the pinned Lemonade
Server and of every llama.cpp fork represented in the manifest, downloads the
exact candidate assets, computes their SHA-256 checksums, and rewrites the
manifest (plus documentation/Dockerfile/compose references) consistently.

It never guesses: an ambiguous or missing asset, an unverifiable container tag,
or a checksum it could not compute is a hard error. The script only edits files;
opening a pull request and publishing images are deliberately left to the
calling workflow.

Standard library only, no third-party dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GITHUB_API = "https://api.github.com"
GHCR_BASE = "https://ghcr.io"
USER_AGENT = "lemonade-containers-dependency-updater"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BUILD_ARG_RE = re.compile(r"^[A-Z0-9_]+=")
RELEASE_PAGES = 3
RELEASE_PAGE_SIZE = 100
MANIFEST_ACCEPT = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)


class UpdateError(Exception):
    """A problem that must stop an update instead of being guessed around."""


@dataclass
class AssetUpdate:
    asset_id: str
    old_name: str
    new_name: str
    old_sha256: str
    new_sha256: str
    gpu_target: str | None
    download_url: str


@dataclass
class SourceUpdate:
    source_id: str
    name: str
    repository: str
    old_version: str
    new_version: str
    release_url: str
    images: list[str]
    assets: list[AssetUpdate] = field(default_factory=list)
    container_digest: str | None = None
    warnings: list[str] = field(default_factory=list)

    def replacement_pairs(self) -> list[tuple[str, str]]:
        """Literal old -> new pairs, longest first so nested tokens stay intact."""
        pairs = {(self.old_version, self.new_version)}
        for asset in self.assets:
            pairs.add((asset.old_name, asset.new_name))
            pairs.add((asset.old_sha256, asset.new_sha256))
        return sorted(
            (pair for pair in pairs if pair[0] and pair[0] != pair[1]),
            key=lambda pair: len(pair[0]),
            reverse=True,
        )


def http_request(
    url: str,
    token: str | None = None,
    accept: str | None = None,
    method: str = "GET",
) -> urllib.request.addinfourl:
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    if token and url.startswith(GITHUB_API):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method=method)
    return urllib.request.urlopen(request, timeout=120)  # noqa: S310 - fixed https hosts


def http_json(url: str, token: str | None = None, accept: str | None = None) -> Any:
    try:
        with http_request(url, token=token, accept=accept or "application/vnd.github+json") as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:  # pragma: no cover - network failure path
        raise UpdateError(f"HTTP {error.code} for {url}: {error.reason}") from error
    except urllib.error.URLError as error:  # pragma: no cover - network failure path
        raise UpdateError(f"Could not reach {url}: {error.reason}") from error


def apply_pairs(text: str, pairs: list[tuple[str, str]]) -> str:
    for old, new in pairs:
        text = text.replace(old, new)
    return text


def build_args_map(image: dict[str, Any]) -> dict[str, str]:
    args: dict[str, str] = {}
    for entry in image.get("build_args", []):
        name, _, value = entry.partition("=")
        args[name] = value
    return args


def set_build_arg(image: dict[str, Any], name: str, value: str) -> None:
    updated = False
    for index, entry in enumerate(image["build_args"]):
        if entry.split("=", 1)[0] == name:
            image["build_args"][index] = f"{name}={value}"
            updated = True
    if not updated:
        raise UpdateError(f"Image '{image['key']}' has no build arg named {name}")


def find_image(manifest: dict[str, Any], key: str) -> dict[str, Any]:
    for image in manifest["images"]:
        if image["key"] == key:
            return image
    raise UpdateError(f"Manifest has no image with key '{key}'")


def source_image_keys(manifest: dict[str, Any], source: dict[str, Any]) -> list[str]:
    """Images a source owns, cross-checked against the version build arg."""
    if source["kind"] == "lemonade_server":
        return [image["key"] for image in manifest["images"]]

    version_arg = source["version_build_arg"]
    declared: list[str] = []
    for asset in source["assets"]:
        for mapping in asset["build_args"]:
            if mapping["image"] not in declared:
                declared.append(mapping["image"])

    carrying = [
        image["key"] for image in manifest["images"] if version_arg in build_args_map(image)
    ]
    missing = sorted(set(carrying) - set(declared))
    if missing:
        raise UpdateError(
            f"Images {missing} use {version_arg} but are not mapped in update_sources; "
            "add them so every variant of the release is updated together."
        )
    unknown = sorted(set(declared) - set(carrying))
    if unknown:
        raise UpdateError(
            f"update_sources maps images {unknown} that do not declare {version_arg}."
        )
    return declared


def current_version(manifest: dict[str, Any], source: dict[str, Any], image_keys: list[str]) -> str:
    if source["kind"] == "lemonade_server":
        return manifest["upstream"]["lemonade_server"]["version"]

    version_arg = source["version_build_arg"]
    values = {
        build_args_map(find_image(manifest, key))[version_arg] for key in image_keys
    }
    if len(values) != 1:
        raise UpdateError(
            f"Images {image_keys} disagree on {version_arg}: {sorted(values)}. "
            "All variants of a release must stay on the same version."
        )
    return values.pop()


def list_releases(repository: str, token: str | None) -> list[dict[str, Any]]:
    releases: list[dict[str, Any]] = []
    for page in range(1, RELEASE_PAGES + 1):
        url = f"{GITHUB_API}/repos/{repository}/releases?per_page={RELEASE_PAGE_SIZE}&page={page}"
        page_items = http_json(url, token=token)
        if not isinstance(page_items, list):
            raise UpdateError(f"Unexpected releases payload for {repository}")
        releases.extend(page_items)
        if len(page_items) < RELEASE_PAGE_SIZE:
            break
    return releases


def release_by_tag(repository: str, tag: str, token: str | None) -> dict[str, Any] | None:
    url = f"{GITHUB_API}/repos/{repository}/releases/tags/{urllib.parse.quote(tag, safe='')}"
    try:
        return http_json(url, token=token)
    except UpdateError as error:
        if "HTTP 404" in str(error):
            return None
        raise


def select_candidate(
    releases: list[dict[str, Any]], source: dict[str, Any], repository: str
) -> dict[str, Any]:
    pattern = re.compile(source["tag_pattern"])
    include_prereleases = bool(source.get("include_prereleases", False))
    matching = [
        release
        for release in releases
        if not release.get("draft")
        and (include_prereleases or not release.get("prerelease"))
        and pattern.match(release.get("tag_name", ""))
    ]
    if not matching:
        raise UpdateError(
            f"No release of {repository} matched tag_pattern {source['tag_pattern']!r}; "
            "the upstream tag scheme may have changed."
        )
    matching.sort(key=lambda release: (release.get("published_at") or "", release.get("created_at") or ""))
    return matching[-1]


def resolve_asset(
    release: dict[str, Any], asset_config: dict[str, Any], version: str, repository: str
) -> dict[str, Any]:
    pattern_text = asset_config["asset_pattern"].replace("{version}", re.escape(version))
    pattern = re.compile(pattern_text)
    matches = [
        asset for asset in release.get("assets", []) if pattern.match(asset.get("name", ""))
    ]
    available = sorted(asset.get("name", "") for asset in release.get("assets", []))
    if not matches:
        raise UpdateError(
            f"{repository} release {release['tag_name']} has no asset matching "
            f"{pattern_text!r} (asset id '{asset_config['id']}'). Available assets: {available}"
        )
    if len(matches) > 1:
        names = sorted(asset["name"] for asset in matches)
        raise UpdateError(
            f"{repository} release {release['tag_name']} has ambiguous assets for "
            f"{pattern_text!r} (asset id '{asset_config['id']}'): {names}"
        )
    return matches[0]


def download_sha256(asset: dict[str, Any], token: str | None) -> str:
    url = asset["browser_download_url"]
    digest = hashlib.sha256()
    downloaded = 0
    try:
        with http_request(url, token=token, accept="application/octet-stream") as response:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                downloaded += len(chunk)
    except urllib.error.HTTPError as error:
        raise UpdateError(f"HTTP {error.code} downloading {url}: {error.reason}") from error
    except urllib.error.URLError as error:
        raise UpdateError(f"Could not download {url}: {error.reason}") from error

    expected_size = asset.get("size")
    if expected_size and downloaded != expected_size:
        raise UpdateError(
            f"Downloaded {downloaded} bytes from {url} but the release reports {expected_size}."
        )
    if downloaded == 0:
        raise UpdateError(f"Downloaded an empty asset from {url}")
    return digest.hexdigest()


def container_tag_digest(image: str, tag: str) -> str:
    """Confirm a GHCR tag really exists before pinning it, and return its digest."""
    if not image.startswith("ghcr.io/"):
        raise UpdateError(f"Only ghcr.io container images can be verified, got {image}")
    repository = image[len("ghcr.io/") :]
    token_url = f"{GHCR_BASE}/token?service=ghcr.io&scope=repository:{repository}:pull"
    token_payload = http_json(token_url, accept="application/json")
    registry_token = token_payload.get("token")
    if not registry_token:
        raise UpdateError(f"Could not obtain an anonymous pull token for {image}")

    url = f"{GHCR_BASE}/v2/{repository}/manifests/{urllib.parse.quote(tag, safe='')}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": MANIFEST_ACCEPT,
            "Authorization": f"Bearer {registry_token}",
        },
        method="HEAD",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed https host
            digest = response.headers.get("Docker-Content-Digest", "")
    except urllib.error.HTTPError as error:
        raise UpdateError(
            f"{image}:{tag} is not published yet (HTTP {error.code}); refusing to pin it."
        ) from error
    except urllib.error.URLError as error:
        raise UpdateError(f"Could not reach {GHCR_BASE}: {error.reason}") from error
    if not digest:
        raise UpdateError(f"{image}:{tag} returned no content digest; refusing to pin it.")
    return digest


def plan_source(
    manifest: dict[str, Any],
    source_id: str,
    source: dict[str, Any],
    token: str | None,
    download: bool,
) -> SourceUpdate | None:
    repository = source["repository"]
    image_keys = source_image_keys(manifest, source)
    old_version = current_version(manifest, source, image_keys)

    releases = list_releases(repository, token)
    candidate = select_candidate(releases, source, repository)
    new_version = candidate["tag_name"]
    if new_version == old_version:
        return None

    pinned = release_by_tag(repository, old_version, token)
    if pinned is None:
        raise UpdateError(
            f"Pinned {repository} release {old_version} no longer exists upstream; "
            "resolve this by hand instead of letting the updater pick a replacement."
        )
    if (candidate.get("published_at") or "") <= (pinned.get("published_at") or ""):
        return None

    update = SourceUpdate(
        source_id=source_id,
        name=source.get("name", source_id),
        repository=repository,
        old_version=old_version,
        new_version=new_version,
        release_url=candidate.get("html_url", ""),
        images=image_keys,
    )

    if source["kind"] == "lemonade_server":
        update.container_digest = container_tag_digest(source["container_image"], new_version)
        return update

    for asset_config in source["assets"]:
        asset = resolve_asset(candidate, asset_config, new_version, repository)
        first_mapping = asset_config["build_args"][0]
        owner_image = find_image(manifest, first_mapping["image"])
        owner_args = build_args_map(owner_image)
        old_name = owner_args[first_mapping["asset"]]
        old_sha = owner_args[first_mapping["sha256"]]

        if download:
            new_sha = download_sha256(asset, token)
            if not SHA256_RE.match(new_sha):
                raise UpdateError(f"Computed an invalid sha256 for {asset['name']}")
        else:
            new_sha = old_sha

        update.assets.append(
            AssetUpdate(
                asset_id=asset_config["id"],
                old_name=old_name,
                new_name=asset["name"],
                old_sha256=old_sha,
                new_sha256=new_sha,
                gpu_target=asset_config.get("gpu_target"),
                download_url=asset["browser_download_url"],
            )
        )
    return update


def apply_to_manifest(
    manifest: dict[str, Any], source: dict[str, Any], update: SourceUpdate
) -> None:
    version_pair = [(update.old_version, update.new_version)]
    is_lemonade = source["kind"] == "lemonade_server"

    if is_lemonade:
        lemonade = manifest["upstream"]["lemonade_server"]
        lemonade["version"] = update.new_version
        lemonade["image"] = f"{source['container_image']}:{update.new_version}"
    else:
        for key in update.images:
            set_build_arg(find_image(manifest, key), source["version_build_arg"], update.new_version)
        for asset_config, asset_update in zip(source["assets"], update.assets, strict=True):
            for mapping in asset_config["build_args"]:
                image = find_image(manifest, mapping["image"])
                set_build_arg(image, mapping["asset"], asset_update.new_name)
                set_build_arg(image, mapping["sha256"], asset_update.new_sha256)

    # Deterministic tags and cache scopes embed the version, and a Lemonade base
    # bump also rewrites every derived BASE_IMAGE reference.
    for key in update.images:
        image = find_image(manifest, key)
        image["default_tag"] = apply_pairs(image["default_tag"], version_pair)
        image["cache_scope"] = apply_pairs(image["cache_scope"], version_pair)
        if is_lemonade:
            image["build_args"] = [apply_pairs(entry, version_pair) for entry in image["build_args"]]

    for image in manifest["images"]:
        for entry in image["build_args"]:
            if not BUILD_ARG_RE.match(entry):
                raise UpdateError(f"Image '{image['key']}' produced an invalid build arg: {entry}")


def propagate_to_files(
    repo_root: Path, source: dict[str, Any], update: SourceUpdate
) -> list[Path]:
    pairs = update.replacement_pairs()
    changed: list[Path] = []
    for relative in source.get("propagate_files", []):
        path = repo_root / relative
        if not path.is_file():
            raise UpdateError(f"propagate_files entry does not exist: {relative}")
        original = path.read_text(encoding="utf-8")
        updated = apply_pairs(original, pairs)
        if updated != original:
            path.write_text(updated, encoding="utf-8", newline="")
            changed.append(path)
        if update.old_version in updated:
            update.warnings.append(
                f"{relative} still mentions {update.old_version} after the update; review it by hand."
            )
    return changed


def verify_manifest(manifest: dict[str, Any]) -> None:
    """Invariants that must hold after any update, before a PR is opened."""
    lemonade = manifest["upstream"]["lemonade_server"]
    expected_image_suffix = f":{lemonade['version']}"
    if not lemonade["image"].endswith(expected_image_suffix):
        raise UpdateError(
            f"upstream.lemonade_server.image {lemonade['image']} does not match version {lemonade['version']}"
        )

    runtime = find_image(manifest, "runtime")
    expected_runtime_tag = f"lemonade-{lemonade['version']}"
    if runtime["default_tag"] != expected_runtime_tag:
        raise UpdateError(
            f"runtime default_tag {runtime['default_tag']} should be {expected_runtime_tag}"
        )
    if build_args_map(runtime).get("BASE_IMAGE") != lemonade["image"]:
        raise UpdateError("runtime BASE_IMAGE must equal upstream.lemonade_server.image")

    runtime_ref = f"lemonade-runtime:{runtime['default_tag']}"
    for image in manifest["images"]:
        base_image = build_args_map(image).get("BASE_IMAGE")
        if base_image and base_image.startswith("lemonade-runtime:") and base_image != runtime_ref:
            raise UpdateError(
                f"Image '{image['key']}' pins stale base {base_image}, expected {runtime_ref}"
            )
        for entry in image["build_args"]:
            name, _, value = entry.partition("=")
            if name.endswith("_SHA256") and not SHA256_RE.match(value):
                raise UpdateError(f"Image '{image['key']}' has a malformed {name}: {value}")

    cache_scopes = [image["cache_scope"] for image in manifest["images"]]
    if len(cache_scopes) != len(set(cache_scopes)):
        raise UpdateError("Manifest cache_scope values must stay unique")


def validate_config(manifest: dict[str, Any], repo_root: Path) -> None:
    sources = manifest.get("update_sources")
    if not isinstance(sources, dict) or not sources:
        raise UpdateError("Manifest is missing a non-empty update_sources object")

    for source_id, source in sources.items():
        kind = source.get("kind")
        if kind not in {"lemonade_server", "github_release_assets"}:
            raise UpdateError(f"Source '{source_id}' has unsupported kind {kind!r}")
        if not source.get("repository") or "/" not in source["repository"]:
            raise UpdateError(f"Source '{source_id}' needs an 'owner/repo' repository")
        try:
            re.compile(source["tag_pattern"])
        except (KeyError, re.error) as error:
            raise UpdateError(f"Source '{source_id}' has an invalid tag_pattern: {error}") from error

        for relative in source.get("propagate_files", []):
            if not (repo_root / relative).is_file():
                raise UpdateError(f"Source '{source_id}' lists missing file {relative}")

        if kind == "lemonade_server":
            image = source.get("container_image", "")
            if not image.startswith("ghcr.io/"):
                raise UpdateError(f"Source '{source_id}' needs a ghcr.io container_image")
            if manifest["upstream"]["lemonade_server"]["image"] != (
                f"{image}:{manifest['upstream']['lemonade_server']['version']}"
            ):
                raise UpdateError(
                    f"Source '{source_id}' container_image disagrees with upstream.lemonade_server.image"
                )
            continue

        if not source.get("assets"):
            raise UpdateError(f"Source '{source_id}' needs at least one asset rule")
        version_arg = source.get("version_build_arg", "")
        if not BUILD_ARG_RE.match(f"{version_arg}="):
            raise UpdateError(f"Source '{source_id}' has an invalid version_build_arg")

        seen_ids: set[str] = set()
        for asset in source["assets"]:
            asset_id = asset.get("id", "")
            if not asset_id or asset_id in seen_ids:
                raise UpdateError(f"Source '{source_id}' has a missing/duplicate asset id {asset_id!r}")
            seen_ids.add(asset_id)
            try:
                re.compile(asset["asset_pattern"].replace("{version}", "0"))
            except (KeyError, re.error) as error:
                raise UpdateError(
                    f"Source '{source_id}' asset '{asset_id}' has an invalid asset_pattern: {error}"
                ) from error
            if not asset.get("build_args"):
                raise UpdateError(f"Source '{source_id}' asset '{asset_id}' maps no build args")
            for mapping in asset["build_args"]:
                image = find_image(manifest, mapping["image"])
                args = build_args_map(image)
                for field_name in ("asset", "sha256"):
                    arg_name = mapping[field_name]
                    if arg_name not in args:
                        raise UpdateError(
                            f"Image '{image['key']}' has no build arg {arg_name} "
                            f"referenced by source '{source_id}' asset '{asset_id}'"
                        )
                if not SHA256_RE.match(args[mapping["sha256"]]):
                    raise UpdateError(
                        f"Image '{image['key']}' build arg {mapping['sha256']} is not a sha256 digest"
                    )
                if version_arg not in args:
                    raise UpdateError(
                        f"Image '{image['key']}' has no {version_arg} build arg "
                        f"required by source '{source_id}'"
                    )

        source_image_keys(manifest, source)
        current_version(manifest, source, source_image_keys(manifest, source))

    verify_manifest(manifest)


def render_summary(updates: list[SourceUpdate], errors: list[str], dry_run: bool) -> str:
    lines: list[str] = []
    if not updates:
        lines.append("No upstream updates were found.")
    else:
        lines.append("## Pinned dependency updates")
        lines.append("")
        for update in updates:
            lines.append(
                f"### {update.name} (`{update.source_id}`): `{update.old_version}` -> `{update.new_version}`"
            )
            lines.append("")
            lines.append(f"- Upstream repository: `{update.repository}`")
            if update.release_url:
                lines.append(f"- Release: {update.release_url}")
            if update.container_digest:
                lines.append(f"- Verified container digest: `{update.container_digest}`")
            lines.append(f"- Manifest images updated: {', '.join(f'`{key}`' for key in update.images)}")
            for asset in update.assets:
                target = f" ({asset.gpu_target})" if asset.gpu_target else ""
                lines.append(f"- Asset `{asset.asset_id}`{target}: `{asset.new_name}`")
                lines.append(f"  - sha256 `{asset.new_sha256}`")
                lines.append(f"  - downloaded from {asset.download_url}")
            for warning in update.warnings:
                lines.append(f"- :warning: {warning}")
            lines.append("")

    if errors:
        lines.append("## Sources that failed")
        lines.append("")
        lines.extend(f"- {error}" for error in errors)
        lines.append("")

    if dry_run:
        lines.append("_Dry run: no files were modified._")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_github_output(path: str, values: dict[str, str]) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            if "\n" in value:
                handle.write(f"{key}<<__EOF__\n{value}\n__EOF__\n")
            else:
                handle.write(f"{key}={value}\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", default=".github/image-matrix.json")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated update_sources ids to consider (default: all)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Report available updates without downloading assets or writing files",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Apply the sources that succeeded even if another source failed",
    )
    parser.add_argument(
        "--validate-config",
        action="store_true",
        help="Validate update_sources and manifest invariants offline, then exit",
    )
    parser.add_argument("--summary-file", default="")
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT", ""))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    manifest_path = (repo_root / args.manifest).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    try:
        validate_config(manifest, repo_root)
    except UpdateError as error:
        print(f"update_sources configuration is invalid: {error}", file=sys.stderr)
        return 1

    if args.validate_config:
        print("update_sources configuration and manifest invariants are valid.")
        return 0

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or None
    if not token:
        print("No GITHUB_TOKEN/GH_TOKEN set; using unauthenticated API rate limits.", file=sys.stderr)

    selected = [item.strip() for item in args.only.split(",") if item.strip()]
    sources: dict[str, Any] = manifest["update_sources"]
    unknown = sorted(set(selected) - set(sources))
    if unknown:
        print(f"Unknown update source ids requested: {unknown}", file=sys.stderr)
        return 1

    updates: list[SourceUpdate] = []
    errors: list[str] = []
    for source_id, source in sources.items():
        if selected and source_id not in selected:
            continue
        print(f"Checking {source_id} ({source['repository']})...")
        try:
            update = plan_source(
                manifest, source_id, source, token, download=not args.check_only
            )
        except UpdateError as error:
            errors.append(f"`{source_id}`: {error}")
            print(f"  ERROR: {error}", file=sys.stderr)
            continue
        if update is None:
            print("  up to date")
            continue
        print(f"  update available: {update.old_version} -> {update.new_version}")
        updates.append(update)

    if errors and not args.allow_partial:
        summary = render_summary([], errors, dry_run=True)
        if args.summary_file:
            Path(args.summary_file).write_text(summary, encoding="utf-8")
        if args.github_output:
            write_github_output(args.github_output, {"has_updates": "false", "sources": ""})
        print(
            "Refusing to write partial updates. Re-run with --allow-partial to apply the "
            "sources that succeeded.",
            file=sys.stderr,
        )
        return 1

    if updates and not args.check_only:
        for update in updates:
            source = sources[update.source_id]
            apply_to_manifest(manifest, source, update)
            propagate_to_files(repo_root, source, update)
        try:
            verify_manifest(manifest)
        except UpdateError as error:
            print(f"Post-update validation failed, nothing was written: {error}", file=sys.stderr)
            return 1
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="",
        )
        # Re-read to guarantee the file we just wrote is valid JSON.
        json.loads(manifest_path.read_text(encoding="utf-8"))

    summary = render_summary(updates, errors, dry_run=args.check_only)
    if args.summary_file:
        Path(args.summary_file).write_text(summary, encoding="utf-8")
    print(summary)

    if args.github_output:
        write_github_output(
            args.github_output,
            {
                "has_updates": "true" if updates else "false",
                "sources": ", ".join(
                    f"{update.source_id} {update.old_version} -> {update.new_version}"
                    for update in updates
                ),
            },
        )

    if errors and not args.allow_partial:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
