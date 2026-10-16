import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { parse } from 'yaml';

/** Compile only public EN/DE translations from the canonical YAML source files. */
export function compilePublicLocales(root) {
  const sources = resolve(root, 'frontend/packages/ui/src/i18n/sources');
  const readYaml = (path) => {
    const parsed = parse(readFileSync(resolve(sources, path), 'utf8'));
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error(`Invalid translation source: ${path}`);
    return parsed;
  };
  const setNestedValue = (target, dottedKey, leaf) => {
    const path = dottedKey.split('.');
    let node = target;
    for (const part of path.slice(0, -1)) node = node[part] ??= {};
    const key = path.at(-1);
    node[key] = node[key] && typeof node[key] === 'object' ? { ...node[key], ...leaf } : leaf;
  };
  const compileFile = (target, sourcePath, keyPrefix, locale, { allowEmpty = false, required = false, filter = () => true } = {}) => {
    const source = readYaml(sourcePath);
    for (const [key, entry] of Object.entries(source)) {
      if (!filter(key)) continue;
      const raw = entry?.[locale];
      if (typeof raw !== 'string') {
        if (required) throw new Error(`Missing ${locale} translation: ${sourcePath}:${key}`);
        continue;
      }
      const value = raw.replace(/\n+$/, '');
      if (!value && !allowEmpty) {
        if (required) throw new Error(`Empty ${locale} translation: ${sourcePath}:${key}`);
        continue;
      }
      setNestedValue(target, keyPrefix && key !== keyPrefix ? `${keyPrefix}.${key}` : key, { text: value });
    }
  };

  const newsletterSource = readYaml('settings/main.yml');
  const newsletterKeys = Object.keys(newsletterSource).filter((key) => key.startsWith('newsletter_public_')).sort();
  if (!newsletterKeys.length) throw new Error('No canonical public newsletter keys found');
  const announcementFiles = readdirSync(resolve(sources, 'demo_chats'))
    .filter((name) => /^announcements_.*\.yml$/.test(name)).sort();
  const localeData = {};
  const newsletterLocales = {};
  for (const locale of ['en', 'de']) {
    const legal = {};
    for (const name of ['privacy', 'terms', 'imprint']) compileFile(legal, `legal/${name}.yml`, name, locale);
    const metadata = {};
    for (const name of ['legal_privacy', 'legal_terms', 'legal_imprint']) compileFile(metadata, `metadata/${name}.yml`, name, locale, { allowEmpty: true });
    const demoChats = {};
    for (const name of announcementFiles) compileFile(demoChats, `demo_chats/${name}`, name.slice(0, -4), locale);
    localeData[locale] = { legal, metadata, demo_chats: demoChats };

    const newsletter = {};
    compileFile(newsletter, 'settings/main.yml', '', locale, { required: true, filter: (key) => key.startsWith('newsletter_public_') });
    for (const key of newsletterKeys) {
      const compiled = newsletter[key]?.text;
      if (typeof compiled !== 'string' || !compiled.trim() || compiled !== newsletterSource[key][locale].replace(/\n+$/, '')) {
        throw new Error(`Missing/stale ${locale} newsletter translation: ${key}`);
      }
      newsletter[key] = compiled;
    }
    newsletterLocales[locale] = newsletter;
  }
  return { localeData, newsletterLocales, newsletterKeys, sourcePaths: [
    ...['privacy', 'terms', 'imprint'].map((name) => `legal/${name}.yml`),
    ...['legal_privacy', 'legal_terms', 'legal_imprint'].map((name) => `metadata/${name}.yml`),
    ...announcementFiles.map((name) => `demo_chats/${name}`),
    'settings/main.yml'
  ] };
}
