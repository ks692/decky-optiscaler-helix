import { ButtonItem, PanelSection, PanelSectionRow, showModal } from "@decky/ui";
import { toaster } from "@decky/api";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  helixCancelSetup,
  helixForgetLaunchOptions,
  helixGames,
  helixGetLaunchRecord,
  helixInstall,
  helixSetup,
  helixSetupLog,
  helixStatus,
  helixUninstall,
} from "../api";
import { setLaunchOptions } from "../hooks/useRunningGame";
import { currentLaunchOptions } from "../launchOptions";
import {
  HELIX_ENV,
  addHelixEnv,
  recordPreviousHelixLaunchOptions,
} from "../helixLaunch";
import type { LaunchAction } from "../launchOptions";
import { KeyValue, Mono, Notice, Pill } from "./Common";
import { HelixRemovePrompt } from "./HelixRemovePrompt";
import type { HelixGame, HelixStatus } from "../types";

function phaseLabel(phase: string): string {
  switch (phase) {
    case "download":
      return "Downloading";
    case "build":
      return "Building the network";
    case "done":
      return "Done";
    case "error":
      return "Failed";
    case "cancelled":
      return "Cancelled";
    default:
      return "Idle";
  }
}

const iniDirOf = (game: HelixGame): string => game.ini.replace(/\/OptiScaler\.ini$/, "");

export function HelixPanel() {
  const [status, setStatus] = useState<HelixStatus | null>(null);
  const [games, setGames] = useState<HelixGame[]>([]);
  const [log, setLog] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [st, gm] = await Promise.all([helixStatus(), helixGames()]);
      setStatus(st);
      if (gm.ok) setGames(gm.games);
    } catch {
      /* backend unreachable; the panel keeps its last state */
    }
  }, []);

  useEffect(() => {
    void refresh();
    timer.current = window.setInterval(refresh, 2000);
    return () => {
      if (timer.current !== null) window.clearInterval(timer.current);
    };
  }, [refresh]);

  const onSetup = async () => {
    setBusy(true);
    try {
      const result = await helixSetup();
      if (!result.ok) toaster.toast({ title: "Setup failed to start", body: String(result.error ?? "") });
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const onCancel = async () => {
    await helixCancelSetup();
    await refresh();
  };

  const onShowLog = async () => {
    try {
      const result = await helixSetupLog();
      setLog(result.log || "(no log yet)");
    } catch {
      setLog("(could not read the log)");
    }
  };

  const onInstall = async (game: HelixGame) => {
    setBusy(true);
    try {
      const result = await helixInstall(iniDirOf(game));
      if (!result.ok) {
        toaster.toast({ title: "Install failed", body: String(result.error ?? "") });
        return;
      }
      // Record what Steam had before us, then add the HelixSR entries in
      // front of it — anything already there (an lsfg-vk wrapper, the game's
      // own flags) keeps its place behind them.
      await recordPreviousHelixLaunchOptions(game.appid, iniDirOf(game));
      const current = await currentLaunchOptions(game.appid);
      const next = addHelixEnv(current);
      if (next !== (current ?? "").trim()) {
        if (setLaunchOptions(Number(game.appid), next)) {
          toaster.toast({ title: "HelixSR installed", body: "Launch options updated." });
        } else {
          toaster.toast({
            title: "HelixSR installed",
            body: `The launch options could not be written from here — add this yourself: ${HELIX_ENV} %command%`,
          });
        }
      } else {
        toaster.toast({ title: "HelixSR installed", body: String(result.message ?? "") });
      }
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const doUninstall = async (game: HelixGame, action: LaunchAction) => {
    setBusy(true);
    try {
      const result = await helixUninstall(iniDirOf(game));
      if (!result.ok) {
        toaster.toast({ title: "Remove failed", body: String(result.error ?? "") });
        return;
      }
      // Apply the launch-options answer, then drop the record: it belonged to
      // this install.
      await applyLaunchChoice(game, action);
      await helixForgetLaunchOptions(iniDirOf(game)).catch(() => null);
      toaster.toast({ title: "HelixSR removed", body: String(result.message ?? "") });
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const applyLaunchChoice = async (game: HelixGame, action: LaunchAction) => {
    if (action === "keep") return;
    try {
      const [record, current] = await Promise.all([
        helixGetLaunchRecord(iniDirOf(game)).catch(() => ({ recorded: false, value: "" })),
        currentLaunchOptions(game.appid).catch(() => null),
      ]);
      const { helixLaunchChoices } = await import("../helixLaunch");
      const choice = helixLaunchChoices({
        current,
        recorded: record.recorded ? record.value : null,
      }).find((c) => c.action === action);
      if (choice && choice.value !== null) {
        setLaunchOptions(Number(game.appid), choice.value);
      }
    } catch {
      /* launch options are a courtesy; the uninstall already succeeded */
    }
  };

  const onUninstall = async (game: HelixGame) => {
    const [record, current] = await Promise.all([
      helixGetLaunchRecord(iniDirOf(game)).catch(() => ({ recorded: false, value: "" })),
      currentLaunchOptions(game.appid).catch(() => null),
    ]);
    showModal(
      <HelixRemovePrompt
        gameName={game.name}
        launch={{ current, recorded: record.recorded ? record.value : null }}
        closeModal={() => undefined}
        onConfirm={(action) => doUninstall(game, action)}
      />,
    );
  };

  return (
    <div>
      <PanelSection title="HelixSR setup">
        <PanelSectionRow>
          <KeyValue
            label="Status"
            value={
              status ? (
                <>
                  <Pill color={status.ready ? "green" : status.setting_up ? "blue" : "gray"}>
                    {status.setting_up ? phaseLabel(status.phase) : status.ready ? "Ready" : "Not set up"}
                  </Pill>{" "}
                  <span>HelixSR {status.version}</span>
                </>
              ) : (
                "Loading…"
              )
            }
          />
        </PanelSectionRow>
        {status?.message && status.phase !== "idle" && (
          <PanelSectionRow>
            <Notice tone={status.phase === "error" ? "error" : "info"}>{status.message}</Notice>
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy || !status || status.ready || status.setting_up} onClick={onSetup}>
            {busy ? "Starting…" : "Set up HelixSR"}
          </ButtonItem>
        </PanelSectionRow>
        {status?.setting_up && (
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={onCancel}>
              Cancel setup
            </ButtonItem>
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onShowLog}>
            Show setup log
          </ButtonItem>
        </PanelSectionRow>
        {log && (
          <PanelSectionRow>
            <div style={{ maxHeight: 220, overflowY: "auto", width: "100%" }}>
              <Mono>{log}</Mono>
            </div>
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection title={`Games with OptiScaler (${games.length})`}>
        {games.length === 0 && (
          <PanelSectionRow>
            <Notice tone="info">
              No games with OptiScaler.ini found. Install OptiScaler for a game first, then HelixSR can be added.
            </Notice>
          </PanelSectionRow>
        )}
        {games.map((game) => (
          <PanelSectionRow key={game.ini}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, width: "100%" }}>
              <div style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {game.name}
                {game.helix_installed && <Pill color="green"> HelixSR</Pill>}
              </div>
              <ButtonItem
                layout="inline"
                disabled={busy || !status?.ready}
                onClick={() => (game.helix_installed ? onUninstall(game) : onInstall(game))}
              >
                {game.helix_installed ? "Remove" : "Install"}
              </ButtonItem>
            </div>
          </PanelSectionRow>
        ))}
      </PanelSection>

      <PanelSection title="Launch options">
        <PanelSectionRow>
          <Notice tone="info">
            Installing HelixSR adds <Mono>{HELIX_ENV}</Mono> to the game's Steam launch options automatically, in
            front of anything already there. Removing it asks what to do with the field: put back what was there
            before, take out only the HelixSR entries, or leave it alone.
          </Notice>
        </PanelSectionRow>
        <PanelSectionRow>
          <Notice tone="info">
            HelixSR handles upscaling only. If you pair it with lsfg-vk for frame generation, keep your existing
            launch options — the install preserves them. Do not stack two frame generators at once.
          </Notice>
        </PanelSectionRow>
      </PanelSection>
    </div>
  );
}
