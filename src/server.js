import http from 'node:http';
import { fileURLToPath } from 'node:url';
import { StateStore } from './state-store.js';

const MAX_BODY_BYTES = 16 * 1024;

function json(response, statusCode, body) {
  response.writeHead(statusCode, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  });
  response.end(JSON.stringify(body));
}

async function readJson(request) {
  let body = '';
  for await (const chunk of request) {
    body += chunk;
    if (Buffer.byteLength(body) > MAX_BODY_BYTES) {
      const error = new Error('Request body is too large');
      error.statusCode = 413;
      throw error;
    }
  }
  return body ? JSON.parse(body) : {};
}

export async function createServer({ workspaceDir }) {
  const store = new StateStore(workspaceDir);
  await store.initialize();

  return http.createServer(async (request, response) => {
    try {
      const url = new URL(request.url, 'http://localhost');

      if (request.method === 'GET' && url.pathname === '/health') {
        return json(response, 200, { status: 'ok' });
      }
      if (request.method === 'GET' && url.pathname === '/state') {
        return json(response, 200, await store.read());
      }
      if (request.method === 'POST' && url.pathname === '/action') {
        const { action } = await readJson(request);
        if (typeof action !== 'string' || action.trim().length === 0 || action.length > 500) {
          return json(response, 400, { error: 'action must be a non-empty string of at most 500 characters' });
        }
        return json(response, 200, await store.applyAction(action.trim()));
      }

      return json(response, 404, { error: 'not found' });
    } catch (error) {
      const statusCode = error instanceof SyntaxError ? 400 : (error.statusCode ?? 500);
      return json(response, statusCode, {
        error: statusCode === 500 ? 'internal server error' : error.message,
      });
    }
  });
}

const isMain = process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1];
if (isMain) {
  const port = Number.parseInt(process.env.PORT ?? '8080', 10);
  const workspaceDir = process.env.WORKSPACE_DIR ?? '/workspace';
  const server = await createServer({ workspaceDir });
  server.listen(port, '0.0.0.0', () => {
    console.log(JSON.stringify({ level: 'info', message: 'server started', port }));
  });
}
