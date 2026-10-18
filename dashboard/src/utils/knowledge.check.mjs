import assert from 'node:assert/strict';
import { unverifiedIds, gapItems, updateAchievement, removeAt, moveItem } from './knowledge.js';

const src = { roles: [{ company: 'Acme', achievements: [
  { id: 'AC-01', text: 'Cut churn 18%', needs_metric: false, unverified: true },
  { id: 'AC-02', text: 'Led migration', needs_metric: true, unverified: false },
] }] };
assert.deepEqual(unverifiedIds(src), ['AC-01']);
assert.deepEqual(gapItems(src), [{ id: 'AC-02', company: 'Acme', text: 'Led migration' }]);
const next = updateAchievement(src, 'AC-01', { unverified: false });
assert.equal(next.roles[0].achievements[0].unverified, false);
assert.equal(src.roles[0].achievements[0].unverified, true);
assert.deepEqual(removeAt([1, 2, 3], 1), [1, 3]);
assert.deepEqual(moveItem(['a', 'b', 'c'], 2, 0), ['c', 'a', 'b']);
console.log('knowledge.check ok');
