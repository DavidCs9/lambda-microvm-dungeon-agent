import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';

const initialWorld = Object.freeze({
  revision: 0,
  location: 'The Snapshot Tavern',
  inventory: [],
  story: ['You awaken beside a humming Firecracker.'],
});

export class StateStore {
  constructor(workspaceDir) {
    this.workspaceDir = workspaceDir;
    this.statePath = path.join(workspaceDir, 'world.json');
  }

  async initialize() {
    await mkdir(this.workspaceDir, { recursive: true });
    try {
      await readFile(this.statePath, 'utf8');
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
      await this.write(structuredClone(initialWorld));
    }
  }

  async read() {
    return JSON.parse(await readFile(this.statePath, 'utf8'));
  }

  async write(world) {
    const serialized = `${JSON.stringify(world, null, 2)}\n`;
    const temporaryPath = `${this.statePath}.tmp`;
    await writeFile(temporaryPath, serialized, { encoding: 'utf8', mode: 0o600 });
    await rename(temporaryPath, this.statePath);
  }

  async applyAction(action) {
    const world = await this.read();
    const next = {
      ...world,
      revision: world.revision + 1,
      story: [...world.story, action],
    };
    await this.write(next);
    return next;
  }
}
