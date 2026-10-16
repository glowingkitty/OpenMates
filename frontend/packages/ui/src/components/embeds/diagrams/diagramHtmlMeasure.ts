/** Bounds for a complete static diagram, including headers and body padding. */
import runtimeSource from './diagramHtmlMeasureRuntime.js?raw';

export const MAX_DIAGRAM_PRESENTATION_HEIGHT = 4096;
export const MAX_DIAGRAM_MEASURE_STEPS = 3;
export const DIAGRAM_MEASURE_CHANNEL = 'openmates-diagram-measure-v1';

export interface DiagramMeasureMessage {
  channel: typeof DIAGRAM_MEASURE_CHANNEL;
  kind: 'measure';
  token: string;
  height: number;
  width: number;
  viewportHeight: number;
}

export function diagramMeasureScript(token: string): string {
  const invocation = 'diagramMeasureRuntime(__OM_DIAGRAM_TOKEN__);';
  const offset = runtimeSource.lastIndexOf(invocation);
  if (offset < 0 || runtimeSource.indexOf(invocation) !== offset) throw new Error('Invalid trusted diagram measurement asset');
  return runtimeSource.slice(0, offset)
    + `diagramMeasureRuntime(${JSON.stringify(token)});`
    + runtimeSource.slice(offset + invocation.length);
}

export function readDiagramMeasurement(data: unknown, token: string, width: number, viewportHeight: number): number | null {
  if (!data || typeof data !== 'object') return null;
  const message = data as Partial<DiagramMeasureMessage>;
  if (message.channel !== DIAGRAM_MEASURE_CHANNEL || message.kind !== 'measure' || message.token !== token
    || message.width !== width || message.viewportHeight !== viewportHeight
    || !Number.isSafeInteger(message.height) || (message.height as number) < 200
    || (message.height as number) > MAX_DIAGRAM_PRESENTATION_HEIGHT + 1) return null;
  return message.height as number;
}

export function nextDiagramPresentationHeight(declared: number, current: number, measured: number, steps: number): { height: number; ready: boolean; error: boolean } {
  if (measured > MAX_DIAGRAM_PRESENTATION_HEIGHT) return { height: current, ready: false, error: true };
  const target = Math.max(declared, current, measured);
  if (target <= current) return { height: current, ready: true, error: false };
  if (steps >= MAX_DIAGRAM_MEASURE_STEPS) return { height: current, ready: false, error: true };
  return { height: target, ready: false, error: false };
}
