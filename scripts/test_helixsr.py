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


def fake_ready(state_dir):
    runtime = installer.runtime_dir(state_dir)
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / C.NVNGX_DLL).write_bytes(b"0" * (C.MIN_READY_BYTES + 1))
    (runtime / C.READY_MARKER).write_text(json.dumps({"version": C.VERSION}))


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

        # install refused before setup
        denied = await service.install(str(bindir))
        check("install refused until setup ran",
              not denied["ok"] and "setup" in denied["error"].lower())

        # fake a completed setup, then install
        fake_ready(state)
        check("ready after marker written", (await service.status())["ready"])
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
        check("second install refused", not duplicate["ok"])

        # uninstall restores
        removed = await service.uninstall(str(bindir))
        check("uninstall succeeds", removed["ok"], removed)
        restored = (bindir / "OptiScaler.ini").read_text()
        check("Dx12Upscaler restored", "Dx12Upscaler=auto" in restored)
        check("NvngxPath restored", "NvngxPath=auto" in restored)
        check("HelixSR folder gone", not (bindir / "HelixSR").exists())

        # commands
        commands = await service.commands()
        check("launch option present",
              commands["ok"] and "%command%" in commands["launch_option"])
        check("lsfg variant present", "%command%" in commands["launch_option_lsfg"])

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("  FAILED:", FAILED)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
