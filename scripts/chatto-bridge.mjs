import { request as httpsRequest } from 'node:https';
import { request as httpRequest } from 'node:http';

// Model/tool work can stay silent for longer than the bridge's request timeout.
// Its lifetime belongs to EVE and the bot's shutdown signal, not a socket timer.
export function createEveBridge({ baseUrl, token, ca, timeoutMs = 30000 }) {
  const request = new URL(baseUrl).protocol === 'https:' ? httpsRequest : httpRequest;
  return function eve(path, payload, signal) {
    return new Promise((ok, fail) => {
      const body = JSON.stringify(payload);
      const req = request(new URL(path, baseUrl), {
        method: 'POST', ca, signal,
        timeout: path === '/api/chatto/conversation' ? 0 : timeoutMs,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`,
          'Content-Length': Buffer.byteLength(body) },
      }, res => {
        let text = '', bytes = 0;
        // One queued answer may contain eight files of up to 20 MiB as base64.
        const limit = (path === '/api/chatto/deliveries' ? 240 : 30) * 1024 * 1024;
        res.setEncoding('utf8');
        res.on('data', chunk => { bytes += Buffer.byteLength(chunk); if (bytes > limit) res.destroy(new Error('Response too large')); else text += chunk; });
        res.on('error', fail);
        res.on('end', () => {
          if (res.statusCode < 200 || res.statusCode >= 300) return fail(Object.assign(new Error('EVE API rejected request'), { code: res.statusCode }));
          try { ok(JSON.parse(text)); } catch { fail(new Error('Invalid EVE response')); }
        });
      });
      req.on('timeout', () => req.destroy(new Error('EVE timeout')));
      req.on('error', fail);
      req.end(body);
    });
  };
}
