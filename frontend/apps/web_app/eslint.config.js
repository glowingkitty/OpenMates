import { config } from '@repo/eslint-config/index.js';

export default [
	{
		ignores: [
			'.svelte-kit/*',
			// svelte-eslint-parser does not parse Svelte 5 <svelte:boundary> yet; svelte-check still validates this route.
			'src/routes/dev/preview/embeds/*/+page.svelte'
		]
	},
	...config
];
