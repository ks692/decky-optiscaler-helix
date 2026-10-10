"""HelixSR install machinery: pinned download, setup, per-game transactions.

Game discovery reuses :mod:`optiscaler.steam`; ini edits reuse the
line-preserving :class:`optiscaler.inifile.IniFile`, so comments and unknown
keys in the user's OptiScaler.ini survive.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import ssl
import stat
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from optiscaler import steam as steam_mod
from optiscaler.inifile import IniFile

from . import constants as C


class HelixError(Exception):
    pass


# -- small file helpers ----------------------------------------------------

def _sha256(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise HelixError(f"Refusing symbolic link: {path}")
    fd, tmp = tempfile.mkstemp(prefix=".helix-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def _safe_extract(data: bytes, destination: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(i.file_size for i in archive.infolist()) > 128 * 1024 * 1024:
            raise HelixError("Archive expands beyond the allowed size")
        seen = set()
        for info in archive.infolist():
            p = PurePosixPath(info.filename)
            if "\\" in info.filename or p.is_absolute() or ".." in p.parts or not p.parts:
                raise HelixError("Unsafe archive path")
            if stat.S_ISLNK(info.external_attr >> 16) or info.filename in seen:
                raise HelixError("Archive contains a link or duplicate")
            seen.add(info.filename)
        archive.extractall(destination)


def windows_path(linux_path: Path) -> str:
    """Proton-style path for NvngxPath: Z:\\home\\deck\\... ."""
    return "Z:" + str(linux_path).replace("/", "\\")


# -- setup -----------------------------------------------------------------

def runtime_dir(state_dir: Path) -> Path:
    return Path(state_dir) / "runtime" / C.ARCHIVE_ROOT


def download_release(state_dir: Path, cancelled: threading.Event) -> Path:
    """Download and verify the pinned HelixSR release; return its directory."""
    data = _fetch(C.RELEASE_URL, cancelled)
    if hashlib.sha256(data).hexdigest() != C.RELEASE_SHA256:
        raise HelixError("Release checksum mismatch; nothing was extracted")
    if cancelled.is_set():
        raise HelixError("Setup cancelled")
    runtime = runtime_dir(state_dir)
    with tempfile.TemporaryDirectory(prefix="helix-download-", dir=state_dir) as temp:
        _safe_extract(data, Path(temp))
        source = Path(temp) / C.ARCHIVE_ROOT
        if not (source / C.SETUP_SCRIPT).is_file():
            raise HelixError("Unexpected release layout")
        # Upstream's zip carries the exec bit on launch_synth, but extraction
        # does not always preserve it (seen on Deck: PermissionError). The
        # setup executes these directly, so make it explicit.
        for exe in (source / "setup" / "lib" / "model" / "launch_synth",
                    source / C.SETUP_SCRIPT):
            if exe.is_file():
                exe.chmod(exe.stat().st_mode | 0o111)
        runtime.parent.mkdir(parents=True, exist_ok=True)
        if runtime.exists():
            shutil.rmtree(runtime)
        shutil.move(str(source), runtime)
    return runtime


def _candidate_contexts():
    """SSL contexts to try, most trustworthy first.

    Mirrors optiscaler.wiki: SteamOS images do not always expose a CA bundle
    where Python looks for one, and the plugin runs with a trimmed
    environment, so the default context can fail with
    CERTIFICATE_VERIFY_FAILED even though the network is fine. The download
    is SHA-256-pinned afterwards, so even the unverified fallback cannot be
    fed a tampered release.
    """
    try:
        yield "default", ssl.create_default_context()
    except Exception:
        pass
    try:
        import certifi
    except ImportError:
        pass
    else:
        try:
            yield "certifi", ssl.create_default_context(cafile=certifi.where())
        except Exception:
            pass
    for bundle in ("/etc/ssl/certs/ca-certificates.crt",   # SteamOS / Arch
                   "/etc/pki/tls/certs/ca-bundle.crt",     # Fedora / RHEL
                   "/etc/ssl/ca-bundle.pem",               # openSUSE
                   "/etc/ssl/cert.pem"):                   # macOS / BSD
        if Path(bundle).is_file():
            try:
                yield f"system:{bundle}", ssl.create_default_context(cafile=bundle)
            except Exception:
                continue
    try:
        yield "unverified", ssl._create_unverified_context()
    except Exception:
        return


def _is_tls_error(exc):
    """True when a request failed at the TLS layer rather than the network.

    urllib raises URLError with the SSLError as its .reason, so the SSLError
    never surfaces directly.
    """
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, ssl.SSLError):
            return True
        exc = (getattr(exc, "reason", None)
               if isinstance(exc, urllib.error.URLError) else None)
    return False


def _fetch(url: str, cancelled: threading.Event) -> bytes:
    """Fetch url, walking the TLS fallback chain on certificate errors."""
    req = urllib.request.Request(url, headers={"User-Agent": "decky-optiscaler-helix/0.0.1"})
    last_exc = None
    for _kind, context in _candidate_contexts():
        try:
            chunks, size = [], 0
            with urllib.request.urlopen(req, timeout=30, context=context) as response:
                while True:
                    if cancelled.is_set():
                        raise HelixError("Setup cancelled")
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > C.MAX_DOWNLOAD_BYTES:
                        raise HelixError("Release exceeds maximum size")
                    chunks.append(chunk)
            return b"".join(chunks)
        except Exception as exc:
            if isinstance(exc, HelixError):
                raise
            last_exc = exc
            if not _is_tls_error(exc):
                raise
    raise HelixError(
        f"Could not download the release ({last_exc}). Check the Deck's network "
        "connection and date/time, then retry.")


def run_setup(runtime: Path, home: Path, cancelled: threading.Event,
              log_path: Path, logger=None) -> None:
    """Run the upstream setup script; raises HelixError on failure/cancel."""
    script = runtime / C.SETUP_SCRIPT
    if not script.is_file():
        raise HelixError("Setup script missing from the release")
    env = dict(os.environ,
               HOME=str(home),
               XDG_DATA_HOME=str(runtime.parent / "dependencies"),
               HELIXSR_FORCE_PORTABLE="1",
               PYTHONUNBUFFERED="1")
    env.pop("LD_LIBRARY_PATH", None)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as log:
        proc = subprocess.Popen(
            ["bash", str(script), "--yes"],
            cwd=runtime, env=env,
            stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True)
    try:
        while proc.poll() is None:
            if cancelled.is_set():
                try:
                    os.killpg(proc.pid, 15)
                except ProcessLookupError:
                    pass
                raise HelixError("Setup cancelled")
            cancelled.wait(0.5)
    finally:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, 9)
            except ProcessLookupError:
                pass
            proc.wait()
    if cancelled.is_set():
        raise HelixError("Setup cancelled")
    if proc.returncode != 0:
        raise HelixError(
            f"Setup exited with code {proc.returncode}. See the setup log, then retry.")
    marker = runtime / C.READY_MARKER
    _atomic_write(marker, json.dumps({"version": C.VERSION}).encode())


def is_ready(state_dir: Path) -> bool:
    runtime = runtime_dir(state_dir)
    marker = runtime / C.READY_MARKER
    dll = runtime / C.NVNGX_DLL
    if not marker.is_file() or not dll.is_file():
        return False
    try:
        if json.loads(marker.read_text()).get("version") != C.VERSION:
            return False
    except (OSError, ValueError):
        return False
    try:
        return dll.stat().st_size >= C.MIN_READY_BYTES
    except OSError:
        return False


def setup_log_tail(state_dir: Path, lines: int = 120) -> str:
    path = Path(state_dir) / "helixsr-setup.log"
    if not path.is_file():
        return ""
    text = path.read_text(errors="replace")
    return "\n".join(text.splitlines()[-lines:])


# -- game discovery --------------------------------------------------------

def _find_optiscaler_ini(game_path: Path, max_depth: int = 5) -> Path | None:
    base = str(game_path).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(game_path, followlinks=False):
        if dirpath.count(os.sep) - base > max_depth:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames
                       if not os.path.islink(os.path.join(dirpath, d))]
        if C.OPTISCALER_INI in filenames:
            candidate = Path(dirpath) / C.OPTISCALER_INI
            if candidate.is_file() and not candidate.is_symlink():
                return candidate
    return None


def find_games(home: Path) -> list[dict]:
    """Steam games with an OptiScaler.ini; each is a HelixSR candidate."""
    games = []
    seen = set()
    for library in steam_mod.library_folders(Path(home)):
        for game in steam_mod.steam_games(library):
            root = Path(game["path"])
            if root in seen:
                continue
            seen.add(root)
            ini = _find_optiscaler_ini(root)
            if ini is None:
                continue
            games.append({
                "appid": game["appid"],
                "name": game["name"],
                "path": str(root),
                "ini": str(ini),
                "helix_installed": (ini.parent / C.HELIX_DIRNAME / C.NVNGX_DLL).is_file(),
            })
    return sorted(games, key=lambda g: g["name"].lower())


# -- per-game install ------------------------------------------------------

def _journal_path(ini_dir: Path) -> Path:
    return ini_dir / C.HELIX_DIRNAME / C.JOURNAL_NAME


def _helix_dll_path(ini_dir: Path) -> Path:
    return ini_dir / C.HELIX_DIRNAME / C.NVNGX_DLL


def _resolve_ini_dir(target_dir: Path) -> Path:
    """The directory holding OptiScaler.ini for a game target.

    Usually the target dir itself; falls back to a shallow search for games
    whose ini landed in a subfolder.
    """
    target_dir = Path(target_dir)
    if (target_dir / C.OPTISCALER_INI).is_file():
        return target_dir
    found = _find_optiscaler_ini(target_dir, max_depth=3)
    if found is not None:
        return found.parent
    raise HelixError("OptiScaler.ini not found; install OptiScaler first")


def game_status(target_dir: Path, state_dir: Path) -> dict:
    """Whether HelixSR is installed for this game target and setup is ready."""
    try:
        ini_dir = _resolve_ini_dir(Path(target_dir))
    except HelixError:
        return {"installed": False, "ready": is_ready(state_dir), "ini_dir": None}
    dll = ini_dir / C.HELIX_DIRNAME / C.NVNGX_DLL
    return {"installed": dll.is_file(), "ready": is_ready(state_dir),
            "ini_dir": str(ini_dir)}


def install(ini_dir: Path, nvngx_src: Path) -> str:
    """Deploy HelixSR for one game; journal ini changes for uninstall.

    Idempotent: reinstalling first removes the previous HelixSR cleanly
    (restoring the ini from its journal), so the journal always keeps the
    true original values and nothing of OptiScaler's is ever touched.
    """
    ini_dir = _resolve_ini_dir(Path(ini_dir))
    ini_path = ini_dir / C.OPTISCALER_INI
    helix_dir = ini_dir / C.HELIX_DIRNAME
    dll_path = _helix_dll_path(ini_dir)
    if dll_path.is_file():
        try:
            uninstall(ini_dir)
        except HelixError:
            shutil.rmtree(helix_dir, ignore_errors=True)

    ini = IniFile(ini_path)
    previous = {
        C.INI_DX12_KEY: ini.get(C.INI_DX12_SECTION, C.INI_DX12_KEY),
        C.INI_LIB_KEY: ini.get(C.INI_LIB_SECTION, C.INI_LIB_KEY),
    }
    _atomic_write(_journal_path(ini_dir),
                  json.dumps({"ini": str(ini_path), "previous": previous},
                             indent=2).encode())

    helix_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(nvngx_src, dll_path)

    ini.set(C.INI_DX12_SECTION, C.INI_DX12_KEY, C.INI_DX12_VALUE)
    ini.set(C.INI_LIB_SECTION, C.INI_LIB_KEY, windows_path(dll_path))
    ini.save()
    return ("HelixSR installed. Set the launch option, then select "
            "DLSS in-game.")


def uninstall(ini_dir: Path) -> str:
    """Remove HelixSR and restore the journaled ini values."""
    ini_dir = Path(ini_dir)
    journal = _journal_path(ini_dir)
    if not journal.is_file():
        # Tolerate manual installs: still drop our files, leave the ini alone.
        shutil.rmtree(ini_dir / C.HELIX_DIRNAME, ignore_errors=True)
        return "HelixSR files removed."
    try:
        record = json.loads(journal.read_text())
    except (OSError, ValueError) as exc:
        raise HelixError(f"Install journal unreadable: {exc}")
    ini_path = Path(record["ini"])
    if ini_path.is_file():
        ini = IniFile(ini_path)
        previous = record.get("previous", {})
        if previous.get(C.INI_DX12_KEY) is not None:
            ini.set(C.INI_DX12_SECTION, C.INI_DX12_KEY, previous[C.INI_DX12_KEY])
        if previous.get(C.INI_LIB_KEY) is not None:
            ini.set(C.INI_LIB_SECTION, C.INI_LIB_KEY, previous[C.INI_LIB_KEY])
        ini.save()
    shutil.rmtree(ini_dir / C.HELIX_DIRNAME, ignore_errors=True)
    return "HelixSR removed; OptiScaler.ini restored."


# -- launch-option record --------------------------------------------------
#
# Kept in its own file (not OptiScaler's record): both mods can be installed
# for the same game, and "what was there before HelixSR" is a different
# answer from "what was there before OptiScaler". Write-once, like theirs.

def _launch_record_path(ini_dir: Path) -> Path:
    return Path(ini_dir) / C.HELIX_DIRNAME / C.LAUNCH_RECORD_NAME


def read_launch_record(ini_dir: Path) -> dict:
    path = _launch_record_path(ini_dir)
    if not path.is_file():
        return {"recorded": False, "value": ""}
    try:
        return {"recorded": True, "value": path.read_text(encoding="utf-8")}
    except OSError:
        return {"recorded": False, "value": ""}


def record_launch_options(ini_dir: Path, options: str) -> dict:
    path = _launch_record_path(ini_dir)
    if path.exists():
        return {"recorded": True, "value": read_launch_record(ini_dir)["value"],
                "written": False}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(options or "", encoding="utf-8")
    return {"recorded": True, "value": options or "", "written": True}


def forget_launch_options(ini_dir: Path) -> bool:
    path = _launch_record_path(ini_dir)
    existed = path.is_file()
    path.unlink(missing_ok=True)
    return existed
