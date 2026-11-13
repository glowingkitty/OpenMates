// Node loader for the npm CLI TypeScript sources: `.js` → `.ts` siblings and
// bare packages from OPENMATES_CLI_NODE_MODULES (the installed npm CLI deps).
import { existsSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
export async function resolve(specifier, context, next) {
  if (specifier.endsWith(".js") && context.parentURL && /^\.\.?\//.test(specifier)) {
    const url = new URL(specifier.replace(/\.js$/, ".ts"), context.parentURL);
    if (existsSync(fileURLToPath(url))) return next(url.href, context);
  }
  if (!/^(node:|\.|\/|file:)/.test(specifier) && process.env.OPENMATES_CLI_NODE_MODULES) {
    try { return await next(specifier, context); }
    catch { return next(specifier, { ...context, parentURL: pathToFileURL(process.env.OPENMATES_CLI_NODE_MODULES + "/x.js").href }); }
  }
  return next(specifier, context);
}
