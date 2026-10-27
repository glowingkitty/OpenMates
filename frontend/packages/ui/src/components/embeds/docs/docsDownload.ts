/** Shared DOCX export. Canonical encrypted artifacts take precedence over HTML. */
import { fetchAndDecryptDocArtifact } from './docsArtifactCrypto';
import { sanitizeDocumentHtml } from './docsEmbedContent';
import { restorePIIInText, replacePIIOriginalsWithPlaceholders } from '../../enter_message/services/piiDetectionService';
import { replaceEmbedRefsWithUrlsInHtml } from '../../../utils/embedLinkUtils';
import type { PIIMapping } from '../../../types/chat';

const DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
const DOWNLOAD_URL_REVOKE_DELAY_MS = 60_000;
export interface DocsDownloadOptions {
  filename?: string;
  title?: string;
  htmlContent: string;
  piiMappings?: PIIMapping[];
  piiRevealed?: boolean;
  docxS3Key?: string;
  aesKey?: string;
  preparedUrl?: string | null;
  preparedPromise?: Promise<Blob> | null;
}
export type PreparedDocsDownload = { filename: string } & ({ url: string } | { blob: Blob });

export function docsDownloadFilename(filename?: string): string {
  return (filename || 'document').replace(/\.docx$/i, '') + '.docx';
}
export function fetchDocxDownloadArtifact(s3Key: string, aesKey: string): Promise<Blob> {
  return fetchAndDecryptDocArtifact(s3Key, aesKey, DOCX_MIME);
}

export async function prepareDocsDownload(options: DocsDownloadOptions): Promise<PreparedDocsDownload> {
  const filename = docsDownloadFilename(options.filename);
  if (options.docxS3Key && options.aesKey) {
    if (options.preparedUrl) return { filename, url: options.preparedUrl };
    return { filename, blob: await (options.preparedPromise ?? fetchDocxDownloadArtifact(options.docxS3Key, options.aesKey)) };
  }
  const mappings = options.piiMappings ?? [];
  const processPII = (value: string) => options.piiRevealed
    ? restorePIIInText(value, mappings)
    : replacePIIOriginalsWithPlaceholders(value, mappings);
  let downloadHtmlContent = sanitizeDocumentHtml(processPII(options.htmlContent));
  downloadHtmlContent = await replaceEmbedRefsWithUrlsInHtml(downloadHtmlContent);
  const escapedTitle = processPII(options.title || 'Document').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character] ?? character);
  const fullHtml = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>${escapedTitle}</title>
  <style>
    body { font-family: Calibri, Arial, sans-serif; font-size: 11pt; line-height: 1.6; color: #333; }
    h1 { font-size: 20pt; margin-bottom: 0.5em; }
    h2 { font-size: 16pt; margin-top: 1.5em; }
    h3 { font-size: 13pt; margin-top: 1.2em; }
    p { margin: 0.5em 0; }
    ul, ol { padding-left: 2em; }
    blockquote { border-left: 3px solid #ccc; margin: 1em 0; padding: 0.5em 1em; color: var(--color-grey-70); }
    table { border-collapse: collapse; width: 100%; margin: 1em 0; }
    th, td { border: 1px solid #999; padding: var(--spacing-3) var(--spacing-5); text-align: left; }
    th { background: #f0f0f0; font-weight: bold; }
    code { font-family: 'Courier New', monospace; background: #f5f5f5; padding: var(--spacing-1) var(--spacing-2); font-size: 10pt; }
    pre { background: #f5f5f5; padding: var(--spacing-6); font-family: 'Courier New', monospace; font-size: 10pt; white-space: pre-wrap; }
    a { color: #0563C1; }
    img { max-width: 100%; }
  </style>
</head>
<body>
${downloadHtmlContent}
</body>
</html>`;
  const { asBlob } = await import('html-docx-js-typescript');
  const blob = await asBlob(fullHtml, { margins: { top: 1440, right: 1440, bottom: 1440, left: 1440 } }) as Blob;
  return { filename, blob };
}

/** Prepared URLs belong to their component; new Blob URLs live through browser download startup. */
export function triggerDocsDownload(download: PreparedDocsDownload): void {
  const url = 'url' in download ? download.url : URL.createObjectURL(download.blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = download.filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  if (!('url' in download)) window.setTimeout(() => URL.revokeObjectURL(url), DOWNLOAD_URL_REVOKE_DELAY_MS);
}
