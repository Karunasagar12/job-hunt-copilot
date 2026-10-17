// Run: node dashboard/src/utils/linkedin.check.mjs
import assert from 'node:assert/strict';
import { formatSentAt, isLinkedInProfileUrl, noteLength, noteText } from './linkedin.js';

assert(isLinkedInProfileUrl('https://www.linkedin.com/in/jane-doe'));
assert(isLinkedInProfileUrl('https://ae.linkedin.com/in/jane/'));
assert(isLinkedInProfileUrl('https://in.linkedin.com/in/jane?trk=x'));
assert(isLinkedInProfileUrl('  https://linkedin.com/in/jane  '));
assert(!isLinkedInProfileUrl(''));
assert(!isLinkedInProfileUrl(null));
assert(!isLinkedInProfileUrl('linkedin.com/in/jane'));
assert(!isLinkedInProfileUrl('https://www.linkedin.com/company/acme'));
assert(!isLinkedInProfileUrl('https://evil.com/linkedin.com/in/jane'));
assert(!isLinkedInProfileUrl('https://linkedin.com.evil.com/in/jane'));

assert.equal(noteText('  Hi Jane  '), 'Hi Jane');
assert.equal(noteText(''), '');
assert.equal(noteText(null), '');
assert.equal(noteText('[Outreach content not yet generated for Jane Doe]'), '');

assert.equal(noteLength('héllo 👋'), 7);

assert.equal(formatSentAt(null), '');
assert.equal(formatSentAt('2026-10-11T05:00:00'), new Date('2026-10-11T05:00:00Z').toLocaleString());

console.log('linkedin.js ok');
