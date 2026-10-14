import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';

// Run inside the pinned CMS image with --network none. This imports Directus's
// shipped cache module, rather than a copy of its freeze/clone implementation.
const cachePath = '/directus/node_modules/@directus/api/dist/cache.js';
const vendorRequire = createRequire(fs.realpathSync(cachePath));
const { useEnv } = await import(vendorRequire.resolve('@directus/env'));
const { useCache: usePermissionCache } =
  await import('/directus/node_modules/@directus/api/dist/permissions/cache.js');
const { useBus } = await import('/directus/node_modules/@directus/api/dist/bus/index.js');
const bus = useBus(); // Local-only bus, established before enabling the subscriber.
const env = useEnv();
const priorRedisEnabled = env.REDIS_ENABLED;
env.REDIS_ENABLED = true; // Register cache.js's real schemaChanged subscriber.
env.CACHE_ENABLED = true; // Exercise the real administrative response-cache purge too.
const { clearSystemCache, flushCaches, getCache, getMemorySchemaCache, setMemorySchemaCache } =
  await import(cachePath);
assert.equal(bus.handlers.schemaChanged?.size, 1);
if (priorRedisEnabled === undefined) delete env.REDIS_ENABLED;
else env.REDIS_ENABLED = priorRedisEnabled;
const { getSchema } = await import('/directus/node_modules/@directus/api/dist/utils/get-schema.js');
const { validateAccess } = await import('/directus/node_modules/@directus/api/dist/permissions/modules/validate-access/validate-access.js');

const frozenMode = process.env.CACHE_SCHEMA_FREEZE_ENABLED === 'true';

test(`pinned Directus schema cache preserves reads and invalidates (${frozenMode ? 'frozen' : 'cloned'})`, async () => {
  const schema = {
    collections: {
      chats: {
        collection: 'chats',
        primary: 'id',
        fields: {
          id: { field: 'id', type: 'uuid' },
          owner: { field: 'owner', type: 'uuid' },
        },
      },
    },
    relations: [{ collection: 'chats', field: 'owner', related_collection: 'users' }],
  };
  setMemorySchemaCache(schema);
  try {
    const first = getMemorySchemaCache();
    const second = getMemorySchemaCache();
    const requestSchema = await getSchema();
    assert.equal(first.collections.chats.fields.owner.type, 'uuid');
    assert.equal(first.relations[0].related_collection, 'users');
    await validateAccess({ collection: 'chats', action: 'read', accountability: { admin: true } },
      { schema: requestSchema });

    if (frozenMode) {
      assert.strictEqual(first, second);
      assert.strictEqual(requestSchema, first);
      assert.ok(Object.isFrozen(first));
      assert.ok(Object.isFrozen(first.collections.chats.fields.owner));
      assert.ok(Object.isFrozen(first.relations));
      assert.ok(Object.isFrozen(first.relations[0]));
      assert.throws(() => { first.relations.push({}); }, TypeError);
      assert.throws(() => { first.collections.chats.fields.owner.type = 'unsafe'; }, TypeError);
    } else {
      assert.notStrictEqual(first, second);
      assert.notStrictEqual(requestSchema, first);
      first.collections.chats.fields.owner.type = 'request-local';
      assert.equal(getMemorySchemaCache().collections.chats.fields.owner.type, 'uuid');
    }

    const permissionCache = usePermissionCache();
    await permissionCache.set('schema-freeze-synthetic-permission', { allowed: true });
    assert.deepEqual(await permissionCache.get('schema-freeze-synthetic-permission'),
      { allowed: true });
    await clearSystemCache({ forced: true });
    assert.equal(getMemorySchemaCache(), undefined);
    assert.equal(await permissionCache.get('schema-freeze-synthetic-permission'), undefined);
    setMemorySchemaCache({ collections: {}, relations: [] });
    await assert.rejects(
      validateAccess(
        { collection: 'chats', action: 'read', accountability: { admin: true } },
        { schema: await getSchema() },
      ),
      (error) => error?.status === 403,
    );

    // Administrative cache purge follows the vendor's response/system/permission path.
    setMemorySchemaCache(schema);
    await getCache().cache.set('schema-freeze-synthetic-response', { body: 'synthetic' });
    await permissionCache.set('schema-freeze-synthetic-permission', { allowed: true });
    await flushCaches(true);
    assert.equal(getMemorySchemaCache(), undefined);
    assert.equal(await getCache().cache.get('schema-freeze-synthetic-response'), undefined);
    assert.equal(await permissionCache.get('schema-freeze-synthetic-permission'), undefined);

    setMemorySchemaCache(schema);
    await bus.publish('schemaChanged', { autoPurgeCache: false });
    for (let attempt = 0; attempt < 20 && getMemorySchemaCache() !== undefined; attempt++) {
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
    assert.equal(getMemorySchemaCache(), undefined);
  } finally {
    await clearSystemCache({ forced: true });
  }
});

// Source-bound check only: live database schema application belongs to the
// coordinator's isolated integration checks, never to this no-network probe.
test('pinned schema snapshot and mutation utilities explicitly bypass cached schema', () => {
  for (const utility of ['get-snapshot', 'apply-snapshot', 'apply-diff']) {
    const source = fs.readFileSync(
      `/directus/node_modules/@directus/api/dist/utils/${utility}.js`, 'utf8');
    assert.ok(source.includes('getSchema({ database, bypassCache: true })'), utility);
  }
});
