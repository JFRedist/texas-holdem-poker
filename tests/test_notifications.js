const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('templates/base.html', 'utf8');
const code = source.slice(source.indexOf('        function showNotification('), source.indexOf('        // 创建扑克牌元素'));
function container() {
    return {children: [], appendChild(child) {this.children.push(child); child.parentNode = this;},
        removeChild(child) {this.children.splice(this.children.indexOf(child), 1); child.parentNode = null;},
        replaceChildren(child) {for (const old of [...this.children]) this.removeChild(old); this.appendChild(child);}};
}
for (const inTable of [false, true]) {
    const overlay = container(), inline = inTable ? container() : null, timers = [];
    const context = {document: {createElement: () => ({}), getElementById: id => id === 'tableNotification' ? inline : overlay}, setTimeout: fn => timers.push(fn)};
    vm.createContext(context); vm.runInContext(code, context);
    context.showNotification('玩家 A 过牌');
    context.showNotification('<玩家 B> 跟注', 'success');
    const target = inline || overlay;
    assert.equal(target.children.length, inTable ? 1 : 2);
    assert.equal(target.children.at(-1).textContent, '<玩家 B> 跟注');
    if (inTable) assert.equal(overlay.children.length, 0);
    timers[0]();
    assert.equal(target.children.length, 1, 'Older timers must not clear the latest notice');
    timers[1]();
    assert.equal(target.children.length, 0);
}
console.log('Notification routing and expiry checks passed');
