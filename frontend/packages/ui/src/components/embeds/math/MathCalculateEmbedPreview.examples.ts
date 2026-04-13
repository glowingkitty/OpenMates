/**
 * App-store examples for the math calculate skill.
 *
 * Three example calculations showing different modes: basic arithmetic,
 * unit conversion, and algebraic expression. The result shapes match
 * the real backend CalculateResult format so the preview + fullscreen
 * render identically. A "Sample data" banner is shown at the top of
 * the fullscreen via the is_store_example flag set by SkillExamplesSection.
 */

export interface MathCalculateStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: MathCalculateStoreExample[] = [
  {
    "id": "store-example-math-calculate-1",
    "query": "sqrt(144) + 3^4",
    "query_translation_key": "settings.app_store_examples.math.calculate.1",
    "status": "finished",
    "results": [
      {
        "expression": "sqrt(144) + 3^4",
        "result": "93",
        "result_type": "number",
        "mode": "evaluate"
      }
    ]
  },
  {
    "id": "store-example-math-calculate-2",
    "query": "150 km/h to mph",
    "query_translation_key": "settings.app_store_examples.math.calculate.2",
    "status": "finished",
    "results": [
      {
        "expression": "150 km/h to mph",
        "result": "93.2057 mph",
        "result_type": "unit",
        "mode": "convert"
      }
    ]
  },
  {
    "id": "store-example-math-calculate-3",
    "query": "sin(pi/4) * cos(pi/4)",
    "query_translation_key": "settings.app_store_examples.math.calculate.3",
    "status": "finished",
    "results": [
      {
        "expression": "sin(pi/4) * cos(pi/4)",
        "result": "0.5",
        "result_type": "number",
        "mode": "evaluate"
      }
    ]
  }
];

export default examples;
