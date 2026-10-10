/**
 * The Steam launch options a HelixSR install writes, and how to take them back out.
 *
 * Same shape as this repo's launchOptions.ts, but for the HelixSR half: the
 * install adds `PROTON_FORCE_NVAPI=1 DXVK_NVAPI_GPU_ARCH=AD100` in front of
 * whatever the game already had (an lsfg-vk setup, for example, is left
 * alone). Removing offers the same three honest answers — put back what was
 * there, take out only what HelixSR added, or leave the field untouched —
 * decided from what was recorded at install time.
 */
import { helixRecordLaunchOptions } from "./api";
import { currentLaunchOptions } from "./launchOptions";
import type { LaunchAction, LaunchChoice } from "./launchOptions";

/** The environment entries a HelixSR install adds to the launch options. */
export const HELIX_ENV = "PROTON_FORCE_NVAPI=1 DXVK_NVAPI_GPU_ARCH=AD100";

const HELIX_TOKENS = ["PROTON_FORCE_NVAPI=1", "DXVK_NVAPI_GPU_ARCH=AD100"];

export function helixLaunchOption(): string {
  return `${HELIX_ENV} %command%`;
}

export function hasHelixEnv(options: string | null): boolean {
  if (!options) return false;
  const lower = options.toLowerCase();
  return HELIX_TOKENS.every((token) => lower.includes(token.toLowerCase()));
}

/**
 * The launch options with the HelixSR entries in front, added once.
 *
 * Anything already there — the game's own flags, an lsfg-vk wrapper — keeps
 * its place behind them, because none of it is this plugin's to reorder.
 */
export function addHelixEnv(options: string | null): string {
  const current = (options ?? "").trim();
  if (hasHelixEnv(current)) return current;
  if (!current || current === "%command%") return helixLaunchOption();
  return `${HELIX_ENV} ${current}`;
}

/**
 * The same launch options with the HelixSR entries taken out and nothing else.
 *
 * A leftover bare `%command%` is Steam's own default written out longhand, so
 * that collapses to an empty field.
 */
export function stripHelixEnv(options: string): string {
  let out = options;
  for (const token of HELIX_TOKENS) {
    out = out.replace(new RegExp(`\\s*${token.replace(/=/g, "\\=")}\\s*`, "gi"), " ");
  }
  const collapsed = out.replace(/\s+/g, " ").trim();
  return collapsed === "%command%" ? "" : collapsed;
}

export interface HelixLaunchState {
  /** Steam's current launch options, or null when the client will not say. */
  current: string | null;
  /** What was there before the install, or null when nothing was recorded. */
  recorded: string | null;
}

/**
 * What the user can be offered when HelixSR is removed, best answer first.
 *
 * "Put back what was there before" is only offered when there was something.
 * Taking out only the HelixSR entries is offered whenever the result is
 * known. When neither is true, nothing here is known to be ours, and leaving
 * the field alone is the only honest default.
 */
export function helixLaunchChoices(state: HelixLaunchState): LaunchChoice[] {
  const { current, recorded } = state;
  const restore: LaunchChoice[] =
    recorded !== null && recorded.trim() !== "" && recorded !== current
      ? [
          {
            action: "restore",
            label: "Put back what was there before",
            description: recorded,
            value: recorded,
          },
        ]
      : [];

  const keep: LaunchChoice = {
    action: "keep",
    label: "Leave them as they are",
    description: current
      ? `Steam keeps passing: ${current}`
      : "Nothing in Steam is changed.",
    value: null,
  };

  const known =
    recorded === ""
      ? ""
      : current !== null && hasHelixEnv(current)
        ? stripHelixEnv(current)
        : null;

  if (known === null) return [...restore, keep];

  const cleared = known;
  const clear: LaunchChoice = {
    action: "clear",
    label:
      cleared === ""
        ? "Clear the launch options"
        : "Remove only the HelixSR entries",
    description:
      cleared === ""
        ? recorded === ""
          ? "This game had none before HelixSR was installed."
          : "Leaves the launch options empty."
        : `Leaves: ${cleared}`,
    value: cleared,
  };

  const duplicate =
    cleared === current || restore.some((choice) => choice.value === cleared);
  if (duplicate) return [...restore, keep];
  return [...restore, clear, keep];
}

export function resolveHelixChoice(
  choices: LaunchChoice[],
  remembered: LaunchAction | null,
): LaunchChoice | undefined {
  const match = remembered && choices.find((choice) => choice.action === remembered);
  return match || choices[0];
}

/**
 * Keep this game's launch options as they were, before HelixSR's entries go in.
 *
 * Called after a successful install and before the entries are set, which is
 * the only moment Steam still holds the answer. Write-once in the backend, so
 * a reinstall cannot overwrite the original with our own entries.
 */
export async function recordPreviousHelixLaunchOptions(
  appid: string | null,
  iniDir: string,
): Promise<void> {
  if (!appid) return;
  const current = await currentLaunchOptions(appid);
  try {
    await helixRecordLaunchOptions(iniDir, current, appid);
  } catch {
    /* the record is a convenience; failing to write it must not fail an install */
  }
}
