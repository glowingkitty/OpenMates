/**
 * Preview mock data for CodeGetDocsEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/code/CodeGetDocsEmbedFullscreen
 *
 * Note: results use `documentation` (markdown string) — matches CodeGetDocsResult type.
 * The `content` field is legacy and not read by the component.
 */

const svelteDocumentation = `# $state — Svelte 5 Runes

The \`$state\` rune declares reactive state. When you assign to a \`$state\` variable, Svelte automatically updates all DOM nodes that depend on it.

## Basic Usage

\`\`\`svelte
<script>
let count = $state(0);
</script>

<button onclick={() => count++}>
  Clicks: {count}
</button>
\`\`\`

## Deep Reactivity

\`$state\` provides deep reactivity for objects and arrays. Changes to nested properties are tracked automatically.

\`\`\`svelte
<script>
let user = $state({ name: 'Alice', age: 30 });
</script>

<input bind:value={user.name} />
<p>Name: {user.name}</p>
\`\`\`

## With TypeScript

\`\`\`ts
let count = $state<number>(0);
let items = $state<string[]>([]);
\`\`\`

## Differences from Svelte 4

In Svelte 4, reactive variables were declared at the top level of \`<script>\` and updated reactively. In Svelte 5, you explicitly mark state with \`$state()\` — this makes reactivity explicit and works inside functions, classes, and modules.

| Svelte 4 | Svelte 5 |
|----------|----------|
| \`let count = 0;\` (top-level) | \`let count = $state(0);\` |
| \`$: doubled = count * 2;\` | \`let doubled = $derived(count * 2);\` |
| \`onMount(() => ...)\` | Same |

## Related

- [\`$derived\`](https://svelte.dev/docs/svelte/$derived) — computed values
- [\`$effect\`](https://svelte.dev/docs/svelte/$effect) — side effects
- [\`$props\`](https://svelte.dev/docs/svelte/$props) — component props`;

const sampleResults = [
	{
		library: {
			id: '/sveltejs/svelte',
			title: 'Svelte',
			description: 'Cybernetically enhanced web apps'
		},
		documentation: svelteDocumentation,
		source: 'context7',
		word_count: 180
	}
];

/** Default props — shows a fullscreen code docs view with rendered markdown */
const defaultProps = {
	library: 'svelte',
	question: 'How to use $state rune in Svelte 5?',
	results: sampleResults,
	onClose: () => {},
	hasPreviousEmbed: false,
	hasNextEmbed: false
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** With navigation arrows */
	withNavigation: {
		...defaultProps,
		hasPreviousEmbed: true,
		hasNextEmbed: true,
		onNavigatePrevious: () => {},
		onNavigateNext: () => {}
	},

	/** FastAPI documentation example */
	fastapi: {
		library: 'fastapi',
		question: 'How to define path parameters in FastAPI?',
		results: [
			{
				library: {
					id: '/tiangolo/fastapi',
					title: 'FastAPI',
					description: 'FastAPI framework, high performance, easy to learn'
				},
				documentation: `# Path Parameters — FastAPI

Path parameters are defined using Python type hints in the function signature. FastAPI automatically converts them to the correct type.

## Basic Example

\`\`\`python
from fastapi import FastAPI

app = FastAPI()

@app.get("/items/{item_id}")
async def read_item(item_id: int):
    return {"item_id": item_id}
\`\`\`

## With Validation

Use \`Path()\` to add constraints to path parameters.

\`\`\`python
from fastapi import FastAPI, Path

app = FastAPI()

@app.get("/items/{item_id}")
async def read_item(
    item_id: int = Path(title="The ID of the item", ge=1, le=1000)
):
    return {"item_id": item_id}
\`\`\``,
				source: 'context7',
				word_count: 95
			}
		],
		onClose: () => {}
	},

	/** Empty results */
	noResults: {
		library: 'obscure-lib',
		question: 'How to use undocumented feature?',
		results: [],
		onClose: () => {}
	}
};
