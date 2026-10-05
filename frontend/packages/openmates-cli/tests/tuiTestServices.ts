/** Workspace interaction fixtures admit startup explicitly and never contact npm or download models. */
import type { TuiStartupServices } from "../src/tuiStartup.js";
export const noStartupPrompts: TuiStartupServices = {
  privacyOffer: async () => false,
  privacyInstall: async () => { throw new Error("Unexpected privacy install in workspace fixture"); },
  updateCheck: async () => null,
  updateInstall: async () => { throw new Error("Unexpected update in workspace fixture"); },
  updateSkip: () => { throw new Error("Unexpected update skip in workspace fixture"); },
};
