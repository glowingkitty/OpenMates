// In-memory transactional harness matching the existing recovery test boundary.
export function fakeDatabase(seed, injectedFailure = null) {
  const rows = structuredClone(seed);
  let transactions = 0;
  let transactionTail = Promise.resolve();
  const failureCounts = new Map();
  const compare = (left, operator, right) => {
    const a = left instanceof Date ? left.getTime() : left;
    const b = right instanceof Date ? right.getTime() : right;
    if (operator === '>') return a > b;
    if (operator === '>=') return a >= b;
    if (operator === '<') return a < b;
    if (operator === '<=') return a <= b;
    return a === b;
  };
  const maybeFail = (operation, table) => {
    const key = `${operation}:${table}`;
    const count = (failureCounts.get(key) ?? 0) + 1;
    failureCounts.set(key, count);
    if (injectedFailure?.operation === operation && injectedFailure.table === table
      && (injectedFailure.occurrence ?? 1) === count) throw new Error(`injected ${key} failure`);
  };
  const makeClient = (store) => {
    const client = (table) => {
      const predicates = [];
      const orders = [];
      let limitCount = Infinity;
      const matching = () => (store[table] ?? [])
        .filter((row) => predicates.every((predicate) => predicate(row)))
        .sort((left, right) => {
          for (const [field, direction] of orders) {
            if (left[field] === right[field]) continue;
            return (left[field] < right[field] ? -1 : 1) * (direction === 'desc' ? -1 : 1);
          }
          return 0;
        })
        .slice(0, limitCount);
      const addWhere = (args) => {
        if (typeof args[0] === 'object') {
          predicates.push((row) => Object.entries(args[0]).every(([key, value]) => compare(row[key], '=', value)));
        } else {
          const [field, operator, value] = args.length === 2 ? [args[0], '=', args[1]] : args;
          predicates.push((row) => compare(row[field], operator, value));
        }
      };
      const query = {
        where(...args) { addWhere(args); return query; },
        andWhere(...args) { addWhere(args); return query; },
        whereNull(field) { predicates.push((row) => row[field] == null); return query; },
        whereNotNull(field) { predicates.push((row) => row[field] != null); return query; },
        whereIn(field, values) { predicates.push((row) => values.includes(row[field])); return query; },
        whereNotIn(field, values) { predicates.push((row) => !values.includes(row[field])); return query; },
        forUpdate() { return query; },
        orderBy(field, direction = 'asc') { orders.push([field, direction]); return query; },
        limit(value) { limitCount = value; return query; },
        async first() { return matching()[0]; },
        async select(fields) {
          return matching().map((row) => Object.fromEntries(fields.map((field) => [field, row[field]])));
        },
        async pluck(field) { return matching().map((row) => row[field]); },
        async insert(value) {
          maybeFail('insert', table);
          store[table] ??= [];
          for (const row of Array.isArray(value) ? value : [value]) {
            const stored = structuredClone(row);
            if (table === 'chat_recovery_protocol_state') {
              for (const field of ['active_legacy_tasks', 'legacy_task_lifecycle']) {
                if (typeof stored[field] === 'string') stored[field] = JSON.parse(stored[field]);
              }
            }
            store[table].push(stored);
          }
          return 1;
        },
        async update(values) {
          maybeFail('update', table);
          const found = matching();
          for (const row of found) {
            for (const [field, value] of Object.entries(values)) {
              if (table === 'chat_recovery_protocol_state'
                && ['active_legacy_tasks', 'legacy_task_lifecycle'].includes(field)
                && typeof value === 'string') {
                row[field] = JSON.parse(value);
              } else {
                row[field] = value?.rawExpression === `${field} + 1` ? row[field] + 1 : structuredClone(value);
              }
            }
          }
          return found.length;
        },
        async delete() {
          maybeFail('delete', table);
          const found = new Set(matching());
          store[table] = (store[table] ?? []).filter((row) => !found.has(row));
          return found.size;
        },
      };
      return query;
    };
    client.raw = (value) => typeof value === 'string' && /\w+ \+ 1/.test(value) ? { rawExpression: value } : value;
    return client;
  };
  const database = makeClient(rows);
  database.rows = rows;
  Object.defineProperty(database, 'transactions', { get: () => transactions });
  database.transaction = async (callback) => {
    const run = transactionTail.then(async () => {
      transactions += 1;
      const working = structuredClone(rows);
      const result = await callback(makeClient(working));
      for (const key of new Set([...Object.keys(rows), ...Object.keys(working)])) rows[key] = working[key] ?? [];
      return result;
    });
    transactionTail = run.catch(() => undefined);
    return run;
  };
  return database;
}
