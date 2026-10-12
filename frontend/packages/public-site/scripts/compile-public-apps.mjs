import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { parse } from 'yaml';

const excluded = new Set(['openmates', 'projects', 'tasks', 'plans', 'reminder', 'workflows', 'plants']);
const capabilityTypes = new Set(['skill', 'focus', 'artifact']);

/** Check that a published default points to an available capability in this app. */
export function validateLandingMetadata(id, landing, skills, focuses, artifacts) {
  if (!landing || typeof landing !== 'object' || Array.isArray(landing)) {
    throw new Error(`Missing landing metadata for public app: ${id}`);
  }
  if (!Number.isInteger(landing.order) || landing.order < 0) {
    throw new Error(`Invalid landing order for ${id}`);
  }
  const { type, id: capabilityId } = landing.capability ?? {};
  if (!capabilityTypes.has(type) || typeof capabilityId !== 'string' || !capabilityId.trim()) {
    throw new Error(`Invalid landing capability for ${id}`);
  }
  const available = { skill: skills, focus: focuses, artifact: artifacts }[type];
  if (!available.has(capabilityId)) {
    throw new Error(`Unavailable landing capability for ${id}: ${type}:${capabilityId}`);
  }
  for (const locale of ['en', 'de']) {
    const caption = landing.caption?.[locale];
    if (typeof caption !== 'string' || !caption.trim() || caption !== caption.trim()) {
      throw new Error(`Missing or invalid ${locale} landing caption for ${id}`);
    }
  }
  if (typeof landing.example_chat_id !== 'string' || !/^example-[a-z0-9-]+$/.test(landing.example_chat_id)) {
    throw new Error(`Missing or invalid landing example for ${id}`);
  }
  return landing;
}

/** Read public tour defaults from canonical app sources. */
export function compilePublicApps(root) {
  const appsRoot = resolve(root, 'backend/apps');
  const apps = [];
  for (const entry of readdirSync(appsRoot, { withFileTypes: true }).filter((item) => item.isDirectory()).sort((a, b) => a.name.localeCompare(b.name))) {
    const id = entry.name;
    const appPath = resolve(appsRoot, id, 'app.yml');
    if (!existsSync(appPath)) continue;
    const app = parse(readFileSync(appPath, 'utf8'));
    if (!app || app.default_enabled === false || app.internal === true || app.landing?.enabled === false || excluded.has(id)) continue;

    const skills = new Set(Array.isArray(app.skills) ? app.skills.filter((skill) => skill?.default_enabled !== false && skill?.internal !== true && skill?.id).map((skill) => skill.id) : []);
    const focusRoot = resolve(appsRoot, id, 'focus_modes');
    const focuses = new Set();
    if (existsSync(focusRoot)) {
      for (const focusDir of readdirSync(focusRoot, { withFileTypes: true }).filter((item) => item.isDirectory())) {
        const skillPath = resolve(focusRoot, focusDir.name, 'SKILL.md');
        if (!existsSync(skillPath)) continue;
        const raw = readFileSync(skillPath, 'utf8');
        const frontmatter = raw.match(/^---\s*\n([\s\S]*?)\n---(?:\s*\n|$)/);
        if (!frontmatter) continue;
        const focus = parse(frontmatter[1]);
        if (focus?.default_enabled !== false) focuses.add(focus?.id || focusDir.name.replaceAll('-', '_'));
      }
    }
    const legacy = app.focuses || app.focus_modes || [];
    if (Array.isArray(legacy)) for (const focus of legacy) {
      if (focus?.id && focus.default_enabled !== false) focuses.add(focus.id);
    }
    const directEmbeds = Array.isArray(app.embed_types) ? app.embed_types.filter((embed) => embed?.category === 'direct' && embed?.id) : [];
    const artifacts = new Set(directEmbeds.map((embed) => embed.id));

    // An app with no available behavior does not enter the tour.
    if (!skills.size && !focuses.size && !artifacts.size) continue;
    const icon_image = typeof app.icon_image === 'string' ? app.icon_image.trim() : '';
    if (!icon_image) throw new Error(`Missing public app icon: ${id}`);
    const landing = validateLandingMetadata(id, app.landing, skills, focuses, artifacts);
    const selectedArtifact = directEmbeds.find((embed) => embed.id === landing.capability.id);
    const evidence_types = selectedArtifact ? [selectedArtifact.id, selectedArtifact.frontend_type, selectedArtifact.backend_type].filter(Boolean) : [];
    apps.push({ id, icon_image, order: landing.order, capability: landing.capability, caption: landing.caption, example_chat_id: landing.example_chat_id, evidence_types });
  }
  if (new Set(apps.map((app) => app.order)).size !== apps.length) throw new Error('Duplicate public landing app order');
  return apps.sort((a, b) => a.order - b.order);
}
