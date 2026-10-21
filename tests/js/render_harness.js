// Runs the team-sheet page script against a stub DOM at desktop width and prints the
// rendered HTML. argv: script.js payload.json [index to pick]
// env FRAME=1: run inside a stub parent frame (drawn by a streamlit:render message);
// env SEND=<json>: then pass that action to send(). env AFTER=<js>: run after the pick (e.g.
// openReplace(), setQ('x'), swapIn(5)); the page's functions are in scope. Prints JSON {pitch, panel, grades, posted}
const fs = require('fs');
const mk = (id) => ({ id, innerHTML: '', classList: { add() {}, remove() {} }, appendChild() {} });
const els = { grades: mk('grades'), panel: mk('panel'), pitch: mk('pitch'), bar: mk('bar'), plan: mk('plan') };
const posted = [], listeners = {};
global.document = { getElementById: (i) => els[i], querySelector: () => mk('wrap'), body: { scrollHeight: 640 } };
global.window = { innerWidth: 1200 };
if (process.env.FRAME) {
  window.parent = { postMessage: (m) => posted.push(m) };
  window.addEventListener = (t, fn) => { listeners[t] = fn; };
}
const payload = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const pickIdx = process.argv[4];
const first = process.env.FRAME
  ? `;listeners.message({data: {type: 'streamlit:render', args: {payload: ${JSON.stringify(payload)}}}});`
  : `;render(${JSON.stringify(payload)});`;
const then = (pickIdx === undefined ? '' : `;pick(${+pickIdx});`)
  + (process.env.AFTER ? `;${process.env.AFTER};` : '')
  + (process.env.SEND ? `;send(${process.env.SEND});` : '');
eval(fs.readFileSync(process.argv[2], 'utf8') + first + then);
console.log(JSON.stringify({ pitch: els.pitch.innerHTML, panel: els.panel.innerHTML,
  grades: els.grades.innerHTML, bar: els.bar.innerHTML, plan: els.plan.innerHTML, posted }));
