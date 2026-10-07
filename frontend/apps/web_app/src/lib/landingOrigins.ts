interface LandingOriginOverrides {
	webapp?: string;
	website?: string;
}

function configuredOrigin(value: string | undefined, fallback: string): string {
	if (!value) return fallback;
	const url = new URL(value);
	if (url.protocol !== 'https:' && url.protocol !== 'http:') {
		throw new Error('Landing destinations must use HTTP or HTTPS');
	}
	return url.origin;
}

/** Resolve by request host: Vercel's development deployment also uses a production build. */
export function getLandingOrigins(url: URL, overrides: LandingOriginOverrides = {}) {
	const developmentLanding = url.hostname === 'landing.dev.openmates.org';
	const webapp = developmentLanding ? 'https://app.dev.openmates.org' : url.origin;
	return {
		appBaseUrl: configuredOrigin(overrides.webapp, webapp),
		websiteBaseUrl: configuredOrigin(overrides.website, url.origin)
	};
}
