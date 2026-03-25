/**
 * Preview mock data for Not404Screen.
 * Access at: /dev/preview/Not404Screen
 */
import { notFoundPathStore } from '../stores/notFoundPathStore';

export const defaultProps = {
    onSearch: (query: string) => console.log('[preview] search:', query),
    onAskAI: (message: string) => console.log('[preview] ask AI:', message),
};

export const variants: Record<string, typeof defaultProps> = {
    'Single segment path': {
        ...defaultProps,
        get onSearch() {
            notFoundPathStore.set('/iphone-review');
            return defaultProps.onSearch;
        },
    },
    'Multi-segment path': {
        ...defaultProps,
        get onSearch() {
            notFoundPathStore.set('/ai/image-generator');
            return defaultProps.onSearch;
        },
    },
    'Path with underscores': {
        ...defaultProps,
        get onSearch() {
            notFoundPathStore.set('/best_products/2024');
            return defaultProps.onSearch;
        },
    },
};
