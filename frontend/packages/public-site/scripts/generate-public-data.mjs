import { readFileSync, writeFileSync, mkdirSync, copyFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse } from 'yaml';
import { compilePublicLocales } from './compile-public-locales.mjs';
import { compilePublicApps } from './compile-public-apps.mjs';
import { validateLandingAppExamples } from './validate-landing-app-examples.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../../..');
const output = resolve(root, 'frontend/packages/public-site/src/generated');
mkdirSync(output, { recursive: true });
for (const [source, target] of [
  ['data/openmatesEvents.ts', 'data/openmatesEvents.ts'],
  ['legal/privacyPromises.generated.ts', 'legal/privacyPromises.generated.ts'],
  ['legal/trainingPolicies.generated.ts', 'legal/trainingPolicies.generated.ts']
]) copyFileSync(resolve(root, 'frontend/packages/ui/src', source), resolve(root, 'frontend/packages/public-site/src', target));
const landingSource = parse(readFileSync(resolve(root, 'frontend/packages/public-site/src/i18n/landing.yml'), 'utf8'));
const prompts = landingSource.appPrompts;
const promptIds = Object.keys(prompts);
writeFileSync(resolve(output, 'landingLocale.generated.json'), `${JSON.stringify(landingSource.copy, null, 2)}\n`);
const eligible = compilePublicApps(root);
if (eligible.length === 0 || new Set(eligible.map((app) => app.id)).size !== eligible.length) throw new Error('Public app metadata must contain unique available apps');
const eligibleIds = new Set(eligible.map((app) => app.id));
if (promptIds.length !== eligibleIds.size || promptIds.some((id) => !eligibleIds.has(id))) throw new Error('Landing prompt IDs differ from live app capabilities');
validateLandingAppExamples(root, eligibleIds);
const apps = eligible.map((app) => {
  const prompt = prompts[app.id];
  const iconName = app.icon_image?.replace(/\.svg$/, '').trim();
  const icon = iconName === 'plants' ? 'plant' : iconName;
  if (!prompt || !icon) throw new Error(`Missing public prompt/icon for ${app.id}`);
  const iconPath = resolve(root, 'frontend/packages/ui/static/icons', `${icon}.svg`);
  const siteIconPath = resolve(root, 'frontend/apps/website/static/icons', `${icon}.svg`);
  mkdirSync(dirname(siteIconPath), { recursive: true });
  copyFileSync(iconPath, siteIconPath);
  const appIconPath = resolve(root, 'frontend/apps/web_app/static/icons', `${icon}.svg`);
  mkdirSync(dirname(appIconPath), { recursive: true });
  copyFileSync(iconPath, appIconPath);
  return { id: app.id, iconUrl: `/icons/${icon}.svg`, gradient: `var(--color-app-${app.id})`, promptEn: prompt.en, promptDe: prompt.de };
});
writeFileSync(resolve(output, 'publicApps.generated.json'), `${JSON.stringify(apps, null, 2)}\n`);

const { localeData, newsletterLocales, newsletterKeys } = compilePublicLocales(root);
writeFileSync(resolve(output, 'publicLocales.generated.json'), `${JSON.stringify(localeData)}\n`);
writeFileSync(resolve(output, 'newsletterLocale.generated.json'), `${JSON.stringify(newsletterLocales)}\n`);
writeFileSync(resolve(output, 'newsletterKeys.generated.ts'), `export const newsletterKeys = ${JSON.stringify(newsletterKeys)} as const;\nexport type NewsletterKey = typeof newsletterKeys[number];\n`);

const newsletterStore = readFileSync(resolve(root, 'frontend/packages/ui/src/demo_chats/newsletterChatStore.ts'), 'utf8');
const importFiles = [...newsletterStore.matchAll(/from "\.\/data\/(announcements_[^"]+)"/g)].map((match) => match[1]);
const releases = importFiles.map((name) => {
  const source = readFileSync(resolve(root, `frontend/packages/ui/src/demo_chats/data/${name}.ts`), 'utf8');
  const field = (key) => source.match(new RegExp(`\\b${key}: "([^"]+)"`))?.[1];
  const slug = field('slug');
  const publishedAt = field('publishedAt');
  if (!slug || !publishedAt) throw new Error(`Newsletter ${name} lacks slug/publishedAt`);
  const i18nKey = `announcements_${slug.replaceAll('-', '_')}`;
  const localized = Object.fromEntries(['en', 'de'].map((locale) => {
    const entry = localeData[locale].demo_chats[i18nKey];
    if (!entry) throw new Error(`Missing ${locale} newsletter copy ${i18nKey}`);
    const resolveText = (value) => typeof value === 'string' ? value : value?.text;
    return [locale, { title: resolveText(entry.title), description: resolveText(entry.description), bodyMarkdown: resolveText(entry.message) }];
  }));
  const video = slug === 'introducing-openmates-v09' ? {
    type: 'video', url: 'https://vod.api.video/vod/vi43o2FOchAMACeh5blHumCa/mp4/source.mp4',
    posterUrl: 'https://vod.api.video/vod/vi43o2FOchAMACeh5blHumCa/thumbnail.jpg', alt: 'OpenMates introduction video'
  } : null;
  return { id: `news-${slug}`, slug, kind: 'release', publishedAt, updatedAt: publishedAt, author: 'OpenMates', locales: localized, media: video };
}).sort((a, b) => Date.parse(b.publishedAt) - Date.parse(a.publishedAt));
writeFileSync(resolve(output, 'newsReleases.generated.json'), `${JSON.stringify(releases, null, 2)}\n`);
const sharedIcons = ['search', 'task', 'coding', 'chat', 'app', 'workflow', 'github', 'language', 'settings', 'ai', 'recordaudio', 'bluesky', 'mastodon', 'discord', 'instagram', 'pixelfed', 'meetup', 'signal', 'openmates'];
const aliases = { security: 'lock', devices: 'desktop' };
for (const icon of [...sharedIcons, ...Object.keys(aliases)]) {
  const source = resolve(root, 'frontend/packages/ui/static/icons', `${aliases[icon] ?? icon}.svg`);
  const destination = resolve(root, 'frontend/apps/website/static/icons', `${icon}.svg`);
  copyFileSync(source, destination);
  const appDestination = resolve(root, 'frontend/apps/web_app/static/icons', `${icon}.svg`);
  mkdirSync(dirname(appDestination), { recursive: true });
  copyFileSync(source, appDestination);
}
for (const app of ['website', 'web_app']) {
  copyFileSync(resolve(root, 'frontend/packages/ui/static/speechbubble.svg'), resolve(root, `frontend/apps/${app}/static/icons/speechbubble.svg`));
}
console.log(`public-site: ${apps.length} apps, ${releases.length} news releases, ${sharedIcons.length + Object.keys(aliases).length} shared icons`);
