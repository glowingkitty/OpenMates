// Custom ESM loader that rewrites .js → .ts imports within the src/ directory.
// Used by the Node.js test runner with --experimental-strip-types to resolve
// cross-module TypeScript imports that use .js extensions (for tsup compatibility).

export async function resolve(specifier, context, nextResolve) {
  const parentUrl = context.parentURL ?? '';
  const parentPath = parentUrl.split(/[?#]/, 1)[0];
  const isWorkspaceTypeScriptParent =
    parentPath.includes('/frontend/packages/') &&
    !parentPath.includes('/node_modules/') &&
    !parentPath.includes('/dist/') &&
    /\.tsx?$/.test(parentPath);

  if (!isWorkspaceTypeScriptParent) {
    return nextResolve(specifier, context);
  }

  // Only rewrite relative .js imports within the CLI package
  if (specifier.endsWith('.js') && (specifier.startsWith('./') || specifier.startsWith('../'))) {
    // Tests can import built CLI output alongside source modules. Keep dist
    // imports pointed at the built JavaScript instead of a nonexistent .ts file.
    if (new URL(specifier, parentUrl).pathname.includes('/dist/')) {
      return nextResolve(specifier, context);
    }
    const tsSpecifier = specifier.replace(/\.js$/, '.ts');
    return nextResolve(tsSpecifier, context);
  }
  if ((specifier.startsWith('./') || specifier.startsWith('../')) && !specifier.match(/\.[a-z0-9]+$/i)) {
    try {
      return await nextResolve(specifier, context);
    } catch (error) {
      return nextResolve(`${specifier}.ts`, context);
    }
  }
  return nextResolve(specifier, context);
}
