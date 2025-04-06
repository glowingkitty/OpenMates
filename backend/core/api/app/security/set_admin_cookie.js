// == START: Cookie Setting Script ==

// 1. --- REPLACE THIS VALUE ---
const adminKeyValue = 'YOUR_ADMIN_ACCESS_KEY_HERE';
// -----------------------------

const cookieName = 'admin_access_token';
const path = '/';
const maxAgeSeconds = 86400; // Expires in 1 day

// Set the cookie for the current domain context
// Ensure you run this from a page on *.dev.openmates.org
document.cookie = `${cookieName}=${encodeURIComponent(adminKeyValue)}; path=${path}; max-age=${maxAgeSeconds}; SameSite=Lax; Secure`;

console.log(`Cookie '${cookieName}' attempted to be set. Check developer tools (Application/Storage tab) to verify. You might need to refresh the page.`);

// == END: Cookie Setting Script ==