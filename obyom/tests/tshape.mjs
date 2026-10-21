// режимы формы: node tshape.mjs /tmp/t/box box|prism|planes|normal [истинный объём, мм³]
import { loadSet, hullOf, meshVolume, saveMesh } from './thull.mjs';
import { meshFromGrid, taubin, computeNormals, colorize } from '../web/js/recon.js';
import { boxMesh, prismMesh, snapPlanes } from '../web/js/shapes.js';
const [dir, mode, vtrue] = process.argv.slice(2);
const good = loadSet(dir), G = hullOf(good);
let M, info = '';
if (mode === 'box' || mode === 'prism') ({ mesh: M, info } = mode === 'box' ? boxMesh(G) : prismMesh(G));
else { M = meshFromGrid(G, 3); taubin(M, 30); computeNormals(M); if (mode === 'planes') ({ mesh: M, info } = snapPlanes(M)); }
colorize(M, good);
const v = meshVolume(M);
console.log(mode, info, '| объём', (v / 1000).toFixed(2), 'см³', vtrue ? `(истина ${(vtrue / 1000).toFixed(2)}, ошибка ${((v / vtrue - 1) * 100).toFixed(1)}%)` : '', '| треугольников', M.idx.length / 3);
saveMesh(M, `/tmp/t/mesh_${mode}.json`);
