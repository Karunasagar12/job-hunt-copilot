import assert from 'node:assert/strict';
import { regionLabel, regionOptions } from './regions.js';

const regions = [{ id: 'eu', label: 'Europe' }, { id: 'gcc', label: 'Gulf' }];
assert.equal(regionLabel(regions, 'eu'), 'Europe');
assert.equal(regionLabel(regions, 'india'), 'INDIA');
assert.equal(regionLabel(regions, ''), '—');
assert.deepEqual(regionOptions(regions, { includeAuto: true }).map(option => option.value), ['auto', 'eu', 'gcc']);
assert.deepEqual(regionOptions([], {}), []);
console.log('regions.check ok');
