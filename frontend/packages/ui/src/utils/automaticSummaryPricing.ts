import { modelsMetadata, type AIModelMetadata } from '../data/modelsMetadata';

export interface AutomaticSummaryRate {
  name: string;
  inputTokensPerCredit: number;
  outputTokensPerCredit: number;
}

export interface AutomaticSummaryPricing {
  primary: AutomaticSummaryRate;
  fallback: AutomaticSummaryRate;
}

function ordinaryRate(modelId: string): AutomaticSummaryRate | null {
  const model = modelsMetadata.find((candidate: AIModelMetadata) => candidate.id === modelId);
  const inputTokensPerCredit = model?.pricing?.input_tokens_per_credit;
  const outputTokensPerCredit = model?.pricing?.output_tokens_per_credit;
  if (!model || !inputTokensPerCredit || !outputTokensPerCredit ||
    !Number.isFinite(inputTokensPerCredit) || !Number.isFinite(outputTokensPerCredit) ||
    inputTokensPerCredit <= 0 || outputTokensPerCredit <= 0) return null;
  return { name: model.name, inputTokensPerCredit, outputTokensPerCredit };
}

/** Ordinary catalog rates for a distinct, only-when-needed summary operation. */
export function getAutomaticSummaryPricing(): AutomaticSummaryPricing | null {
  const primary = ordinaryRate('gemini-3.5-flash-lite');
  const fallback = ordinaryRate('gpt-oss-120b');
  return primary && fallback ? { primary, fallback } : null;
}
