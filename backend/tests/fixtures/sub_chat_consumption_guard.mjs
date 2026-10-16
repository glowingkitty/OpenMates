// Test-only in-memory database adapter. Authorization is the real recovery operation.
import fs from 'node:fs';
import { executeOperation } from '../../core/directus/extensions/chat-recovery-transaction/src/operations.js';

const { seed, payload } = JSON.parse(fs.readFileSync(0, 'utf8'));
function databaseFor(rows) {
  const db = (table) => {
    const predicates = [];
    const matching = () => (rows[table] || []).filter((row) => predicates.every((p) => p(row)));
    const query = {
      where(scope) { predicates.push((row) => Object.entries(scope).every(([k, v]) => row[k] === v)); return query; },
      forUpdate() { return query; },
      async first() { return matching()[0]; },
      async update(value) { const found = matching(); for (const row of found) Object.assign(row, value); return found.length; },
    };
    return query;
  };
  db.raw = async () => undefined;
  db.transaction = async (callback) => {
    const pending = structuredClone(rows);
    const result = await callback(databaseFor(pending));
    Object.assign(rows, pending);
    return result;
  };
  return db;
}
try {
  const result = await executeOperation(databaseFor(seed), 'mark_child_parent_consumed', payload);
  process.stdout.write(JSON.stringify({ result, seed }));
} catch (error) {
  process.stdout.write(JSON.stringify({ error: error.code || error.message, seed }));
}
