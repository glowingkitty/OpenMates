/** A fresh account's empty device list is the default bare-preview state. */
if (new URLSearchParams(window.location.search).get('testApi') !== '1') {
  const fetchFromPreview = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, window.location.href);
    if (url.pathname === '/v1/settings/api-key-devices' && (!init?.method || init.method === 'GET')) {
      return Promise.resolve(new Response(JSON.stringify({ devices: [] }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      }));
    }
    return fetchFromPreview(input, init);
  };
}
export default {};
