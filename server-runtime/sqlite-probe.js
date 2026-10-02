'use strict';

// Normal allocation-driven GC exercises Statement's native ObjectWrap
// destructor. Explicit global.gc() does not reproduce Node issue #65446.
const assert = require('node:assert/strict');
const Database = require('/opt/evejs/server/node_modules/better-sqlite3');
assert.equal(process.arch, 'arm64', 'SQLite qualification requires native ARM64');
const db = new Database(':memory:');
assert.equal(db.prepare('SELECT 42 AS value').get().value, 42);
const statementCount = 300000;
let allocations = [];
for (let i = 0; i < statementCount; i++) {
  const statement = db.prepare('SELECT ? AS value');
  if (i % 10000 === 0) assert.equal(statement.get(i).value, i);
  allocations.push({ value: i, padding: 'allocation-driven-sqlite-collection' });
  if (allocations.length > 1000) allocations = [];
}
assert.equal(db.prepare('PRAGMA integrity_check').get().integrity_check, 'ok');
db.close();
console.log(JSON.stringify({ node: process.version, architecture: process.arch,
  nativeSqlite: true, allocationDrivenGc: true, statementCount }));
