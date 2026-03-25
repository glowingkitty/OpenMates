// Custom ESM loader that rewrites .js → .ts imports within the src/ directory.
// Used by the Node.js test runner with --experimental-strip-types to resolve
// cross-module TypeScript imports that use .js extensions (for tsup compatibility).

export function resolve(specifier, context, nextResolve) {
  // Only rewrite relative .js imports within the CLI package
  if (specifier.endsWith('.js') && (specifier.startsWith('./') || specifier.startsWith('../'))) {
    const tsSpecifier = specifier.replace(/\.js$/, '.ts');
    return nextResolve(tsSpecifier, context);
  }
  return nextResolve(specifier, context);
}
