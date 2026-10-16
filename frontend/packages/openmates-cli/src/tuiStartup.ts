/** Ordered fullscreen startup gates. Workspace keys and loading start only after admission. */
import { claimPrivacyOffer } from "./privacyModel.js";
import { runPrivacyCommand } from "./privacyCommands.js";
import { checkTuiUpdate, deferTuiUpdate, installTuiUpdate, type TuiUpdateOffer } from "./selfUpdate.js";
import type { TuiState } from "./tuiRenderer.js";
import type { TerminalKey } from "./tuiTerminal.js";

export type TuiStartupScreen = {
  kind: "checking" | "privacy" | "update";
  selected: 0 | 1;
  busy: boolean;
  status: string | null;
  update: TuiUpdateOffer | null;
};
export type TuiStartupServices = {
  privacyOffer: () => Promise<boolean>;
  privacyInstall: (progress: (received: number, total: number) => void) => Promise<unknown>;
  updateCheck: () => Promise<TuiUpdateOffer | null>;
  updateInstall: (offer: TuiUpdateOffer) => Promise<void>;
  updateSkip: () => void;
};
const services: TuiStartupServices = {
  privacyOffer: claimPrivacyOffer,
  privacyInstall: (progress) => runPrivacyCommand("install", { yes: true, progress }),
  updateCheck: checkTuiUpdate,
  updateInstall: installTuiUpdate,
  updateSkip: deferTuiUpdate,
};

export function createTuiStartup(options: {
  state: TuiState; render: () => void; closed: () => boolean;
  ready: () => void; updated: () => void; services?: TuiStartupServices;
}) {
  const { state, render, closed, ready, updated } = options;
  const api = options.services ?? services;
  // Select Skip by default so an accidental Enter cannot download or install.
  const screen = (kind: TuiStartupScreen["kind"]): TuiStartupScreen => ({ kind, selected: 1, busy: false, status: null, update: null });
  const enterWorkspace = () => {
    if (closed()) return;
    state.startup = null; state.privacyOffer = false;
    ready(); render();
  };
  const showUpdate = async () => {
    if (closed()) return;
    state.privacyOffer = false;
    state.startup = screen("checking"); render();
    let update: TuiUpdateOffer | null = null;
    try { update = await api.updateCheck(); } catch { /* Offline startup remains usable. */ }
    if (closed()) return;
    if (!update) { enterWorkspace(); return; }
    state.startup = { ...screen("update"), update }; render();
  };
  return {
    async start(): Promise<void> {
      state.startup = screen("checking"); render();
      let offer = false;
      try { offer = await api.privacyOffer(); } catch { /* Keep existing basic detection. */ }
      if (closed()) return;
      if (offer) { state.privacyOffer = true; state.startup = screen("privacy"); render(); }
      else await showUpdate();
    },
    async handleKey(_chunk: string, key: TerminalKey): Promise<boolean> {
      const current = state.startup;
      if (!current) return false;
      if (current.busy || current.kind === "checking") return true;
      if (["tab", "left", "right", "up", "down"].includes(key.name ?? "")) {
        current.selected = current.selected === 0 ? 1 : 0; render(); return true;
      }
      const choice = key.name === "f6" || key.name === "y" ? 0
        : key.name === "f7" || key.name === "n" || key.name === "escape" ? 1
          : key.name === "return" ? current.selected : null;
      if (choice === null) return true;
      current.busy = true; current.status = null; render();
      try {
        if (current.kind === "privacy") {
          if (choice === 0) {
            state.privacyInstalling = true; current.status = "Downloading and enabling the offline model…"; render();
            try {
              await api.privacyInstall((received, total) => {
                if (!closed()) { current.status = `Offline model download: ${Math.floor(received * 100 / total)}%`; render(); }
              });
            } finally { state.privacyInstalling = false; }
          }
          await showUpdate();
        } else if (choice === 1) {
          api.updateSkip(); enterWorkspace();
        } else if (current.update) {
          current.status = "Installing update… OpenMates will reopen when finished."; render();
          await api.updateInstall(current.update);
          if (!closed()) updated();
        }
      } catch (error) {
        if (!closed()) { current.busy = false; current.status = error instanceof Error ? error.message : String(error); render(); }
      }
      return true;
    },
  };
}
