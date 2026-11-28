/* Experimental CuraEngine WASM probe, not printer G-code.
 *
 * Usage:
 *   node slice_clover_led_compact_probe.mjs ENGINE_JS DEF_DIR INPUT_STL OUTPUT_JSON on|off
 * ENGINE_JS is the installed @mosaicslicer/curaengine@0.0.3 dist/CuraEngine.js;
 * DEF_DIR contains fdmprinter.def.json and fdmextruder.def.json from Cura 5.11.0.
 * See the compact concept documentation for exact reproduction commands.
 *
 * The engine writes G-code only to its in-memory virtual filesystem. We save
 * selected XY segments and aggregate counts, NOT printable instructions. This
 * is an approximate, generic single-extruder slice, not a verified printer
 * profile, a multicolour test, or approval to manufacture the concept.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';

const [enginePath, definitionsDir, inputPath, outputPath, mode] = process.argv.slice(2);
if (!enginePath || !definitionsDir || !inputPath || !outputPath || !['on', 'off'].includes(mode)) {
  console.error('Usage: node slice_clover_led_compact_probe.mjs ENGINE_JS DEF_DIR INPUT_STL OUTPUT_JSON on|off');
  process.exit(2);
}
if (!outputPath.endsWith('.json')) throw new Error('Output must be a diagnostic .json file, never G-code');

// The package is compiled for a browser. Its WASM is embedded, so a minimal
// window alias is sufficient in Node; no network access is needed for slicing.
globalThis.window = globalThis;
let engineInfo = null;
let sliceInfo = null;
globalThis.clover_progress = () => {};
globalThis.clover_engine = (info) => { engineInfo = info; };
globalThis.clover_slice = (info) => { sliceInfo = info; };
globalThis.clover_header = () => {};
const warnings = [];
const {default: createEngine} = await import(pathToFileURL(path.resolve(enginePath)).href);
const engine = await createEngine({
  noInitialRun: true,
  print: (line) => { if (!line.includes('All settings:')) console.log(line); },
  printErr: (line) => {
    if (line.includes('[warning]') || line.includes('[error]')) warnings.push(line);
    if (!line.includes('All settings:')) console.error(line);
  },
});

const printer = JSON.parse(fs.readFileSync(path.join(definitionsDir, 'fdmprinter.def.json'), 'utf8'));
const extruder = fs.readFileSync(path.join(definitionsDir, 'fdmextruder.def.json'));
// The 5.11.0 definition has a literal value but no default for this disabled
// setting. CuraEngine's standalone loader otherwise warns and drops the key.
let patched = 0;
function patchResetDefault(value) {
  if (!value || typeof value !== 'object') return;
  for (const [key, child] of Object.entries(value)) {
    if (key === 'reset_flow_duration') {
      if (child.value !== 2 || child.default_value !== undefined) {
        throw new Error('Unexpected Cura definition: inspect reset_flow_duration before patching');
      }
      child.default_value = 2;
      patched++;
    }
    patchResetDefault(child);
  }
}
patchResetDefault(printer);
if (patched !== 1) throw new Error(`Expected one reset_flow_duration setting, found ${patched}`);
const mesh = fs.readFileSync(inputPath);
engine.FS.writeFile('/fdmprinter.def.json', JSON.stringify(printer));
engine.FS.writeFile('/fdmextruder.def.json', extruder);
engine.FS.writeFile('/probe.stl', mesh);

// Deliberately generic settings; all other values are standalone defaults from
// the specified Cura definitions, not the settings of a real Bambu printer.
const settings = {
  machine_width: 220, machine_depth: 220, machine_height: 220,
  machine_center_is_zero: false, machine_extruder_count: 1,
  machine_start_gcode: '', machine_end_gcode: '',
  layer_height: 0.2, layer_height_0: 0.2,
  machine_nozzle_size: 0.4, material_diameter: 1.75,
  line_width: 0.4, wall_line_width: 0.4, wall_line_width_0: 0.4, wall_line_width_x: 0.4,
  wall_line_count: 2, top_layers: 4, bottom_layers: 4,
  infill_sparse_density: 20, infill_line_distance: 4,
  support_enable: mode === 'on', support_type: 'everywhere', support_angle: 50,
  support_structure: 'normal', support_z_seam_min_distance: 0,
  support_infill_sparse_thickness: 0.2, support_z_distance: 0.2,
  support_top_distance: 0.2, support_bottom_distance: 0.2,
  adhesion_type: 'none', speed_print: 50,
};
const args = [
  'slice', '--progress_cb', 'clover_progress', '--engine_info_cb', 'clover_engine',
  '--gcode_header_cb', 'clover_header', '--slice_info_cb', 'clover_slice',
  '-m1', '--force-read-parent', '-j', '/fdmprinter.def.json',
];
for (const [key, value] of Object.entries(settings)) args.push('-s', `${key}=${value}`);
args.push('-e0', '-j', '/fdmextruder.def.json', '-s', 'material_diameter=1.75',
          '-l', '/probe.stl', '-o', '/probe.gcode');
engine.callMain(args);
if (engineInfo?.version !== '5.11.0-alpha.0' || !sliceInfo) {
  throw new Error(`Unexpected or incomplete engine result: ${JSON.stringify(engineInfo)}`);
}
const text = engine.FS.readFile('/probe.gcode', {encoding: 'utf8'});
if (!text.includes(';LAYER:0') || !text.includes('M82') || text.includes('\nM83')) {
  throw new Error('Missing layers or unsupported extrusion mode');
}

// Only linear XY extrusion segments are retained, stripped of extrusion
// amounts, temperatures, motion commands and all other machine instructions.
const selected = new Set([0, 10, 15, 26, 28]);
const paths = [];
const counts = {};
const supportLayers = new Set();
let layer = null, type = '', x = 0, y = 0, z = 0, e = 0, layerCount = 0;
const number = /([XYZE])(-?(?:\d+(?:\.\d*)?|\.\d+))/g;
for (const line of text.split('\n')) {
  if (line.startsWith(';LAYER_COUNT:')) layerCount = Number(line.slice(13));
  else if (line.startsWith(';LAYER:')) layer = Number(line.slice(7));
  else if (line.startsWith(';TYPE:')) type = line.slice(6).trim();
  else if (line.startsWith('G92')) {
    const match = line.match(/\bE(-?(?:\d+(?:\.\d*)?|\.\d+))/);
    if (match) e = Number(match[1]);
  } else if (line.startsWith('G0 ') || line.startsWith('G1 ')) {
    const values = Object.fromEntries([...line.matchAll(number)].map((m) => [m[1], Number(m[2])]));
    const nx = values.X ?? x, ny = values.Y ?? y, nz = values.Z ?? z, ne = values.E ?? e;
    if (layer !== null && ne > e + 1e-6 && Math.hypot(nx - x, ny - y) > 1e-8) {
      counts[type] = (counts[type] ?? 0) + 1;
      if (type === 'SUPPORT' || type.startsWith('SUPPORT-')) supportLayers.add(layer);
      if (selected.has(layer)) paths.push([layer, type, x, y, nx, ny]);
    }
    x = nx; y = ny; z = nz; e = ne;
  }
}
if (!layerCount || !counts['WALL-OUTER']) throw new Error('No model extrusion paths found');
const data = {
  diagnostic_only: 'NOT FOR PRINTING. Selected 2D paths, not printer instructions.',
  source_mesh_sha256: crypto.createHash('sha256').update(mesh).digest('hex'),
  engine: '@mosaicslicer/curaengine 0.0.3 / Cura_SteamEngine 5.11.0-alpha.0 (WASM)',
  definitions: 'UltiMaker Cura 5.11.0; reset_flow_duration default set to its literal value 2',
  settings, warnings,
  layer_count: layerCount,
  segment_counts: counts,
  support_layers: [...supportLayers].sort((a, b) => a - b),
  selected_layers: [...selected],
  paths,
};
fs.writeFileSync(outputPath, JSON.stringify(data));
console.log(`Saved diagnostic paths: ${outputPath}; layers=${layerCount}; supports=${counts.SUPPORT ?? 0}`);
