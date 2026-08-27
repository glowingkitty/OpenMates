// frontend/packages/ui/src/services/unavailableModelRecovery.ts
// Visible recovery helper for saved chat model selections that are no longer
// routable. It notifies before persisting Auto so the user is not silently
// routed away from an exact saved model.
// Architecture: contracts/features/ai-model-routing/contract.yml

const AUTO_SELECTION = "auto";

export type UnavailableModelRecoveryPhase = "load" | "send";

export type UnavailableModelRecoveryRequest = {
  phase: UnavailableModelRecoveryPhase;
  selection: string;
  isUsable: (model: string) => boolean;
  notify: (event: {
    phase: UnavailableModelRecoveryPhase;
    unavailableModel: string;
  }) => void;
  persistSelection: (selection: typeof AUTO_SELECTION) => Promise<void>;
};

export async function recoverUnavailableModelSelection({
  phase,
  selection,
  isUsable,
  notify,
  persistSelection,
}: UnavailableModelRecoveryRequest): Promise<string> {
  if (selection === AUTO_SELECTION || isUsable(selection)) return selection;

  notify({ phase, unavailableModel: selection });
  await persistSelection(AUTO_SELECTION);
  return AUTO_SELECTION;
}
