/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * Temporary Playwright diagnostics for overlapping interactive surfaces.
 *
 * Captures computed hit-testing state without changing pointer behavior.
 * Remove this helper after the welcome overlay regression is identified.
 */
export {};

async function logHitTestDiagnostics(locator: any, label: string): Promise<void> {
	const diagnostics = await locator.evaluate((target: HTMLElement) => {
		const describe = (element: Element) => {
			const style = window.getComputedStyle(element);
			return {
				tag: element.tagName,
				testId: element.getAttribute('data-testid'),
				classes: element.className,
				pointerEvents: style.pointerEvents,
				position: style.position,
				zIndex: style.zIndex,
				opacity: style.opacity,
				visibility: style.visibility,
				transform: style.transform
			};
		};
		const rect = target.getBoundingClientRect();
		const points = [
			{ name: 'center', x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 },
			{ name: 'inset', x: rect.left + Math.min(12, rect.width / 4), y: rect.top + Math.min(12, rect.height / 4) }
		];
		const ancestors = [];
		let current: Element | null = target;
		while (current && ancestors.length < 10) {
			ancestors.push(describe(current));
			current = current.parentElement;
		}
		return {
			rect: { left: rect.left, top: rect.top, width: rect.width, height: rect.height },
			ancestors,
			points: points.map((point) => ({
				...point,
				stack: document.elementsFromPoint(point.x, point.y).slice(0, 10).map(describe)
			}))
		};
	});
	console.log(`[hit-test:${label}] ${JSON.stringify(diagnostics)}`);
}

module.exports = { logHitTestDiagnostics };
