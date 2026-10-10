// Presentation regression: all table sizes keep the hero at bottom, with distinct seats.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('templates/table.html', 'utf8');
const render = source.slice(source.indexOf('    function displayPlayers('), source.indexOf('    function displayMyCards('));
const container = {dataset: {}, innerHTML: '', children: [], appendChild(el) {this.children.push(el);}};
const context = {
    console: {log() {}}, myPlayerId: 'hero', currentPlayer: {nickname: 'Hero'},
    currentTableState: {current_player_id: 'hero', game_stage: 'flop', current_bet: 20},
    I18N: {t: text => text}, getPlayerStatusDisplay: () => 'playing',
    document: {getElementById: () => container, createElement() {
        return {dataset: {}, style: {values: {}, setProperty(k, v) {this.values[k] = v;}},
            set textContent(value) {this.innerHTML = String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');}};
    }}
};
vm.createContext(context); vm.runInContext(render, context);
for (let n = 2; n <= 9; n++) {
    const players = Array.from({length: n}, (_, i) => ({id: i === n - 1 ? 'hero' : `p${i}`, nickname: i === 0 ? '<img src=x>' : `P${i}`, chips: 1000, status: 'playing', current_bet: 0}));
    const before = JSON.stringify(players); container.children = [];
    context.displayPlayers(players);
    assert.equal(container.children.length, n);
    assert.equal(JSON.stringify(players), before);
    assert.equal(new Set(container.children.map(el => JSON.stringify(el.style.values))).size, n);
    const hero = container.children[n - 1];
    assert.match(hero.className, /seat-me seat-active/);
    assert.equal(hero.dataset.seatIndex, 0);
    assert.equal(new Set(container.children.map(el => el.dataset.seatIndex)).size, n);
    assert.equal(hero.style.values['--seat-y'], '88%');
    assert.ok(Math.abs(parseFloat(hero.style.values['--seat-x']) - 50) < 0.001);
    assert.ok(container.children[0].innerHTML.includes('&lt;img src=x&gt;'));
    assert.ok(!container.children[0].innerHTML.includes('<img src=x>'));
}
context.displayPlayers([]);
console.log('PASS seat placement, hero highlight, escaping and immutable player order for 2–9 players');
