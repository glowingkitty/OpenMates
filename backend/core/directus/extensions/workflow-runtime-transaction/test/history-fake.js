export function fakeDatabase(seed) {
  const rows = structuredClone(seed);
  let tail = Promise.resolve();
  const client = (store) => (table) => {
    const predicates = [];
    const orderings = [];
    let rowLimit = null;
    const match = () => {
      let rows = (store[table] ?? []).filter((row) => predicates.every((predicate) => predicate(row)));
      for (const { field, direction } of orderings.slice().reverse()) {
        rows = rows.slice().sort((left, right) => {
          if (left[field] === right[field]) return 0;
          const comparison = left[field] < right[field] ? -1 : 1;
          return direction === 'desc' ? -comparison : comparison;
        });
      }
      return rowLimit === null ? rows : rows.slice(0, rowLimit);
    };
    const addWhere = (args) => {
      if (typeof args[0] === 'object') {
        const values = args[0];
        predicates.push((row) => Object.entries(values).every(([key, value]) => row[key] === value));
        return;
      }
      if (args.length === 3) {
        const [field, op, value] = args;
        predicates.push((row) => {
          if (row[field] == null && ['<=','<','>=','>'].includes(op)) return false;
          if (op === '<=') return row[field] <= value;
          if (op === '<') return row[field] < value;
          if (op === '>=') return row[field] >= value;
          if (op === '>') return row[field] > value;
          return row[field] === value;
        });
        return;
      }
      const [field, value] = args;
      predicates.push((row) => row[field] === value);
    };
    const query = {
      where(...args) { addWhere(args); return query; },
      whereIn(field, values) { predicates.push((row) => Array.isArray(values) && values.includes(row[field])); return query; },
      forUpdate() { return query; },
      select() { return query; },
      async del() { const removed = match(); store[table] = (store[table] || []).filter(row => !removed.includes(row)); return removed.length; },
      async first() { return match()[0]; },
      async insert(value) { (store[table] ??= []).push(structuredClone(value)); return 1; },
      async update(values) { const found = match(); found.forEach((row) => Object.assign(row, structuredClone(values))); return found.length; },
      orderBy(field, direction = 'asc') { orderings.push({ field, direction }); return query; },
      limit(value) { rowLimit = value; return query; },
      then(resolve, reject) { return Promise.resolve(match()).then(resolve, reject); },
    };
    return query;
  };
  const database = client(rows);
  database.rows = rows;
  database.transaction = async (callback) => {
    const run = tail.then(async () => {
      const working = structuredClone(rows);
      const result = await callback(client(working));
      for (const key of new Set([...Object.keys(rows), ...Object.keys(working)])) rows[key] = working[key] ?? [];
      return result;
    });
    tail = run.catch(() => undefined);
    return run;
  };
  return database;
}
