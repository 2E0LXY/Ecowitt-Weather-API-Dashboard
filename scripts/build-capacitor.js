const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const dist = path.join(root, 'dist');

fs.rmSync(dist, { recursive: true, force: true });
fs.mkdirSync(dist, { recursive: true });

const html = fs.readFileSync(path.join(root, 'static', 'weather.html'), 'utf8');
fs.writeFileSync(path.join(dist, 'index.html'), html);

fs.writeFileSync(
  path.join(dist, 'assetlinks-placeholder.txt'),
  'This Android build bundles the dashboard locally and uses the configured FastAPI backend for API calls.\n'
);

console.log(`Built Capacitor web assets in ${dist}`);
