"""Minimal OCI registry client — pull files out of a container image.

The os-rpi deployment pins an exact `firmware-image-server` container, and
that container *is* the firmware bundle: it ships the matching `.bin` files
under /srv and serves them over HTTP on the microscope.  Pulling that image
therefore gives us exactly the firmware that belongs to a given SD card
image — no tag guessing, no release-name matching.

This implements just enough of the OCI distribution spec (anonymous token,
manifest index → platform manifest, blob download, tar extraction) to do
that without requiring docker on the station.
"""

from __future__ import annotations

import io
import re
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import httpx

ACCEPT = ",".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)

IMAGE_REF_RE = re.compile(
    r"^(?:(?P<registry>[\w.\-]+(?::\d+)?)/)?"
    r"(?P<repo>[\w.\-/]+?)"
    r"(?::(?P<tag>[\w.\-]+))?"
    r"(?:@(?P<digest>sha256:[0-9a-f]+))?$"
)


class OCIError(RuntimeError):
    pass


@dataclass
class ImageRef:
    registry: str
    repo: str
    tag: str
    digest: str | None = None

    @property
    def reference(self) -> str:
        """What to ask the registry for — digest wins over tag."""
        return self.digest or self.tag

    def __str__(self) -> str:
        base = f"{self.registry}/{self.repo}:{self.tag}"
        return f"{base}@{self.digest}" if self.digest else base


def parse_ref(ref: str, default_registry: str = "ghcr.io") -> ImageRef:
    m = IMAGE_REF_RE.match(ref.strip())
    if not m:
        raise OCIError(f"Cannot parse image reference: {ref}")
    registry = m.group("registry") or default_registry
    repo = m.group("repo")
    # "ghcr.io/foo/bar" parses registry=ghcr.io; but "foo/bar" has no registry
    # and the first segment may be a host — only treat it as one if it looks
    # like a hostname (contains a dot or a port).
    if m.group("registry") and "." not in registry and ":" not in registry:
        repo = f"{registry}/{repo}"
        registry = default_registry
    return ImageRef(
        registry=registry,
        repo=repo,
        tag=m.group("tag") or "latest",
        digest=m.group("digest"),
    )


class OCIClient:
    """Read-only OCI registry client (anonymous or bearer-token auth)."""

    def __init__(self, token: str = "") -> None:
        self.token = token
        self._cached_tokens: dict[str, str] = {}

    def _auth_token(self, ref: ImageRef, client: httpx.Client) -> str:
        key = f"{ref.registry}/{ref.repo}"
        if key in self._cached_tokens:
            return self._cached_tokens[key]
        # ghcr.io (and Docker Hub) hand out pull tokens; for public images the
        # request needs no credentials, but a GitHub token raises rate limits
        # and unlocks private packages.
        params = {"scope": f"repository:{ref.repo}:pull", "service": ref.registry}
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        r = client.get(f"https://{ref.registry}/token", params=params, headers=headers)
        if r.status_code != 200:
            raise OCIError(f"Registry auth failed ({r.status_code}) for {ref.repo}")
        tok = r.json().get("token") or r.json().get("access_token", "")
        self._cached_tokens[key] = tok
        return tok

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=120, follow_redirects=True)

    def get_manifest(self, ref: ImageRef, arch: str = "arm64") -> dict:
        with self._client() as c:
            tok = self._auth_token(ref, c)
            h = {"Authorization": f"Bearer {tok}", "Accept": ACCEPT}
            r = c.get(
                f"https://{ref.registry}/v2/{ref.repo}/manifests/{ref.reference}",
                headers=h,
            )
            if r.status_code == 404:
                raise OCIError(f"Image not found: {ref}")
            if r.status_code != 200:
                raise OCIError(f"Manifest fetch failed ({r.status_code}) for {ref}")
            manifest = r.json()

            if "manifests" in manifest:  # multi-arch index
                candidates = [
                    e
                    for e in manifest["manifests"]
                    if (e.get("platform") or {}).get("os") == "linux"
                    and (e.get("platform") or {}).get("architecture")
                    not in (None, "unknown")
                ]
                if not candidates:
                    raise OCIError(f"No linux platform manifest in index for {ref}")
                pick = next(
                    (e for e in candidates if e["platform"]["architecture"] == arch),
                    candidates[0],
                )
                r = c.get(
                    f"https://{ref.registry}/v2/{ref.repo}/manifests/{pick['digest']}",
                    headers=h,
                )
                r.raise_for_status()
                manifest = r.json()
            return manifest

    def extract_files(
        self,
        ref: ImageRef,
        dest: Path,
        want: Callable[[str], bool],
        arch: str = "arm64",
        progress: Callable[[float, str], None] = lambda f, m: None,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> list[Path]:
        """Download the image's layers and extract every file whose *base
        name* satisfies `want`, flattened into `dest`.

        Later layers win, matching container filesystem semantics.
        """
        manifest = self.get_manifest(ref, arch=arch)
        layers = manifest.get("layers", [])
        if not layers:
            raise OCIError(f"No layers in manifest for {ref}")
        dest.mkdir(parents=True, exist_ok=True)
        written: dict[str, Path] = {}

        with self._client() as c:
            tok = self._auth_token(ref, c)
            h = {"Authorization": f"Bearer {tok}"}
            total = sum(lay.get("size") or 0 for lay in layers) or 1
            done = 0
            for i, lay in enumerate(layers):
                if cancelled():
                    raise OCIError("cancelled")
                progress(done / total, f"Layer {i + 1}/{len(layers)}")
                r = c.get(
                    f"https://{ref.registry}/v2/{ref.repo}/blobs/{lay['digest']}",
                    headers=h,
                )
                r.raise_for_status()
                done += len(r.content)
                try:
                    tf = tarfile.open(fileobj=io.BytesIO(r.content), mode="r:*")
                except tarfile.TarError:
                    continue  # non-tar layer (attestation etc.)
                with tf:
                    for member in tf.getmembers():
                        if not member.isfile() or member.size <= 0:
                            continue
                        name = Path(member.name).name
                        if name.startswith(".wh."):  # whiteout marker
                            written.pop(name.removeprefix(".wh."), None)
                            continue
                        if not want(name):
                            continue
                        src = tf.extractfile(member)
                        if src is None:
                            continue
                        target = dest / name
                        with open(target, "wb") as f:
                            while chunk := src.read(1 << 20):
                                f.write(chunk)
                        written[name] = target
                progress(done / total, f"Layer {i + 1}/{len(layers)}")
        return sorted(written.values())

    def list_tags(self, ref: ImageRef, limit: int = 100) -> list[str]:
        with self._client() as c:
            tok = self._auth_token(ref, c)
            r = c.get(
                f"https://{ref.registry}/v2/{ref.repo}/tags/list",
                headers={"Authorization": f"Bearer {tok}"},
                params={"n": limit},
            )
            if r.status_code != 200:
                return []
            return r.json().get("tags", [])
