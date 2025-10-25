const { spawn } = require('child_process');
const path = require('path');

module.exports = (req, res) => {
  const py = spawn('python3', [path.join(__dirname, 'index.py')], {
    stdio: ['pipe', 'pipe', 'inherit']
  });
  py.stdin.write(JSON.stringify({ req, env: process.env }));
  py.stdin.end();
  let out = '';
  py.stdout.on('data', d => out += d);
  py.on('close', code => {
    res.status(code === 0 ? 200 : 500).send(out);
  });
};