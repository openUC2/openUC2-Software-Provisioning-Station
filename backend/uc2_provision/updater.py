"""Self-update: pull the latest station software and restart.

The station is installed as a git checkout at /opt/uc2-provision (see
scripts/install.sh), so updating is `git fetch` + `git reset --hard` onto the
tracked branch.  The frontend is **not** built here — a Pi building Vite
bundles is slow and needs a node toolchain — instead CI builds
`frontend/dist` and commits it, so pulling the repo delivers backend and
frontend together as one consistent bundle.

Restarting is deliberately detached from the request: the service restart
kills this very process, so it is scheduled a moment later, giving the job
time to record its final state and the UI time to notice the reconnect.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from .jobs import Job

# The repo root as installed: .../backend/uc2_provision/updater.py -> ../../..
REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_NAME = "uc2-provision.service"


class UpdateError(RuntimeError):
    pass


def _git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise UpdateError(
            f"git {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout.strip()


def is_git_checkout() -> bool:
    return (REPO_ROOT / ".git").exists()


def repo_status(fetch: bool = False) -> dict[str, Any]:
    """Current commit, branch and how far behind the remote we are."""
    info: dict[str, Any] = {
        "repo_root": str(REPO_ROOT),
        "is_git_checkout": is_git_checkout(),
        "update_supported": False,
    }
    if not info["is_git_checkout"]:
        info["error"] = (
            "Not a git checkout — reinstall with scripts/install.sh to enable "
            "in-place updates."
        )
        return info
    if shutil.which("git") is None:
        info["error"] = "git is not installed on this station."
        return info

    try:
        info["commit"] = _git("rev-parse", "--short", "HEAD")
        info["commit_full"] = _git("rev-parse", "HEAD")
        info["branch"] = _git("rev-parse", "--abbrev-ref", "HEAD")
        info["subject"] = _git("log", "-1", "--pretty=%s")
        info["committed_at"] = _git("log", "-1", "--pretty=%cI")
        info["dirty"] = bool(_git("status", "--porcelain"))
        info["remote_url"] = _git("remote", "get-url", "origin")
        info["update_supported"] = True

        if fetch:
            _git("fetch", "--quiet", "origin", info["branch"])
        upstream = f"origin/{info['branch']}"
        try:
            counts = _git("rev-list", "--left-right", "--count", f"HEAD...{upstream}")
            ahead, behind = (int(x) for x in counts.split())
            info["ahead"] = ahead
            info["behind"] = behind
            info["remote_commit"] = _git("rev-parse", "--short", upstream)
            info["remote_subject"] = _git("log", "-1", "--pretty=%s", upstream)
        except UpdateError:
            # No upstream tracking ref yet (e.g. fetch never ran offline).
            info["behind"] = None
    except UpdateError as exc:
        info["error"] = str(exc)
    return info


def update(job: Job, restart: bool = True, reboot: bool = False) -> None:
    """Fast-forward the checkout to origin and restart the station."""
    if not is_git_checkout():
        raise UpdateError(
            f"{REPO_ROOT} is not a git checkout — cannot self-update. "
            "Reinstall with scripts/install.sh."
        )

    job.set_progress(0.05, "Reading current version")
    before = _git("rev-parse", "--short", "HEAD")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    job.log_line(f"Current: {before} on {branch}")

    job.set_progress(0.15, "Fetching from origin")
    job.log_line(f"Fetching origin/{branch} ...")
    _git("fetch", "origin", branch)

    target = _git("rev-parse", "--short", f"origin/{branch}")
    if target == before:
        job.log_line("Already up to date — nothing to do.")
        job.set_progress(1.0, "Already up to date")
        job.meta["updated"] = False
        return

    job.log_line(f"Updating {before} → {target}")
    for line in _git(
        "log", "--oneline", "--no-decorate", f"HEAD..origin/{branch}"
    ).splitlines()[:20]:
        job.log_line(f"  {line}")

    job.set_progress(0.35, "Applying update")
    # Hard reset rather than merge: the station is an appliance, its checkout
    # should always be exactly what the branch says.
    if _git("status", "--porcelain"):
        job.log_line("Discarding local modifications on the station checkout.")
    _git("reset", "--hard", f"origin/{branch}")
    job.log_line(f"Now at {_git('rev-parse', '--short', 'HEAD')}")

    job.set_progress(0.6, "Updating Python dependencies")
    _install_backend(job)

    dist = REPO_ROOT / "frontend" / "dist" / "index.html"
    if dist.exists():
        job.log_line("Frontend bundle present (built by CI).")
    else:
        job.log_line(
            "WARNING: frontend/dist is missing from this commit — the UI may "
            "not load. Check that the build workflow committed it."
        )

    job.meta["updated"] = True
    job.meta["from"] = before
    job.meta["to"] = target

    if reboot:
        job.set_progress(0.95, "Rebooting")
        job.log_line("Rebooting the station ...")
        _schedule("reboot")
    elif restart:
        job.set_progress(0.95, "Restarting service")
        job.log_line("Restarting the station service ...")
        _schedule("restart")
    job.set_progress(1.0, "Update applied")


def _install_backend(job: Job) -> None:
    """Reinstall the backend package so new dependencies land."""
    import sys

    pip = Path(sys.executable).with_name("pip")
    if not pip.exists():
        job.log_line("pip not found next to the interpreter — skipping dependency update.")
        return
    result = subprocess.run(
        [str(pip), "install", "-q", "-e", str(REPO_ROOT / "backend")],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise UpdateError(f"pip install failed: {result.stderr.strip()[:500]}")

    # pip treats "same name+version already installed" as satisfied and skips
    # re-pointing an existing editable install, even to a different source
    # path — so the call above is a no-op if this venv was ever pointed at a
    # different checkout. Force the editable link back onto REPO_ROOT so a
    # stale pointer can't silently keep serving old code/frontend forever.
    result = subprocess.run(
        [str(pip), "install", "-q", "--force-reinstall", "--no-deps", "-e", str(REPO_ROOT / "backend")],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise UpdateError(f"pip install --force-reinstall failed: {result.stderr.strip()[:500]}")
    job.log_line("Python dependencies up to date.")


def _schedule(action: str) -> None:
    """Restart or reboot shortly after we return, so this request completes.

    `systemctl restart` on our own unit would kill us mid-response; sleeping
    in a detached child lets the HTTP response and job state flush first.
    """
    cmd = (
        ["systemctl", "reboot"]
        if action == "reboot"
        else ["systemctl", "restart", SERVICE_NAME]
    )
    subprocess.Popen(
        ["sh", "-c", f"sleep 2; exec {' '.join(cmd)}"],
        start_new_session=True,
    )
