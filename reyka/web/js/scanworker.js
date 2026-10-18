// Фоновый поток оцифровки: тяжёлые расчёты не замораживают экран.
import { ScanEngine, makePump } from './scanengine.js';

const onMsg = makePump(new ScanEngine(), (m) => self.postMessage(m));
self.onmessage = (e) => onMsg(e.data);
