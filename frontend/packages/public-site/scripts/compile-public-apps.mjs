import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { parse } from 'yaml';

// The first entries follow the public landing's capability tour. Keep the
// complete order here so newly available apps cannot silently enter the rail.
const appOrder = [
  'events', 'travel', 'code', 'home', 'health', 'social_media', 'fitness', 'mail', 'jobs',
  'web', 'maps', 'weather', 'calendar', 'shopping', 'nutrition', 'news', 'docs',
  'mindmaps', 'math', 'images', 'audio', 'videos', 'books', 'study', 'business',
  'finance', 'design', 'electronics', 'hosting', 'models3d', 'music',
  'life_coaching', 'plants', 'politics', 'pdf', 'ai'
];

/** Read only the capability fields needed by the public landing from canonical app sources. */
export function compilePublicApps(root) {
  const appsRoot = resolve(root, 'backend/apps');
  const excluded = new Set(['openmates', 'projects', 'tasks', 'plans', 'reminder', 'workflows']);
  const apps = [];
  for (const entry of readdirSync(appsRoot, { withFileTypes: true }).filter((item) => item.isDirectory()).sort((a, b) => a.name.localeCompare(b.name))) {
    const id = entry.name;
    const appPath = resolve(appsRoot, id, 'app.yml');
    if (!existsSync(appPath)) continue;
    const app = parse(readFileSync(appPath, 'utf8'));
    if (!app || app.default_enabled === false || app.internal === true || excluded.has(id)) continue;

    const skills = Array.isArray(app.skills) ? app.skills.filter((skill) => skill?.default_enabled !== false && skill?.internal !== true && skill?.id) : [];
    const focusRoot = resolve(appsRoot, id, 'focus_modes');
    const focusIds = new Set();
    if (existsSync(focusRoot)) {
      for (const focusDir of readdirSync(focusRoot, { withFileTypes: true }).filter((item) => item.isDirectory())) {
        const skillPath = resolve(focusRoot, focusDir.name, 'SKILL.md');
        if (!existsSync(skillPath)) continue;
        const raw = readFileSync(skillPath, 'utf8');
        const frontmatter = raw.match(/^---\s*\n([\s\S]*?)\n---(?:\s*\n|$)/);
        if (!frontmatter) continue;
        const focus = parse(frontmatter[1]);
        if (focus?.default_enabled !== false) focusIds.add(focus?.id || focusDir.name.replaceAll('-', '_'));
      }
    }
    const legacy = app.focuses || app.focus_modes || [];
    if (Array.isArray(legacy)) for (const focus of legacy) {
      if (focus?.id && !focusIds.has(focus.id) && focus.default_enabled !== false) focusIds.add(focus.id);
    }

    // Docs and Mind Maps are live direct-artifact pipelines without declared skills.
    if (!skills.length && !focusIds.size && id !== 'docs' && id !== 'mindmaps') continue;
    const icon_image = typeof app.icon_image === 'string' ? app.icon_image.trim() : '';
    if (!icon_image) throw new Error(`Missing public app icon: ${id}`);
    apps.push({ id, icon_image });
  }
  const order = new Map(appOrder.map((id, index) => [id, index]));
  const unknown = apps.filter((app) => !order.has(app.id));
  const unavailable = appOrder.filter((id) => !apps.some((app) => app.id === id));
  if (unknown.length || unavailable.length) {
    throw new Error(`Public app order differs from live capabilities: unknown=${unknown.map((app) => app.id).join(',')} unavailable=${unavailable.join(',')}`);
  }
  return apps.sort((a, b) => order.get(a.id) - order.get(b.id));
}
