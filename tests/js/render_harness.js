// Runs the team-view page script against a stub DOM at desktop width and prints the
// rendered HTML. argv: script.js [index to pick] ; prints JSON {pitch, panel}
const fs = require('fs');
const mk = (id) => ({ id, innerHTML: '', classList: { add() {}, remove() {} }, appendChild() {} });
const els = { grades: mk('grades'), panel: mk('panel'), pitch: mk('pitch') };
global.document = { getElementById: (i) => els[i], querySelector: () => mk('wrap') };
global.window = { innerWidth: 1200 };
const pickIdx = process.argv[3];
eval(fs.readFileSync(process.argv[2], 'utf8') + (pickIdx === undefined ? '' : `;pick(${+pickIdx});`));
console.log(JSON.stringify({ pitch: els.pitch.innerHTML, panel: els.panel.innerHTML }));
