/* Test-only transparent HTTP recorder. Every response comes from the real API. */
const http = require('node:http');
const {once} = require('node:events');
module.exports = async function recordingProxy(base) {
    const exchanges = [];
    const server = http.createServer(async (request, response) => {
        try {
            if (request.method !== 'POST' || request.url !== '/api/readings') throw new Error('Unexpected recorder request');
            const chunks = [];
            for await (const chunk of request) chunks.push(chunk);
            const body = Buffer.concat(chunks);
            const upstream = await fetch(`${base}/api/readings`, {method: 'POST',
                headers: {'Content-Type': 'application/json'}, body, redirect: 'manual', signal: AbortSignal.timeout(5000)});
            const result = await upstream.text();
            exchanges.push({payload: JSON.parse(body), status: upstream.status, response: JSON.parse(result)});
            response.writeHead(upstream.status, {'Content-Type': 'application/json'});
            response.end(result);
        } catch (error) { console.error(error); response.writeHead(502); response.end('Recorder failed'); }
    });
    server.listen(0, '127.0.0.1'); await once(server, 'listening');
    return {exchanges, url: `http://127.0.0.1:${server.address().port}/api/readings`,
        close: () => new Promise(resolve => {server.closeAllConnections(); server.close(resolve);})};
};
