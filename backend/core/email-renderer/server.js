import express from 'express';
import { renderEmail } from './renderer.js';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { dirname } from 'path';
import { getAvailableLanguages } from './translations-loader.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const app = express();
const port = 3030;

// Middleware for parsing query parameters
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ status: 'healthy' });
});

// Email rendering endpoint
app.get('/v1/:templateName', async (req, res) => {
  try {
    const { templateName } = req.params;
    const templateData = req.query;
    
    console.log(`Rendering template: ${templateName} with data:`, templateData);
    
    // Convert darkmode string to boolean if present
    if (templateData.darkMode !== undefined) {
      templateData.darkMode = templateData.darkMode === 'true';
    }
    
    const html = await renderEmail(templateName, templateData);
    
    if (!html) {
      console.error(`Template ${templateName} not found`);
      return res.status(404).json({ error: `Template ${templateName} not found` });
    }
    
    // Set appropriate content type for email HTML
    res.setHeader('Content-Type', 'text/html');
    
    // Send the raw HTML without any additional processing
    res.send(html);
  } catch (error) {
    console.error('Error rendering email:', error);
    res.status(500).json({ error: error.message });
  }
});

// Add a preview endpoint that wraps the email in a nice viewing UI
app.get('/preview/:templateName', async (req, res) => {
  try {
    const { templateName } = req.params;
    const templateData = req.query;
    
    // Convert darkmode string to boolean if present
    if (templateData.darkMode !== undefined) {
      templateData.darkMode = templateData.darkMode === 'true';
    }
    
    const html = await renderEmail(templateName, templateData);
    
    if (!html) {
      return res.status(404).json({ error: `Template ${templateName} not found` });
    }
    
    // Create a preview page that displays the email in an iframe
    const previewHtml = `
      <!DOCTYPE html>
      <html>
        <head>
          <meta charset="utf-8">
          <title>Email Preview: ${templateName}</title>
          <style>
            body {
              font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
              margin: 0;
              padding: 20px;
              background-color: #f5f5f5;
            }
            .container {
              max-width: 1200px;
              margin: 0 auto;
            }
            .header {
              margin-bottom: 20px;
              padding-bottom: 20px;
              border-bottom: 1px solid #eaeaea;
            }
            .controls {
              display: flex;
              gap: 10px;
              margin-bottom: 20px;
            }
            .email-container {
              background-color: white;
              border-radius: 8px;
              box-shadow: 0 2px 8px rgba(0,0,0,0.1);
              padding: 20px;
              overflow: auto;
            }
            iframe {
              width: 100%;
              height: 700px;
              border: none;
            }
          </style>
        </head>
        <body>
          <div class="container">
            <div class="header">
              <h1>Email Preview: ${templateName}</h1>
              <p>This is how your email will appear to recipients.</p>
            </div>
            <div class="controls">
              <a href="/v1/${templateName}?${new URLSearchParams(req.query).toString()}" target="_blank">View Raw HTML</a>
            </div>
            <div class="email-container">
              <iframe srcdoc="${html.replace(/"/g, '&quot;')}"></iframe>
            </div>
          </div>
        </body>
      </html>
    `;
    
    res.setHeader('Content-Type', 'text/html');
    res.send(previewHtml);
  } catch (error) {
    console.error('Error rendering preview:', error);
    res.status(500).json({ error: error.message });
  }
});

// List available templates
app.get('/templates', (req, res) => {
  try {
    const templatesDir = path.join(__dirname, 'templates');
    
    const templates = fs.readdirSync(templatesDir)
      .filter(file => file.endsWith('.svelte'))
      .map(file => file.replace('.svelte', ''));
    
    // Get available languages
    const languages = getAvailableLanguages();
    
    res.json({ 
      templates,
      languages
    });
  } catch (error) {
    console.error('Error listing templates:', error);
    res.status(500).json({ error: error.message });
  }
});

app.listen(port, () => {
  console.log(`Email renderer listening on port ${port}`);
});
