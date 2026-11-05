/** TypeScript compiler inventory: reads source, never imports product runtime. */
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, resolve, join } from 'node:path';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const require = createRequire(join(root, 'frontend/packages/openmates-cli/package.json'));
const ts = require('typescript');
const sourceArgument = process.argv.indexOf('--source-dir');
const base = sourceArgument < 0 ? join(root, 'frontend/packages/openmates-cli/src') : resolve(process.argv[sourceArgument + 1]);
const entries = ['index.ts', 'sdk-entry.ts', 'sdk-session-v1-entry.ts'].map(name => join(base, name));
const program = ts.createProgram(entries, { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler, skipLibCheck: true });
const checker = program.getTypeChecker(), symbols = new Set();
const resolveAlias = symbol => symbol.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(symbol) : symbol;
const isPrivate = node => ts.getCombinedModifierFlags(node) & (ts.ModifierFlags.Private | ts.ModifierFlags.Protected);
const owned = node => node.getSourceFile().fileName.startsWith(base + '/');
function runtimeExport(symbol) {
  if (symbol.declarations?.some(node => ts.isExportSpecifier(node) && (node.isTypeOnly || node.parent.parent.isTypeOnly))) return false;
  return Boolean(resolveAlias(symbol).flags & ts.SymbolFlags.Value);
}
function members(type, prefix, ancestors = new Set(), recursive = false) {
  if (ancestors.has(type)) return;
  const next = new Set([...ancestors, type]);
  for (const property of type.getProperties()) {
    const name = property.getName();
    if (name.startsWith('_') || name === 'constructor') continue;
    const declaration = property.valueDeclaration ?? property.declarations?.[0];
    if (!declaration || !owned(declaration) || isPrivate(declaration) || ts.isPrivateIdentifier(declaration.name)) continue;
    const path = `${prefix}.${name}`, child = checker.getTypeOfSymbolAtLocation(property, declaration);
    symbols.add(path);
    // Expand namespace object literals, aliases/intersections and public class
    // fields using compiler types, so adding a method behind an existing field
    // cannot evade inventory drift checks. Never descend into library primitives.
    if (recursive && child.getCallSignatures().length === 0) members(checker.getNonNullableType(child), path, next, true);
  }
}
for (const filename of entries) {
  const source = program.getSourceFile(filename), module = source && checker.getSymbolAtLocation(source);
  if (!module) throw new Error('SDK public entrypoint is not a module');
  for (const exported of checker.getExportsOfModule(module)) {
    if (!runtimeExport(exported)) continue;
    const name = exported.getName(), symbol = resolveAlias(exported);
    symbols.add(name);
    if (symbol.flags & ts.SymbolFlags.Class) {
      members(checker.getDeclaredTypeOfSymbol(symbol), name, new Set(), true);
      const declaration = symbol.valueDeclaration ?? symbol.declarations?.[0];
      if (declaration) members(checker.getTypeOfSymbolAtLocation(symbol, declaration), name, new Set(), true);
    } else {
      const declaration = symbol.valueDeclaration ?? symbol.declarations?.[0];
      if (declaration && owned(declaration)) members(checker.getTypeOfSymbolAtLocation(symbol, declaration), name, new Set(), true);
    }
  }
}
process.stdout.write(JSON.stringify({ npm: [...symbols].sort(), rules: { excluded: ['Type-only exports/interfaces', 'private/protected members', 'underscore-prefixed implementation helpers', 'external primitive/library members', 'constructors represented by their exported class'], includes: ['recursive public barrel value exports and aliases', 'exported class public methods/getters/fields', 'facade fields including imported classes, type aliases, intersections, object literal functions'] } }) + '\n');
