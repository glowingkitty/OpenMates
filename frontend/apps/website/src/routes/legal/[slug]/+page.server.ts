import { error } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';
import { buildPrivacyPolicyContent, buildTermsOfUseContent, buildImprintContent } from '@repo/public-site/legal/buildLegalContent';
import { legalTranslate } from '@repo/public-site/legal/legalLocale';
import { privacyPolicyChat } from '@repo/public-site/legal/documents/privacy-policy';
import { termsOfUseChat } from '@repo/public-site/legal/documents/terms-of-use';
import { imprintChat } from '@repo/public-site/legal/documents/imprint';
import MarkdownIt from 'markdown-it';
import { siteOrigin, isDevelopmentHost } from '$lib/server/origins';

const markdown = new MarkdownIt({ html: false, linkify: true });
const definitions = {
  privacy: { chat: privacyPolicyChat, build: buildPrivacyPolicyContent },
  terms: { chat: termsOfUseChat, build: buildTermsOfUseContent },
  imprint: { chat: imprintChat, build: (t: (key: string) => string) => buildImprintContent(t) }
} as const;
export const load: PageServerLoad = ({ params, url, setHeaders }) => {
  if (!(params.slug in definitions)) error(404, 'Legal document not found');
  const slug = params.slug as keyof typeof definitions;
  const definition = definitions[slug];
  const locale = url.searchParams.get('lang') === 'de' ? 'de' : 'en';
  const t = (key: string) => legalTranslate(locale, key);
  const title = t(definition.chat.title);
  const description = t(definition.chat.description);
  const body = definition.build(t, { lastUpdated: definition.chat.metadata.lastUpdated, locale });
  const canonicalUrl = `${siteOrigin(url)}/legal/${slug}`;
  const jsonLd = JSON.stringify({ '@context': 'https://schema.org', '@type': 'WebPage', name: title, description, url: canonicalUrl, inLanguage: locale, publisher: { '@type': 'Organization', name: 'OpenMates' }});
  setHeaders({ 'Cache-Control': 'public, s-maxage=86400, stale-while-revalidate=604800' });
  return { slug, locale, title, description, bodyHtml: markdown.render(body), canonicalUrl, jsonLd, isDevHost: isDevelopmentHost(url) };
};
