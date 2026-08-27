/**
 * Canonical AI model-selection identity and availability helpers.
 * User-visible preferences persist stable model-provider/model IDs while
 * hosting-server IDs remain internal routing choices. Legacy server-prefixed
 * selections are normalized before encrypted persistence and send routing.
 */

import { modelsMetadata, type AIModelMetadata } from '../data/modelsMetadata';

export interface AiModelAvailabilityPreferences {
    disabledModels?: readonly string[];
    disabledServers?: Record<string, readonly string[]>;
}

export function aiModelSelectionValue(model: AIModelMetadata): string {
    return `${model.provider_id}/${model.id}`;
}

export function canonicalizeAiModelSelection(
    selection: string,
    models: AIModelMetadata[] = modelsMetadata,
): string | null {
    if (selection === 'auto') return selection;
    const separator = selection.indexOf('/');
    if (separator <= 0) return null;
    const prefix = selection.slice(0, separator);
    const modelId = selection.slice(separator + 1);
    const model = models.find((candidate) =>
        candidate.id === modelId
        && candidate.for_app_skill === 'ai.ask'
        && (candidate.provider_id === prefix || candidate.servers?.some((server) => server.id === prefix))
    );
    return model ? aiModelSelectionValue(model) : null;
}

export function isAiModelSelectionUsable(
    selection: string,
    preferences: AiModelAvailabilityPreferences,
    isServerHealthy: (serverId: string) => boolean,
    models: AIModelMetadata[] = modelsMetadata,
): boolean {
    const canonicalSelection = canonicalizeAiModelSelection(selection, models);
    if (!canonicalSelection || canonicalSelection === 'auto') return false;
    const separator = canonicalSelection.indexOf('/');
    const providerId = canonicalSelection.slice(0, separator);
    const modelId = canonicalSelection.slice(separator + 1);
    const model = models.find((candidate) =>
        candidate.id === modelId
        && candidate.provider_id === providerId
        && candidate.for_app_skill === 'ai.ask'
    );
    return !!model
        && !preferences.disabledModels?.includes(modelId)
        && !!model.servers?.some((server) =>
            !preferences.disabledServers?.[modelId]?.includes(server.id)
            && isServerHealthy(server.id)
        );
}
