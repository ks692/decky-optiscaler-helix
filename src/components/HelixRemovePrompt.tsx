import { ConfirmModal, DropdownItem } from "@decky/ui";
import { useState } from "react";
import { helixLaunchChoices, resolveHelixChoice } from "../helixLaunch";
import type { HelixLaunchState } from "../helixLaunch";
import type { LaunchAction } from "../launchOptions";
import { Notice } from "./Common";

/**
 * The launch-options question a HelixSR removal asks, in the same shape as
 * this repo's RemovePrompt: the install added `PROTON_FORCE_NVAPI=1
 * DXVK_NVAPI_GPU_ARCH=AD100` to Steam, and taking it back out is a decision
 * rather than a side effect — put back what was there, remove only the
 * HelixSR entries, or leave the field alone.
 */
export function HelixRemovePrompt({
  gameName,
  launch,
  closeModal,
  onConfirm,
}: Readonly<{
  gameName: string;
  /** Null when this game has no launch options to decide about at all. */
  launch: HelixLaunchState | null;
  closeModal?: () => void;
  onConfirm: (action: LaunchAction) => void;
}>) {
  const choices = launch ? helixLaunchChoices(launch) : [];
  const asked = choices.filter((choice) => choice.action !== "keep").length > 0;
  const initial = resolveHelixChoice(choices, null);
  const [action, setAction] = useState<LaunchAction>(initial?.action ?? "keep");
  const chosen = choices.find((choice) => choice.action === action) ?? initial;

  return (
    <ConfirmModal
      strTitle="Remove DLSS 3.7?"
      strOKButtonText="Remove"
      strCancelButtonText="Keep it"
      closeModal={closeModal}
      onOK={() => onConfirm(action)}
    >
      <div style={{ fontSize: "14px", lineHeight: 1.5 }}>
        {`Its nvngx.dll and the two OptiScaler.ini settings are removed from ${gameName}.`}
      </div>

      {asked ? (
        <DropdownItem
          label="Steam launch options"
          description={chosen?.description}
          rgOptions={choices.map((choice) => ({ data: choice.action, label: choice.label }))}
          selectedOption={action}
          bottomSeparator="none"
          onChange={(option: { data: LaunchAction }) => setAction(option.data)}
        />
      ) : (
        <div style={{ fontSize: "13px", opacity: 0.7, marginTop: "6px" }}>
          Steam has no launch options for this game to put back.
        </div>
      )}

      {asked && chosen?.action === "restore" ? (
        <Notice tone="info">
          The launch options the game had before DLSS 3.7 are put back verbatim.
        </Notice>
      ) : null}
    </ConfirmModal>
  );
}
