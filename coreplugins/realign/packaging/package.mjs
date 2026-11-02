// Empaqueta el plugin (la carpeta padre de esta) en packaging/dist/realign-<versión>.zip, listo
// para Administración → Plugins.
//
// El instalador de WebODM exige una sola carpeta raíz con plugin.py y manifest.json, y su nombre
// es el del plugin (de él salen las rutas /api/plugins/realign/...). Las rutas internas del zip
// van con "/": un zip con "\" (lo que genera Compress-Archive de PowerShell 5) se extrae en Linux
// como archivos llamados literalmente "realign\plugin.py".
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import AdmZip from 'adm-zip';

const root = path.dirname(fileURLToPath(import.meta.url));
const pluginName = 'realign';
const src = path.join(root, '..');

// `packaging` son estas mismas herramientas: no forman parte del plugin instalado.
const EXCLUDED_DIRS = new Set(['__pycache__', 'node_modules', 'packaging']);
// tests.py solo corre dentro del repo de WebODM; webpack.config.js lo regenera WebODM.
const EXCLUDED_FILES = new Set(['tests.py', 'public/webpack.config.js']);

for (const f of ['public/build/Realign.js', 'public/build/Realign.css']) {
  if (!fs.existsSync(path.join(src, f))) {
    console.error(`Falta ${pluginName}/${f}: ejecuta "npm run build" antes de empaquetar.`);
    process.exit(1);
  }
}

const manifest = JSON.parse(fs.readFileSync(path.join(src, 'manifest.json'), 'utf8'));
const zip = new AdmZip();
const added = [];

function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    const rel = path.relative(src, full).split(path.sep).join('/');
    if (entry.isDirectory()) {
      if (!EXCLUDED_DIRS.has(entry.name)) walk(full);
    } else if (!EXCLUDED_FILES.has(rel) && !entry.name.endsWith('.pyc')) {
      zip.addFile(`${pluginName}/${rel}`, fs.readFileSync(full));
      added.push(rel);
    }
  }
}
walk(src);

const distDir = path.join(root, 'dist');
fs.mkdirSync(distDir, { recursive: true });
const out = path.join(distDir, `${pluginName}-${manifest.version}.zip`);
zip.writeZip(out);

console.log(added.map(f => `  ${pluginName}/${f}`).join('\n'));
console.log(`\n${added.length} archivos → ${path.relative(root, out)}`);
