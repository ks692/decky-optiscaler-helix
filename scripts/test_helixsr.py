#!/usr/bin/env python3
"""HelixSR backend tests against a synthetic Steam library in a temp dir.

Exercises game discovery (OptiScaler.ini detection), the per-game
install/uninstall transaction, comment-preserving ini edits with journaled
restore, and the HelixService RPC layer with a faked ready state.
"""
import asyncio
import json
import logging
import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "py_modules"))

from helixsr import constants as C  # noqa: E402
from helixsr import installer  # noqa: E402
from helixsr.service import HelixService  # noqa: E402

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    mark = "ok  " if condition else "FAIL"
    print(f"  [{mark}] {name}{(' — ' + str(detail)) if detail else ''}")


def build_fixture(root):
    home = root / "home"
    steam = home / ".local" / "share" / "Steam"
    (steam / "steamapps" / "common").mkdir(parents=True)
    (home / ".steam").mkdir(parents=True, exist_ok=True)
    os.symlink(steam, home / ".steam" / "steam")
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n' % steam
    )
    (steam / "steamapps" / "appmanifest_1091500.acf").write_text(
        '"AppState"\n{\n\t"appid"\t\t"1091500"\n\t"name"\t\t"Cyberpunk 2077"\n'
        '\t"installdir"\t\t"Cyberpunk 2077"\n\t"SizeOnDisk"\t\t"73819938816"\n}\n'
    )
    game = steam / "steamapps" / "common" / "Cyberpunk 2077"
    bindir = game / "bin" / "x64"
    bindir.mkdir(parents=True)
    (bindir / "OptiScaler.ini").write_text(
        "; user comment to preserve\n[Upscalers]\nDx12Upscaler=auto\n"
        "\n[Libraries]\nNvngxPath=auto\n"
    )
    return home, bindir


def fake_ready(state_dir, with_network=True):
    runtime = installer.runtime_dir(state_dir)
    runtime.mkdir(parents=True, exist_ok=True)
    dll = runtime / C.NVNGX_DLL
    if with_network:
        dll.write_bytes(b"\x00HelixSR 1.5.1\x00" + b"0" * 100 + b"\x00" * 24 + C.NETWORK_FOOTER + b"\x00" * 24)
    else:
        dll.write_bytes(b"0" * 1024)
        for name in C.NETWORK_FILES:
            (runtime / name).write_bytes(b"1" * 64)
    (runtime / C.READY_MARKER).write_text(json.dumps({"version": C.VERSION}))


def dll_bytes(version="1.5.1", with_network=True):
    head = b"\x00HelixSR " + version.encode() + b"\x00"
    if with_network:
        return head + b"0" * 100 + b"\x00" * 24 + C.NETWORK_FOOTER + b"\x00" * 24
    return head + b"0" * 100


async def main():
    logging.basicConfig(level=logging.CRITICAL)
    logger = logging.getLogger("test")
    with tempfile.TemporaryDirectory(prefix="helix-test-") as tmp:
        root = Path(tmp)
        home, bindir = build_fixture(root)
        state = root / "state"
        service = HelixService(home=home, state_dir=state, logger=logger)

        # discovery
        result = await service.games()
        check("finds the game with OptiScaler.ini",
              result["ok"] and len(result["games"]) == 1, result)
        game = result["games"][0]
        check("reports not installed initially", not game["helix_installed"])

        # status before setup
        status = await service.status()
        check("status reports not ready before setup",
              status["version"] == C.VERSION and not status["ready"])
        check("pinned by default", status["use_latest"] is False)

        # version choice round-trips and resolves to the pinned release
        set_res = await service.set_use_latest(False)
        check("set_use_latest(false) sticks",
              set_res["ok"] and set_res["use_latest"] is False)
        rel = installer.resolve_release(state, threading.Event())
        check("pinned resolution is verified",
              rel["version"] == C.VERSION and rel["verified"]
              and rel["sha256"] == C.RELEASE_SHA256)
        check("set_use_latest(true) sticks",
              (await service.set_use_latest(True))["use_latest"] is True)
        check("status reflects the choice",
              (await service.status())["use_latest"] is True)
        await service.set_use_latest(False)

        # install refused before setup
        denied = await service.install(str(bindir))
        check("install refused until setup ran",
              not denied["ok"] and "setup" in denied["error"].lower())

        # fake a completed setup, then install
        fake_ready(state)
        check("ready after marker written", (await service.status())["ready"])
        check("installed version reported",
              (await service.status())["version"] == C.VERSION)
        check("network footer detected",
              installer.has_network(installer.runtime_dir(state) / C.NVNGX_DLL))
        check("dll version parsed",
              installer.dll_version(installer.runtime_dir(state) / C.NVNGX_DLL) == "1.5.1")
        installed = await service.install(str(bindir))
        check("install succeeds", installed["ok"], installed)
        ini_text = (bindir / "OptiScaler.ini").read_text()
        check("Dx12Upscaler set to dlss", "Dx12Upscaler=dlss" in ini_text)
        check("NvngxPath set to a windows path",
              "NvngxPath=Z:" in ini_text and ini_text.count("\\") > 2)
        check("user comment preserved", "; user comment to preserve" in ini_text)
        check("nvngx.dll deployed", (bindir / "HelixSR" / "nvngx.dll").is_file())
        check("journal written", (bindir / "HelixSR" / C.JOURNAL_NAME).is_file())
        again = await service.games()
        check("reports installed after install", again["games"][0]["helix_installed"])
        duplicate = await service.install(str(bindir))
        check("reinstall succeeds", duplicate["ok"])
        ini_text2 = (bindir / "OptiScaler.ini").read_text()
        check("reinstall keeps dlss settings", "Dx12Upscaler=dlss" in ini_text2)
        journal = json.loads((bindir / "HelixSR" / C.JOURNAL_NAME).read_text())
        check("journal still holds the true originals",
              journal["previous"].get(C.INI_DX12_KEY) == "auto")
        check("journal records the dll version",
              journal.get("helixsr_version") == "1.5.1", journal)
        gs = await service.game_status(str(bindir))
        check("game status reports the installed version",
              gs["ok"] and gs["helixsr_version"] == "1.5.1", gs)

        # uninstall restores
        removed = await service.uninstall(str(bindir))
        check("uninstall succeeds", removed["ok"], removed)
        restored = (bindir / "OptiScaler.ini").read_text()
        check("Dx12Upscaler restored", "Dx12Upscaler=auto" in restored)
        check("NvngxPath restored", "NvngxPath=auto" in restored)
        check("HelixSR folder gone", not (bindir / "HelixSR").exists())

        # separate-files setup mode: dll without the network, sidecars beside it
        state2 = root / "state2"
        fake_ready(state2, with_network=False)
        check("ready via separate network files",
              installer.is_ready(state2))
        check("dll without footer is not network-carrying",
              not installer.has_network(installer.runtime_dir(state2) / C.NVNGX_DLL))
        service2 = HelixService(home=home, state_dir=state2, logger=logger)
        installed2 = await service2.install(str(bindir))
        check("install succeeds in separate-files mode", installed2["ok"])
        check("sidecars deployed next to the dll",
              all((bindir / "HelixSR" / n).is_file() for n in C.NETWORK_FILES))
        await service2.uninstall(str(bindir))
        check("sidecars removed with uninstall",
              not (bindir / "HelixSR").exists())

        # launch-option record
        rec0 = await service.get_launch_record(str(bindir))
        check("no launch record initially",
              rec0["ok"] and not rec0["recorded"])
        r1 = await service.record_launch_options(
            str(bindir), "MANGOHUD=1 %command%", appid="1091500")
        check("record writes once", r1["ok"] and r1["written"])
        r2 = await service.record_launch_options(str(bindir), "OTHER=1 %command%")
        check("second record does not overwrite",
              r2["ok"] and not r2["written"] and r2["value"] == "MANGOHUD=1 %command%")
        rec1 = await service.get_launch_record(str(bindir))
        check("record reads back",
              rec1["recorded"] and rec1["value"] == "MANGOHUD=1 %command%")
        forgotten = await service.forget_launch_options(str(bindir))
        check("forget drops the record", forgotten["ok"] and forgotten["forgotten"])
        rec2 = await service.get_launch_record(str(bindir))
        check("record gone after forget", not rec2["recorded"])

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("  FAILED:", FAILED)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
