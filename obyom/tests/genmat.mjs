import { matLayout, matRaster } from '../web/js/mat.js';
import fs from 'fs';
const theme = process.argv[2] || 'light';
const L = matLayout('A4'); const R = matRaster(L, theme, 6);
fs.writeFileSync(`/tmp/t/mat_${theme}.pgm`, Buffer.concat([Buffer.from(`P5\n${R.w} ${R.h}\n255\n`), Buffer.from(R.g)]));
console.log(R.w, R.h);
