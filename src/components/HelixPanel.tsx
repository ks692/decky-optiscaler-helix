import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";
import { toaster } from "@decky/api";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  helixCancelSetup,
  helixCommands,
  helixGames,
  helixInstall,
  helixSetup,
  helixSetupLog,
  helixStatus,
  helixUninstall,
} from "../api";
import { KeyValue, Mono, Notice, Pill } from "./Common";
import type { HelixCommands, HelixGame, HelixStatus } from "../types";

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

async function copyText(text: string, what: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    toaster.toast({ title: "Copied", body: `${what} copied to the clipboard.` });
  } catch {
    toaster.toast({ title: "Copy failed", body: "Select the text and copy it manually." });
  }
}

export function HelixPanel() {
  const [status, setStatus] = useState<HelixStatus | null>(null);
  const [games, setGames] = useState<HelixGame[]>([]);
  const [commands, setCommands] = useState<HelixCommands | null>(null);
  const [log, setLog] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [st, gm, cmd] = await Promise.all([helixStatus(), helixGames(), helixCommands()]);
      setStatus(st);
      if (gm.ok) setGames(gm.games);
      if (cmd.ok) setCommands(cmd);
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
      const result = await helixInstall(game.ini.replace(/\/OptiScaler\.ini$/, ""));
      if (result.ok) {
        toaster.toast({ title: "HelixSR installed", body: String(result.message ?? "") });
      } else {
        toaster.toast({ title: "Install failed", body: String(result.error ?? "") });
      }
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const onUninstall = async (game: HelixGame) => {
    setBusy(true);
    try {
      const result = await helixUninstall(game.ini.replace(/\/OptiScaler\.ini$/, ""));
      if (result.ok) {
        toaster.toast({ title: "HelixSR removed", body: String(result.message ?? "") });
      } else {
        toaster.toast({ title: "Remove failed", body: String(result.error ?? "") });
      }
      await refresh();
    } finally {
      setBusy(false);
    }
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

      <PanelSection title="Launch commands">
        <PanelSectionRow>
          <Notice tone="info">
            Paste one of these into the game's Steam launch options. Set up each game once — the game stays managed
            afterwards.
          </Notice>
        </PanelSectionRow>
        {commands && (
          <>
            <PanelSectionRow>
              <KeyValue label="HelixSR" value={<Mono>{commands.launch_option}</Mono>} />
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => copyText(commands.launch_option, "HelixSR launch option")}>
                Copy HelixSR command
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <KeyValue label="HelixSR + lsfg-vk" value={<Mono>{commands.launch_option_lsfg}</Mono>} />
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                onClick={() => copyText(commands.launch_option_lsfg, "HelixSR + lsfg-vk launch option")}
              >
                Copy HelixSR + lsfg-vk command
              </ButtonItem>
            </PanelSectionRow>
            {commands.notes.map((note) => (
              <PanelSectionRow key={note}>
                <Notice tone="info">{note}</Notice>
              </PanelSectionRow>
            ))}
          </>
        )}
      </PanelSection>
    </div>
  );
}
