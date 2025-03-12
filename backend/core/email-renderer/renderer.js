import { render } from '@react-email/render';
import path from 'path';
import fs from 'fs';
import * as svelteCompiler from 'svelte/compiler';
import { fileURLToPath } from 'url';
import { dirname } from 'path';
import { getTranslation } from './translations-loader.js';

// Get current file's directory path (__dirname equivalent for ES modules)
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Path to templates directory
const TEMPLATES_DIR = path.join(__dirname, 'templates');

/**
 * Renders a Svelte email template with the provided data
 * 
 * @param {string} templateName - Name of the template file without extension
 * @param {object} data - Data to pass to the template
 * @returns {Promise<string>} - Rendered HTML email
 */
async function renderEmail(templateName, data = {}) {
  try {
    // Check if template exists
    const templatePath = path.join(TEMPLATES_DIR, `${templateName}.svelte`);
    if (!fs.existsSync(templatePath)) {
      throw new Error(`Template ${templateName} not found at ${templatePath}`);
    }

    // Read the template file
    const templateCode = fs.readFileSync(templatePath, 'utf8');
    
    // Create a translate function based on provided language
    const lang = data.lang || 'en';
    
    // Add the translate function to the template data
    const enhancedData = {
      ...data,
      // Add a t() function that templates can use for translation
      t: (key, vars = {}) => getTranslation(key, lang, vars)
    };
    
    // Compile Svelte component to JavaScript
    const { js } = svelteCompiler.compile(templateCode, {
      filename: templatePath,
      generate: 'ssr',
      hydratable: true,
      css: 'external'
    });
    
    // Create temporary file for the compiled component
    const tempDir = path.join(__dirname, 'temp');
    if (!fs.existsSync(tempDir)) {
      fs.mkdirSync(tempDir, { recursive: true });
    }
    
    const tempFilePath = path.join(tempDir, `${templateName}.js`);
    fs.writeFileSync(tempFilePath, js.code);
    
    // Import the compiled component (dynamically)
    const modulePath = `file://${tempFilePath}`;
    const EmailComponent = (await import(modulePath)).default;
    
    // Render the component to HTML
    const { html } = EmailComponent.render(enhancedData);
    
    // Using react-email's render without wrapping component output
    // This avoids double-wrapping the HTML
    const renderedHtml = html;
    
    // Clean up the temporary file
    fs.unlinkSync(tempFilePath);
    
    return renderedHtml;
  } catch (error) {
    console.error(`Error rendering email template "${templateName}":`, error);
    throw error;
  }
}

export { renderEmail };
