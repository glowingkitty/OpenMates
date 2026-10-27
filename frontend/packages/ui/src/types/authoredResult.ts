/** Presentation data from validated, encrypted authored-result content. */
export interface AuthoredResultSource {
	url?: string;
	label?: string;
	embed_ref?: string;
}

export type AuthoredResultImage = string | {
	url?: string;
	embed_ref?: string;
	caption?: string;
	attribution?: string;
};

export interface AuthoredResultMetadata {
	schema_version: 1;
	/** Canonical app-qualified identity; unknown future kinds stay readable. */
	kind: string;
	origin: 'researched' | 'user_provided' | 'draft';
	sources: AuthoredResultSource[];
	observed_at?: string;
	images?: AuthoredResultImage[];
}

/** Kept inside encrypted content. Never persist plaintext keys or blob URLs elsewhere. */
export interface AuthoredResultMedia {
	source_embed_id: string;
	s3_base_url: string;
	aes_key: string;
	aes_nonce?: string;
	files: Partial<Record<'preview' | 'original' | 'full', {
		s3_key: string;
		/** Existing encrypted-media metadata is passed to the shared decryptor. */
		[field: string]: unknown;
	}>>;
	caption?: string;
	attribution?: string;
}

export interface AuthoredResultItemReference {
	embed_id: string;
	kind: string;
	title: string;
	embed_ref: string;
}

export interface AuthoredResultsContent {
	type: 'authored_results';
	app_id: 'ai';
	skill_id: 'authored_results';
	schema_version: 1;
	title: string;
	status: 'processing' | 'finished' | 'error' | 'cancelled';
	embed_ids: string[];
	items: AuthoredResultItemReference[];
	view: { mode: 'auto' | 'cards' | 'map'; embeds: string[] };
	validation?: {
		status: 'valid' | 'partial' | 'invalid_source';
		warnings: Array<{ code: string; path: string }>;
		parse_error?: string | null;
	};
}
