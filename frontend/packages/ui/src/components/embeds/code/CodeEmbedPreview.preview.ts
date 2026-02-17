/**
 * Preview mock data for CodeEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/code/CodeEmbedPreview
 */

const sampleCode = `import { onMount } from 'svelte';

interface Props {
  title: string;
  count?: number;
}

let { title, count = 0 }: Props = $props();
let isLoading = $state(false);
let displayTitle = $derived(title.toUpperCase());

onMount(() => {
  console.log('Component mounted');
});`;

/** Default props — shows a finished code embed with TypeScript content */
const defaultProps = {
	id: 'preview-code-1',
	language: 'typescript',
	filename: 'MyComponent.svelte',
	lineCount: 14,
	status: 'finished' as const,
	codeContent: sampleCode,
	isMobile: false,
	onFullscreen: () => console.log('[Preview] Fullscreen clicked')
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Processing state — shows loading/streaming animation */
	processing: {
		id: 'preview-code-processing',
		language: 'python',
		filename: 'main.py',
		lineCount: 0,
		status: 'processing' as const,
		codeContent: '',
		isMobile: false
	},

	/** Python code example */
	python: {
		id: 'preview-code-python',
		language: 'python',
		filename: 'api_handler.py',
		lineCount: 10,
		status: 'finished' as const,
		codeContent: `from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class UserRequest(BaseModel):
    username: str
    email: str

@app.post("/users")
async def create_user(request: UserRequest):
    return {"status": "created", "user": request.username}`,
		isMobile: false
	},

	/** Error state */
	error: {
		id: 'preview-code-error',
		language: 'javascript',
		status: 'error' as const,
		codeContent: '',
		isMobile: false
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-code-mobile',
		isMobile: true
	}
};
