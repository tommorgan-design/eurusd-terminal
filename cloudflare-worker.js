// ═══════════════════════════════════════════════════════════════
// EUR/USD Terminal — Cloudflare Worker Proxy for Anthropic API
// ═══════════════════════════════════════════════════════════════
// 
// This Worker sits between your GitHub Pages terminal and 
// Anthropic's API, adding the CORS headers that browsers require.
//
// Deploy: Cloudflare Dashboard → Workers & Pages → Create → 
//         Paste this code → Deploy
//
// Your terminal Settings tab needs this Worker's URL:
//   https://eurusd-proxy.YOUR-ACCOUNT.workers.dev
//
// ═══════════════════════════════════════════════════════════════

export default {
  async fetch(request, env) {
    // ─── CORS Preflight ───
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        status: 204,
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'POST, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type, x-api-key, anthropic-version, anthropic-beta',
          'Access-Control-Max-Age': '86400',
        },
      });
    }

    // ─── Only allow POST ───
    if (request.method !== 'POST') {
      return new Response('Method not allowed', { 
        status: 405,
        headers: { 'Access-Control-Allow-Origin': '*' }
      });
    }

    // ─── Build headers for Anthropic ───
    const anthropicHeaders = {
      'Content-Type': 'application/json',
      'x-api-key': request.headers.get('x-api-key') || '',
      'anthropic-version': request.headers.get('anthropic-version') || '2023-06-01',
    };

    // Pass through anthropic-beta header if present (for web search etc)
    const beta = request.headers.get('anthropic-beta');
    if (beta) {
      anthropicHeaders['anthropic-beta'] = beta;
    }

    // ─── Forward to Anthropic ───
    try {
      const response = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: anthropicHeaders,
        body: request.body,
      });

      // ─── Return with CORS headers ───
      const responseBody = await response.text();
      return new Response(responseBody, {
        status: response.status,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*',
        },
      });
    } catch (error) {
      return new Response(JSON.stringify({ error: 'Proxy error: ' + error.message }), {
        status: 502,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*',
        },
      });
    }
  },
};
