const OFFICIAL_PUBLICATION_HOSTS = new Set(['openmates.org', 'localhost', '127.0.0.1']);

export function isOfficialOpenMatesPublicationHost(
	hostname: string,
	buildEnvironment = import.meta.env.VITE_ENV
): boolean {
	if (buildEnvironment === 'self_hosted') return false;
	const normalizedHostname = hostname.toLowerCase().replace(/\.$/, '');
	return (
		OFFICIAL_PUBLICATION_HOSTS.has(normalizedHostname) ||
		normalizedHostname.endsWith('.openmates.org')
	);
}
