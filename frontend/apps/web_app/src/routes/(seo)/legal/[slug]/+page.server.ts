import { env } from '$env/dynamic/public';
import { error } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';
import { buildPrivacyPolicyContent, buildTermsOfUseContent, buildImprintContent } from '@repo/public-site/legal/buildLegalContent';
import { legalTranslate } from '@repo/public-site/legal/legalLocale';
import { privacyPolicyChat } from '@repo/public-site/legal/documents/privacy-policy';
import { termsOfUseChat } from '@repo/public-site/legal/documents/terms-of-use';
import { imprintChat } from '@repo/public-site/legal/documents/imprint';
import MarkdownIt from 'markdown-it';
import { getSiteOrigin } from '$lib/backendUrl';

const markdown = new MarkdownIt({ html: false, linkify: true });
const definitions = {
  privacy: { chat: privacyPolicyChat, build: buildPrivacyPolicyContent },
  terms: { chat: termsOfUseChat, build: buildTermsOfUseContent },
  imprint: { chat: imprintChat, build: (t: (key: string) => string) => buildImprintContent(t) }
} as const;

export const load: PageServerLoad = ({ params, setHeaders, url, request }) => {
  if (!(params.slug in definitions)) error(404, 'Legal document not found');
  const slug = params.slug as keyof typeof definitions;
  const definition = definitions[slug];
  const locale = url.searchParams.get('lang') === 'de' || (!url.searchParams.has('lang') && request.headers.get('accept-language')?.toLowerCase().startsWith('de')) ? 'de' : 'en';
  const t = (key: string) => legalTranslate(locale, key);
  const title = t(definition.chat.title);
  const description = t(definition.chat.description);
  const body = definition.build(t, { lastUpdated: definition.chat.metadata.lastUpdated, locale });
  let websiteOrigin = getSiteOrigin(url);
  if (env.PUBLIC_LANDING_WEBSITE_URL) {
    try {
      const configured = new URL(env.PUBLIC_LANDING_WEBSITE_URL);
      if (configured.protocol === 'http:' || configured.protocol === 'https:') websiteOrigin = configured.origin;
    } catch {
      // Serve the legal document from this app until a valid website origin is configured.
    }
  }
  const canonicalUrl = `${websiteOrigin}/legal/${slug}`;
  const isDevHost = websiteOrigin !== url.origin || url.hostname.includes('.dev.') || url.hostname.startsWith('dev.') || url.hostname.endsWith('.vercel.app') || url.hostname === 'localhost' || url.hostname === '127.0.0.1';
  const jsonLd = JSON.stringify({ '@context': 'https://schema.org', '@type': 'WebPage', name: title, description, url: canonicalUrl, inLanguage: locale, publisher: { '@type': 'Organization', name: 'OpenMates', url: websiteOrigin } });
  setHeaders({ 'Cache-Control': 'public, s-maxage=86400, stale-while-revalidate=604800' });
  return { slug, locale, title, description, keywords: definition.chat.keywords, bodyHtml: markdown.render(body), canonicalUrl, websiteOrigin, jsonLd, isDevHost };
};
