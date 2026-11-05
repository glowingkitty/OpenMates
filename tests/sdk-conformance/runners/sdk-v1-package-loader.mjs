/** Packaging-only selection. The default maintained adapter remains unchanged.
 * Closed CI mode imports the real published subpath from an extracted package;
 * no source transpiler, CLI launcher, arbitrary adapter or missing-native skip.
 */
import {readFileSync,realpathSync,lstatSync} from 'node:fs';
import path from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
export const CONSUMER_SOURCE = "export {RustApiKeyClient} from 'openmates/sdk/v1';\nexport const resolvedEntrypoint = import.meta.resolve('openmates/sdk/v1');\n";
export async function loadApiKeyConformanceSdk() {
  const consumer=process.env.OPENMATES_SDK_V1_PACKAGE_CONSUMER;
  if(consumer===undefined)return import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js');
  for(const [key,value]of Object.entries({CI:'true',GITHUB_ACTIONS:'true',OPENMATES_CI_ISOLATED:'1'}))if(process.env[key]!==value)throw Error('packaged_sdk_requires_isolated_ci');
  if(!path.isAbsolute(consumer)||realpathSync(consumer)!==consumer)throw Error('invalid_packaged_consumer');
  const packageRoot=path.join(consumer,'node_modules/openmates'),entry=path.join(packageRoot,'dist/sdk-session-v1-entry.js');
  if(realpathSync(packageRoot)!==packageRoot||realpathSync(entry)!==entry||!lstatSync(entry).isFile())throw Error('invalid_packaged_entry');
  const manifest=JSON.parse(readFileSync(path.join(packageRoot,'package.json'),'utf8'));
  if(manifest.name!=='openmates'||manifest.exports?.['./sdk/v1']?.default!=='./dist/sdk-session-v1-entry.js')throw Error('invalid_versioned_package_export');
  const source=path.join(consumer,'consume.mjs');
  if(realpathSync(source)!==source||readFileSync(source,'utf8')!==CONSUMER_SOURCE)throw Error('invalid_packaged_consumer_module');
  const sdk=await import(pathToFileURL(source).href);
  if(fileURLToPath(sdk.resolvedEntrypoint)!==entry||typeof sdk.RustApiKeyClient!=='function')throw Error('versioned_package_resolution_failed');
  return sdk;
}
