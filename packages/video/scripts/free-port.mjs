import net from 'node:net';

// Remotion's preview server defaults to port 3000 and probes availability only by binding.
// On Windows that bind succeeds even while another process already answers on the port
// through a wildcard listener, so the renderer serves the bundle on a port Chrome cannot
// reach: Chrome loads the foreign page instead and composition lookup fails with
// "window.getStaticCompositions is undefined". Pin a port nothing answers on.
const answers = (port) => new Promise((resolve) => {
  const socket = new net.Socket();
  socket.setTimeout(250);
  socket.once('connect', () => { socket.destroy(); resolve(true); });
  socket.once('timeout', () => { socket.destroy(); resolve(false); });
  socket.once('error', () => resolve(false));
  socket.connect(port, '127.0.0.1');
});

export const freeRemotionPort = async ({attempts = 40} = {}) => {
  for (let i = 0; i < attempts; i++) {
    const port = await new Promise((resolve, reject) => {
      const server = net.createServer();
      server.once('error', reject);
      server.listen(0, '127.0.0.1', () => {
        const {port} = server.address();
        server.close(() => resolve(port));
      });
    });
    if (port >= 1024 && !(await answers(port))) return port;
  }
  throw new Error('no free local port available for the Remotion preview server');
};
