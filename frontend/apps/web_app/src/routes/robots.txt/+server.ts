import type { RequestHandler } from './$types';

export const GET: RequestHandler = ({ url }) => {
    const hostname = url.hostname;
    
    // Check if we are on a .dev. subdomain (e.g., app.dev.openmates.org)
    // or if the environment variable suggests a development version
    const isDevSubdomain = hostname.includes('.dev.') || hostname.startsWith('dev.');
    
    let content = '';
    
    if (isDevSubdomain) {
        // Block all crawlers on development subdomains
        content = [
            'User-agent: *',
            'Disallow: /',
            '',
            '# Development/Staging environment - crawling prohibited'
        ].join('\n');
    } else {
        // Standard robots.txt for production
        content = [
            'User-agent: *',
            'Allow: /',
            '',
            'Sitemap: https://openmates.org/sitemap.xml'
        ].join('\n');
    }

    return new Response(content, {
        headers: {
            'Content-Type': 'text/plain'
        }
    });
};
