// Runs the team-view page script against a tiny stub DOM at phone width.
// argv: script.js payload.json index [rerender.json] ; with a 4th arg it renders that payload
// again after the pick (a rerun) and reports the placement from that render.
//  prints JSON {afterRow: [positions in that row], open: bool}
const fs = require('fs');
const log = {};
const mk = (id) => ({ id, classList: { s: new Set(), add(c) { this.s.add(c); }, remove(c) { this.s.delete(c); } },
  innerHTML: '', after(n) { log.afterRow = this.cards; log.afterNode = n.id; }, appendChild() {}, scrollIntoView() {} });
const els = { grades: mk('grades'), panel: mk('panel'), bar: mk('bar'), plan: mk('plan') };
const cardsByIndex = {};
els.pitch = mk('pitch');
Object.defineProperty(els.pitch, 'innerHTML', { get() { return this._h || ''; }, set(h) {
  this._h = h;
  h.split('<div class="row">').slice(1).forEach((chunk) => {
    const row = { cards: [], after(n) { log.afterRow = this.cards; log.afterNode = n.id; } };
    for (const m of chunk.split('</div>')[0].matchAll(/data-i="(\d+)"/g)) { row.cards.push(+m[1]); cardsByIndex[m[1]] = row; }
    // positions of the cards in the row (second ".pos" div follows each data-i)
    row.cards = [...chunk.matchAll(/data-i="(\d+)"[\s\S]*?<div class="pos">(\w+)/g)].map((m) => m[2]);
  });
} });
global.document = {
  getElementById: (i) => els[i],
  querySelector: (q) => {
    if (q === '.wrap') return mk('wrap');
    const m = q.match(/data-i="(\d+)"/);
    return { parentNode: cardsByIndex[m[1]] };
  },
};
global.window = { innerWidth: 375 };
const payload = fs.readFileSync(process.argv[3], 'utf8');
eval(fs.readFileSync(process.argv[2], 'utf8') + `;render(${payload});pick(${+process.argv[4]});`
  + (process.argv[5] ? `;delete log.afterRow;delete log.afterNode;render(${fs.readFileSync(process.argv[5], 'utf8')});` : ''));
log.open = els.panel.classList.s.has('open');
console.log(JSON.stringify(log));
