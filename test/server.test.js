import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { createServer } from '../src/server.js';

let baseUrl;
let server;
let workspaceDir;

before(async () => {
  workspaceDir = await mkdtemp(path.join(tmpdir(), 'dungeon-agent-'));
  server = await createServer({ workspaceDir });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address();
  baseUrl = `http://127.0.0.1:${port}`;
});

after(async () => {
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  await rm(workspaceDir, { recursive: true, force: true });
});

test('health endpoint reports ready', async () => {
  const response = await fetch(`${baseUrl}/health`);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { status: 'ok' });
});

test('actions persist in world state', async () => {
  const action = 'Take the brass key';
  const response = await fetch(`${baseUrl}/action`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ action }),
  });
  assert.equal(response.status, 200);
  const world = await response.json();
  assert.equal(world.revision, 1);
  assert.equal(world.story.at(-1), action);

  const persisted = await fetch(`${baseUrl}/state`).then((result) => result.json());
  assert.deepEqual(persisted, world);
});

test('invalid actions are rejected', async () => {
  const response = await fetch(`${baseUrl}/action`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ action: '' }),
  });
  assert.equal(response.status, 400);
});
