"""Async service around :mod:`helixsr.installer`, mirroring optiscaler.service."""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from . import constants as C
from . import installer
from optiscaler import steam as steam_mod


class HelixService:
    def __init__(self, home, state_dir, logger):
        self.home = Path(home)
        self.state_dir = Path(state_dir)
        self.log = logger
        self._lock = asyncio.Lock()
        self._setup_task = None
        self._cancel_event = None
        self._setup_state = {"phase": "idle", "message": ""}

    @staticmethod
    async def _run(func, *args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    # -- status ------------------------------------------------------------

    async def status(self):
        ready = await self._run(installer.is_ready, self.state_dir)
        setting_up = self._setup_task is not None and not self._setup_task.done()
        return {
            "version": C.VERSION,
            "ready": ready,
            "setting_up": setting_up,
            "phase": self._setup_state["phase"],
            "message": self._setup_state["message"],
        }

    # -- setup -------------------------------------------------------------

    def _set_phase(self, phase, message=""):
        self._setup_state = {"phase": phase, "message": message}
        if self.log:
            self.log.info("HelixSR setup [%s] %s", phase, message)

    def _setup_job(self, cancel_event):
        self._set_phase("download", "Downloading HelixSR")
        try:
            runtime = installer.download_release(self.state_dir, cancel_event)
            self._set_phase("build", "Building the HelixSR network")
            installer.run_setup(runtime, self.home, cancel_event,
                                self.state_dir / "helixsr-setup.log", self.log)
            self._set_phase("done", "HelixSR ready")
        except Exception as exc:  # surfaced verbatim in the UI
            if str(exc) == "Setup cancelled":
                self._set_phase("cancelled", "Setup cancelled")
            else:
                if self.log:
                    self.log.exception("HelixSR setup failed")
                self._set_phase("error", str(exc))

    async def start_setup(self):
        async with self._lock:
            if self._setup_task is not None and not self._setup_task.done():
                return {"ok": False, "error": "Setup already running"}
            if await self._run(installer.is_ready, self.state_dir):
                return {"ok": True, "already_ready": True}
            self._cancel_event = threading.Event()
            self._setup_task = asyncio.get_running_loop().run_in_executor(
                None, self._setup_job, self._cancel_event)
            return {"ok": True}

    async def cancel_setup(self):
        if self._cancel_event is not None:
            self._cancel_event.set()
        return {"ok": True}

    async def setup_log(self):
        return {"ok": True,
                "log": await self._run(installer.setup_log_tail, self.state_dir)}

    # -- games -------------------------------------------------------------

    async def games(self):
        games = await self._run(installer.find_games, self.home)
        return {"ok": True, "games": games}

    async def install(self, ini_dir):
        try:
            async with self._lock:
                runtime = installer.runtime_dir(self.state_dir)
                src = runtime / C.NVNGX_DLL
                if not await self._run(installer.is_ready, self.state_dir):
                    return {"ok": False, "error": "Run the HelixSR setup first"}
                message = await self._run(installer.install, Path(ini_dir), src)
            return {"ok": True, "message": message}
        except Exception as exc:
            if self.log:
                self.log.exception("HelixSR install failed for %s", ini_dir)
            return {"ok": False, "error": str(exc)}

    async def uninstall(self, ini_dir):
        try:
            async with self._lock:
                message = await self._run(installer.uninstall, Path(ini_dir))
            return {"ok": True, "message": message}
        except Exception as exc:
            if self.log:
                self.log.exception("HelixSR uninstall failed for %s", ini_dir)
            return {"ok": False, "error": str(exc)}

    # -- launch options ----------------------------------------------------

    async def record_launch_options(self, ini_dir, options=None, appid=None):
        """Keep this game's launch options as they were before HelixSR.

        Mirrors optiscaler.service: the frontend's client read is freshest,
        Steam's config file is the fallback, and the record is write-once.
        """
        try:
            if options is None and appid is not None:
                found = await self._run(steam_mod.launch_options, self.home, appid)
                if not found["found"]:
                    return {"ok": False, "recorded": False, "value": "",
                            "written": False,
                            "error": "Steam would not report the launch options"}
                options = found["value"]
            if options is None:
                return {"ok": False, "recorded": False, "value": "",
                        "written": False, "error": "no launch options to record"}
            result = await self._run(
                installer.record_launch_options, Path(ini_dir), options)
            return {"ok": True, **result}
        except Exception as exc:
            if self.log:
                self.log.exception("could not record launch options for %s", ini_dir)
            return {"ok": False, "error": str(exc)}

    async def get_launch_record(self, ini_dir):
        return {"ok": True,
                **await self._run(installer.read_launch_record, Path(ini_dir))}

    async def forget_launch_options(self, ini_dir):
        forgotten = await self._run(installer.forget_launch_options, Path(ini_dir))
        return {"ok": True, "forgotten": forgotten}
