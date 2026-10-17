/**
 * Генерация иконок PWA из SVG-источника.
 * Запуск: npm run icons
 */
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import sharp from 'sharp';

const __dirname = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(__dirname, '..', 'public', 'icons');

const icon = (pad) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0b1020"/>
      <stop offset="55%" stop-color="#12203c"/>
      <stop offset="100%" stop-color="#0b1020"/>
    </linearGradient>
    <linearGradient id="g1" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#38c3f5"/>
      <stop offset="60%" stop-color="#8b5cf6"/>
      <stop offset="100%" stop-color="#10d19a"/>
    </linearGradient>
    <linearGradient id="g2" x1="0" y1="1" x2="1" y2="0">
      <stop offset="0%" stop-color="#10d19a" stop-opacity="0.9"/>
      <stop offset="100%" stop-color="#38c3f5" stop-opacity="0.9"/>
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="512" height="512" rx="${pad ? 0 : 112}" fill="url(#bg)"/>
  <g transform="translate(256 256) scale(0.82) translate(-256 -256)">
    <rect x="86" y="128" width="340" height="248" rx="40" fill="none" stroke="url(#g1)" stroke-width="18" opacity="0.95"/>
    <rect x="86" y="128" width="340" height="72" rx="36" fill="url(#g1)" opacity="0.22"/>
    <line x1="256" y1="200" x2="256" y2="376" stroke="url(#g1)" stroke-width="10" opacity="0.35"/>
    <line x1="126" y1="252" x2="386" y2="252" stroke="url(#g1)" stroke-width="10" opacity="0.2"/>
    <circle cx="176" cy="300" r="26" fill="url(#g2)"/>
    <circle cx="256" cy="330" r="30" fill="url(#g2)"/>
    <circle cx="336" cy="300" r="26" fill="url(#g2)" opacity="0.85"/>
    <path d="M150 214 h212" stroke="#e7ecf5" stroke-width="16" stroke-linecap="round" opacity="0.85"/>
    <path d="M196 380 h120" stroke="#34e5b0" stroke-width="14" stroke-linecap="round" opacity="0.8"/>
  </g>
</svg>`;

const favicon = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#38c3f5"/><stop offset="100%" stop-color="#10d19a"/>
    </linearGradient>
  </defs>
  <rect width="64" height="64" rx="16" fill="#0b1020"/>
  <rect x="12" y="18" width="40" height="28" rx="7" fill="none" stroke="url(#g)" stroke-width="3.4"/>
  <path d="M20 26h24" stroke="#e7ecf5" stroke-width="3" stroke-linecap="round"/>
  <circle cx="24" cy="38" r="3.6" fill="#10d19a"/>
  <circle cx="32" cy="41" r="4.2" fill="#38c3f5"/>
  <circle cx="40" cy="38" r="3.6" fill="#8b5cf6"/>
</svg>`;

await mkdir(outDir, { recursive: true });

const targets = [
  ['icon-192.png', 192, false],
  ['icon-512.png', 512, false],
  ['icon-maskable-512.png', 512, true],
  ['apple-touch-icon.png', 180, false],
];

for (const [name, size, maskable] of targets) {
  const svg = maskable
    ? icon(true).replace('scale(0.82)', 'scale(0.66)')
    : icon(false);
  const buf = await sharp(Buffer.from(svg)).resize(size, size).png({ quality: 100 }).toBuffer();
  await writeFile(resolve(outDir, name), buf);
  console.log('✓', name, buf.length, 'bytes');
}

/* ICO (с PNG внутри) — нужен для ярлыков Windows и иконки окна приложения */
const icoSizes = [16, 24, 32, 48, 64, 128, 256];
const pngEntries = [];
for (const size of icoSizes) {
  const buf = await sharp(Buffer.from(icon(false))).resize(size, size).png({ quality: 100 }).toBuffer();
  pngEntries.push({ size, buf });
}
const headerSize = 6 + 16 * pngEntries.length;
let offset = headerSize;
const chunks = [];
const dirHeader = Buffer.alloc(6);
dirHeader.writeUInt16LE(0, 0);
dirHeader.writeUInt16LE(1, 2);
dirHeader.writeUInt16LE(pngEntries.length, 4);
chunks.push(dirHeader);
for (const e of pngEntries) {
  const entry = Buffer.alloc(16);
  entry.writeUInt8(e.size >= 256 ? 0 : e.size, 0);
  entry.writeUInt8(e.size >= 256 ? 0 : e.size, 1);
  entry.writeUInt8(0, 2);
  entry.writeUInt8(0, 3);
  entry.writeUInt16LE(1, 4);
  entry.writeUInt16LE(32, 6);
  entry.writeUInt32LE(e.buf.length, 8);
  entry.writeUInt32LE(offset, 12);
  offset += e.buf.length;
  chunks.push(entry);
}
for (const e of pngEntries) chunks.push(e.buf);
const ico = Buffer.concat(chunks);
await writeFile(resolve(outDir, 'icon.ico'), ico);
console.log('✓ icon.ico', ico.length, 'bytes');

await writeFile(resolve(outDir, 'icon.svg'), icon(false));
await writeFile(resolve(outDir, 'favicon.svg'), favicon);
await writeFile(resolve(outDir, '..', 'favicon.svg'), favicon);
console.log('✓ icon.svg, favicon.svg');
