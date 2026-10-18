import assert from 'node:assert/strict';
import { regionLabel, regionOptions, updateProfileRegions } from './regions.js';

const regions = [{ id: 'eu', label: 'Europe' }, { id: 'gcc', label: 'Gulf' }];
assert.equal(regionLabel(regions, 'eu'), 'Europe');
assert.equal(regionLabel(regions, 'india'), 'INDIA');
assert.equal(regionLabel(regions, ''), '—');
assert.deepEqual(regionOptions(regions, { includeAuto: true }).map(option => option.value), ['auto', 'eu', 'gcc']);
assert.deepEqual(regionOptions([], {}), []);
const updatedProfile = updateProfileRegions({ name: 'Candidate', regions: [{ id: 'eu' }], default_region: 'eu' }, [{ id: 'gcc' }, { id: 'eu' }], 'gcc');
assert.deepEqual(updatedProfile.regions.map(region => region.id), ['gcc', 'eu']);
assert.equal(updatedProfile.default_region, 'gcc');
assert.equal(updatedProfile.name, 'Candidate');
console.log('regions.check ok');
