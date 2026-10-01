// Pure source fixtures only; no browser, app, or provider execution.
import fs from 'node:fs';
import path from 'node:path';
import { stripTypeScriptTypes } from 'node:module';
import { pathToFileURL } from 'node:url';
const root = process.cwd();
// Dynamic fixture offsets use a fixed synthetic clock for snapshot freshness.
Date.now = () => Date.parse('2026-03-15T08:30:00Z');
async function load(file) {
  if (!fs.existsSync(file)) return {default: {}, variants: {}};
  let source = stripTypeScriptTypes(fs.readFileSync(file, 'utf8'));
  source = source.replace("from '../../../utils/remotionTimelineParser'", `from '${pathToFileURL(path.join(root,'frontend/packages/ui/src/utils/remotionTimelineParser.ts'))}'`);
  source = source.replace("from './FinanceCheckAccountsEmbedPreview.preview'", `from '${pathToFileURL(path.join(root,'frontend/packages/ui/src/components/embeds/finance/FinanceCheckAccountsEmbedPreview.preview.ts'))}'`);
  return import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
}
const registry = await load(path.join(root,'frontend/packages/ui/src/data/embedRegistry.generated.ts'));
const source = fs.readFileSync('frontend/apps/web_app/src/routes/dev/preview/embeds/[app=embedApp]/+page.svelte','utf8');
const registrySource = source.slice(source.indexOf('const APP_REGISTRY:'), source.indexOf('const APP_ICON:'));
const showcase = (await import('data:text/javascript;base64,' + Buffer.from(stripTypeScriptTypes(registrySource) + '\nexport default APP_REGISTRY;').toString('base64'))).default;
const result = {};
const availableFiles = [];
for (const paths of [registry.EMBED_PREVIEW_COMPONENTS, registry.EMBED_FULLSCREEN_COMPONENTS]) {
  for (const component of Object.values(paths)) {
    if (result[component]) continue;
    const fixtureFile = path.join(root,'frontend/packages/ui/src/components/embeds',component.replace('.svelte','.preview.ts'));
    if (fs.existsSync(fixtureFile)) availableFiles.push(component);
    const mod = await load(fixtureFile);
    result[component] = Object.entries(mod.variants ?? {}).map(([name,props])=>({name,props:{...(mod.default??{}),...props}}));
  }
}
const metadata = {};
for (const sections of Object.values(showcase)) for (const section of sections) {
  const component = section.previewPath.replace('embeds/','')+'.svelte';
  metadata[component]={inlineLinkText:section.inlineLinkText,quoteText:section.quoteText,isAppSkill:!!section.isAppSkill};
}
process.stdout.write(JSON.stringify({preview:registry.EMBED_PREVIEW_COMPONENTS,fullscreen:registry.EMBED_FULLSCREEN_COMPONENTS,metadata,availableFiles,variants:result}));
