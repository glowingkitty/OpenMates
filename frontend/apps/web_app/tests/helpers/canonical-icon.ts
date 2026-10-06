import { expect, type Locator } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const canonicalIcon = (name: string) =>
	readFileSync(
		resolve(__dirname, '../../../../packages/ui/static/icons', `${name}.svg`),
		'utf8'
	).trim();

export async function expectCanonicalMask(
	icon: Locator,
	name: string,
	pseudo: '::before' | '::after' | null = null
) {
	await expect
		.poll(() =>
			icon.evaluate(
				async (element, { canonical, pseudo }) => {
					const mask = getComputedStyle(element, pseudo).maskImage;
					const match = mask.match(/^url\(["']?(.*?)["']?\)$/);
					if (!match) return false;
					type Shape = { tag: string; attributes: [string, string][]; children: Shape[] };
					const shape = (node: Element): Shape => ({
						tag: node.tagName,
						attributes: Array.from(
							node.attributes,
							(attribute) => [attribute.name, attribute.value] as [string, string]
						).sort(([a], [b]) => a.localeCompare(b)),
						children: Array.from(node.children, shape)
					});
					const parse = (svg: string) => {
						const document = new DOMParser().parseFromString(svg, 'image/svg+xml');
						if (document.querySelector('parsererror'))
							throw new Error('Invalid canonical icon SVG');
						return shape(document.documentElement);
					};
					const actual = await (await fetch(match[1])).text();
					return JSON.stringify(parse(actual)) === JSON.stringify(parse(canonical));
				},
				{ canonical: canonicalIcon(name), pseudo }
			)
		)
		.toBe(true);
}
