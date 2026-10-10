import { DialogButton, Focusable } from "@decky/ui";
import { useEffect, useState } from "react";
import { helixSetupLog } from "../api";

/** Live view of helixsr-setup.log; refreshes while open. */
export function HelixSetupLogModal({ closeModal }: Readonly<{ closeModal?: () => void }>) {
  const [log, setLog] = useState("Loading…");
  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        const res = await helixSetupLog();
        if (live) setLog(res.log || "(The setup log is empty.)");
      } catch {
        if (live) setLog("(Could not load the setup log.)");
      }
    };
    void load();
    const timer = setInterval(() => void load(), 2000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);
  return (
    <Focusable
      style={{
        width: "640px",
        maxWidth: "92vw",
        padding: "16px 18px",
        display: "flex",
        flexDirection: "column",
        gap: "10px",
      }}
    >
      <div style={{ fontSize: "17px", fontWeight: 700 }}>HelixSR setup log</div>
      <div
        style={{
          maxHeight: "52vh",
          overflowY: "auto",
          background: "rgba(0,0,0,0.35)",
          padding: "10px",
          borderRadius: "6px",
        }}
      >
        <pre
          style={{
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            fontSize: "12px",
            lineHeight: 1.45,
            margin: 0,
          }}
        >
          {log}
        </pre>
      </div>
      <DialogButton onClick={() => closeModal?.()}>Close</DialogButton>
    </Focusable>
  );
}
