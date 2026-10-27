/**
 * Public share metadata without native content decoding on an unpatched host.
 * node:https exposes raw response bytes; fetch can decode before header checks.
 * See docs/plans/web-brotli-runtime-protection/plan.yml and publicMetadataFetch.test.mjs.
 */
import { request as httpsRequest } from 'node:https';
import { isWebNodeRuntimePatched } from './webNodeRuntimeSecurity.mjs';

const ORIGINS = new Set(['https://api.dev.openmates.org', 'https://api.openmates.org']);
const METADATA_PATH = /^\/v1\/share\/(?:(?:chat|embed)\/[A-Za-z0-9_-]{1,256}\/og-metadata|short-url\/[A-Za-z0-9]{6,12}\/metadata)$/;

/** Dependencies are injectable for raw HTTP fixture tests, never from a request. */
export function createPublicMetadataFetch({ request = httpsRequest, isPatched = isWebNodeRuntimePatched, maxBytes = 1024 * 1024, timeoutMs = 8000 } = {}) {
  return async function publicMetadataFetch(input, fetch, { signal } = {}) {
    if (isPatched()) return fetch(input, { cache: 'no-store', signal });

    const url = new URL(input);
    if (!ORIGINS.has(url.origin) || url.username || url.password || url.hash ||
        !METADATA_PATH.test(url.pathname) || [...url.searchParams].some(([key, value]) => key !== 't' || !/^\d+$/.test(value))) {
      throw new Error('Unpatched runtime permits only first-party public share metadata');
    }

    return new Promise((resolve, reject) => {
      let client;
      let upstream;
      let settled = false;
      const finish = (error, response) => {
        if (settled) return;
        settled = true;
        clearTimeout(deadline);
        if (error) reject(error);
        else resolve(response);
        upstream?.destroy();
        client?.destroy();
      };
      const fail = (message) => finish(new Error(message));
      const deadline = setTimeout(() => fail('Public metadata deadline exceeded'), timeoutMs);
      deadline.unref();
      try {
        client = request(url, {
          method: 'GET', agent: false, signal,
          headers: { accept: 'application/json', 'accept-encoding': 'identity' }
        }, (response) => {
          upstream = response;
          response.on('error', () => fail('Public metadata response failed'));
          response.on('aborted', () => fail('Public metadata response was interrupted'));
          const encoding = String(response.headers['content-encoding'] ?? '').trim().toLowerCase();
          // Check before attaching a body consumer. Never instantiate a decoder,
          // including when an upstream ignores our identity negotiation.
          if (encoding && encoding !== 'identity') return fail('Encoded public metadata is not permitted');
          const status = response.statusCode;
          if (!status || status < 200 || status > 599) return fail('Invalid public metadata status');
          if (status >= 300 && status < 400) return fail('Public metadata redirects are not permitted');
          if (status >= 400 || status === 204 || status === 205) return finish(null, new Response(null, { status }));
          const contentType = response.headers['content-type'] ?? '';
          if (!/^application\/(?:[a-z0-9.+-]+\+)?json(?:\s*;|$)/i.test(contentType)) return fail('Public metadata must be JSON');
          const declaredSize = response.headers['content-length'];
          if (declaredSize !== undefined && (!/^\d+$/.test(declaredSize) || Number(declaredSize) > maxBytes)) return fail('Public metadata exceeds its size limit');
          const chunks = [];
          let bytes = 0;
          response.on('data', (chunk) => {
            bytes += chunk.length;
            if (bytes > maxBytes) return fail('Public metadata exceeds its size limit');
            chunks.push(chunk);
          });
          response.on('end', () => {
            if (settled) return;
            finish(null, new Response(Buffer.concat(chunks), { status, headers: { 'content-type': contentType } }));
          });
        });
        client.on('error', () => fail('Public metadata request failed'));
        client.end();
      } catch {
        fail('Public metadata request failed');
      }
    });
  };
}

export const fetchPublicMetadata = createPublicMetadataFetch();
