import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const [app, sidebar] = await Promise.all([
  readFile(new URL('./App.jsx', import.meta.url), 'utf8'),
  readFile(new URL('./components/Sidebar.jsx', import.meta.url), 'utf8'),
]);

for (const path of ['/profile', '/settings']) {
  assert.match(app, new RegExp(`<Route\\s+path=["']${path}["']`), `${path} must resolve to a route`);
  assert.ok(sidebar.includes(`to: '${path}'`), `${path} must remain linked from the sidebar`);
}
console.log('routes.check ok');
