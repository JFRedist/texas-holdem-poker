const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/music-player.js', 'utf8');
for (const method of ['updatePanelPosition', 'updateShowButtonPosition']) {
    const start = source.indexOf('    ' + method + '(');
    const end = source.indexOf('\n    }', start) + 6;
    const object = vm.runInNewContext('({' + source.slice(start, end) + '})');
    for (const position of ['top-left', 'top-right', 'bottom-left', 'bottom-right']) {
        const element = {style: {}, classList: {remove() {}}};
        object.position = position;
        object[method](element);
        const [vertical, horizontal] = position.split('-');
        assert.equal(element.style[vertical], vertical === 'top' ? '80px' : '20px');
        assert.equal(element.style[horizontal], '20px');
        assert.equal(element.style[vertical === 'top' ? 'bottom' : 'top'], 'auto');
        assert.equal(element.style[horizontal === 'left' ? 'right' : 'left'], 'auto');
    }
}
console.log('PASS music panel and toggle positions at all four corners');
