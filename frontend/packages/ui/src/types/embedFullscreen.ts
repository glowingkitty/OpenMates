/**
 * Shared interfaces for data-driven embed fullscreen routing.
 *
 * Instead of ActiveChat extracting fields from decodedContent and passing
 * individual props, each fullscreen component receives a standardized `data`
 * prop and extracts its own fields internally.
 *
 * Architecture: docs/architecture/frontend/data-driven-embed-fullscreen-routing.md
 */

/** Raw embed data passed to every fullscreen component via the `data` prop */
export interface EmbedFullscreenRawData {
	decodedContent: Record<string, unknown>;
	attrs?: Record<string, unknown>;
	embedData?: Record<string, unknown>;
	focusChildEmbedId?: string | null;
	restoreFromPip?: boolean;
	/** Quote text to highlight in the fullscreen content (from source quote block click) */
	highlightQuoteText?: string | null;
	/** Line range to highlight in a code embed fullscreen (from #L42 / #L10-L20 suffix) */
	focusLineRange?: { start: number; end: number } | null;
}

/** Common props ALL fullscreen components share (passed as top-level props, not inside data) */
export interface EmbedFullscreenCommonProps {
	onClose: () => void;
	embedId?: string;
	hasPreviousEmbed?: boolean;
	hasNextEmbed?: boolean;
	onNavigatePrevious?: () => void;
	onNavigateNext?: () => void;
	navigateDirection?: 'previous' | 'next' | null;
	showChatButton?: boolean;
	onShowChat?: () => void;
}
