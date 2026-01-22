/**
 * Vite Plugin for Documentation Hot Reload
 * 
 * Watches the /docs directory for changes during development and
 * automatically regenerates the docs-data.json file.
 * 
 * Features:
 * - Watches markdown files in /docs directory recursively
 * - Debounces rapid changes
 * - Triggers HMR to update the browser
 */

import { spawn } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * Create the Vite plugin for docs processing
 * @returns {import('vite').Plugin}
 */
export function docsPlugin() {
    // Path to the docs processing script
    const processDocsScript = path.resolve(__dirname, 'process-docs.js');
    
    // Path to watch
    const docsDir = path.resolve(__dirname, '../../../../docs');
    
    // Debounce timer
    let debounceTimer = null;
    const DEBOUNCE_MS = 500;
    
    /**
     * Run the docs processing script
     */
    function processDocs() {
        return new Promise((resolve, reject) => {
            console.log('\n📚 [docs-plugin] Regenerating documentation...');
            
            const child = spawn('node', [processDocsScript], {
                stdio: 'inherit',
                cwd: path.resolve(__dirname, '..')
            });
            
            child.on('close', (code) => {
                if (code === 0) {
                    console.log('📚 [docs-plugin] Documentation updated\n');
                    resolve();
                } else {
                    console.error('📚 [docs-plugin] Failed to process documentation\n');
                    reject(new Error(`Process exited with code ${code}`));
                }
            });
            
            child.on('error', (err) => {
                console.error('📚 [docs-plugin] Error running process-docs.js:', err);
                reject(err);
            });
        });
    }
    
    /**
     * Debounced docs processing
     */
    function debouncedProcessDocs(server) {
        if (debounceTimer) {
            clearTimeout(debounceTimer);
        }
        
        debounceTimer = setTimeout(async () => {
            try {
                await processDocs();
                
                // Trigger HMR for the generated file
                const module = server.moduleGraph.getModulesByFile(
                    path.resolve(__dirname, '../src/lib/generated/docs-data.json')
                );
                
                if (module && module.size > 0) {
                    // Invalidate the module to trigger reload
                    for (const mod of module) {
                        server.moduleGraph.invalidateModule(mod);
                    }
                    
                    // Send full reload since JSON imports need full refresh
                    server.ws.send({
                        type: 'full-reload',
                        path: '*'
                    });
                }
            } catch (err) {
                console.error('📚 [docs-plugin] Error:', err);
            }
        }, DEBOUNCE_MS);
    }
    
    return {
        name: 'vite-plugin-docs',
        
        /**
         * Configure the server to watch docs directory
         */
        configureServer(server) {
            // Watch the docs directory
            server.watcher.add(docsDir);
            
            // Handle file changes
            server.watcher.on('change', (file) => {
                if (file.startsWith(docsDir) && file.endsWith('.md')) {
                    console.log(`📚 [docs-plugin] Detected change: ${path.relative(docsDir, file)}`);
                    debouncedProcessDocs(server);
                }
            });
            
            // Handle new files
            server.watcher.on('add', (file) => {
                if (file.startsWith(docsDir) && file.endsWith('.md')) {
                    console.log(`📚 [docs-plugin] Detected new file: ${path.relative(docsDir, file)}`);
                    debouncedProcessDocs(server);
                }
            });
            
            // Handle deleted files
            server.watcher.on('unlink', (file) => {
                if (file.startsWith(docsDir) && file.endsWith('.md')) {
                    console.log(`📚 [docs-plugin] Detected deleted file: ${path.relative(docsDir, file)}`);
                    debouncedProcessDocs(server);
                }
            });
        }
    };
}

export default docsPlugin;
