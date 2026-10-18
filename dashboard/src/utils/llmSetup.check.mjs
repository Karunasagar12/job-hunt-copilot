import assert from 'node:assert/strict';
import { initialLlmSetupState, llmSetupReducer } from './llmSetup.js';

const edited = llmSetupReducer({ saved: true, tested: true }, { type: 'edit' });
assert.deepEqual(edited, initialLlmSetupState, 'editing any model field invalidates the saved test');
const saved = llmSetupReducer(edited, { type: 'saved' });
assert.deepEqual(saved, { saved: true, tested: false }, 'saving alone does not count as a successful test');
assert.deepEqual(llmSetupReducer(saved, { type: 'tested', ok: false }), { saved: true, tested: false }, 'a failed retest keeps Continue disabled');
assert.deepEqual(llmSetupReducer(saved, { type: 'tested', ok: true }), { saved: true, tested: true }, 'only a successful test of saved fields enables Continue');
assert.deepEqual(llmSetupReducer(edited, { type: 'tested', ok: true }), { saved: false, tested: false }, 'unsaved fields cannot enable Continue');
console.log('llmSetup.check ok');
