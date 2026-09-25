/**
 * Preview mock data for CodeEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/code/CodeEmbedFullscreen
 */

const sampleCode = `import { onMount } from 'svelte';
import { browser } from '$app/environment';

interface Props {
  title: string;
  items: string[];
  onSelect?: (item: string) => void;
}

let { title, items, onSelect }: Props = $props();

let searchQuery = $state('');
let isExpanded = $state(false);

let filteredItems = $derived(
  items.filter(item =>
    item.toLowerCase().includes(searchQuery.toLowerCase())
  )
);

onMount(() => {
  if (browser) {
    console.log('Component mounted in browser');
  }
});

function handleSelect(item: string) {
  onSelect?.(item);
  isExpanded = false;
}`;

/** Default props — shows a fullscreen code view */
const defaultProps = {
	language: 'typescript',
	filename: 'SearchableList.svelte',
	lineCount: 32,
	codeContent: sampleCode,
	onClose: () => {},
	hasPreviousEmbed: true,
	hasNextEmbed: true,
	onNavigatePrevious: () => {},
	onNavigateNext: () => {}
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Single embed — no navigation arrows */
	singleEmbed: {
		...defaultProps,
		hasPreviousEmbed: false,
		hasNextEmbed: false
	},

	/** Long code — tests scrolling behavior */
	longCode: {
		...defaultProps,
		filename: 'long_file.py',
		language: 'python',
		lineCount: 100,
		codeContent: Array.from(
			{ length: 100 },
			(_, i) => `line_${i + 1} = "content for line ${i + 1}"`
		).join('\n')
	},

	/** Virtual file streamed from a connected project source. */
	remoteSource: {
		data: {
			decodedContent: {
				type: 'remote_file_preview',
				code: sampleCode,
				filename: 'SearchableList.svelte',
				language: 'svelte',
				line_count: 32,
				remote_source_label: 'Studio Mac'
			},
			attrs: {
				type: 'code-code',
				virtual: true
			}
		},
		embedId: 'remote:studio-mac:SearchableList.svelte',
		onClose: () => {},
		hasPreviousEmbed: false,
		hasNextEmbed: false
	}
};
