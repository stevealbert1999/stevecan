export interface Env {}

const json = (data: unknown, status = 200): Response => {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      'content-type': 'application/json'
    }
  });
};

export default {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === '/health') {
      return json({
        ok: true,
        service: 'jarvis-os-api',
        version: '0.0.1',
        timestamp: new Date().toISOString()
      });
    }

    if (url.pathname === '/state') {
      return json({
        user: 'local-dev',
        agents: [],
        devices: [],
        suggestions: []
      });
    }

    if (url.pathname === '/events' && request.method === 'GET') {
      return json({
        events: []
      });
    }

    if (url.pathname === '/events' && request.method === 'POST') {
      const body = await request.json().catch(() => ({}));

      return json({
        accepted: true,
        event: body
      }, 202);
    }

    if (url.pathname === '/agent/message' && request.method === 'POST') {
      const body = await request.json().catch(() => ({}));

      return json({
        received: body,
        response: 'Jarvis core online. Capability execution not implemented yet.'
      });
    }

    return json({
      error: 'not_found'
    }, 404);
  }
};
