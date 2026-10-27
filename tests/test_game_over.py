"""
整局结束与重新开始：一对一全下直到一方输光，应收到 game_over；
发送 restart_game 后所有人筹码重置并自动开始新的一手。
运行：python tests/test_game_over.py
"""
import contextlib, io, os, sys, time
os.environ['POKER_ASYNC_MODE'] = 'threading'
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)
import app as m

fails = []
def check(name, cond, info=''):
    print(('PASS ' if cond else 'FAIL ') + name + (f'  [{info}]' if info and not cond else ''))
    if not cond: fails.append(name)

def wait_for(client, names, timeout=20):
    """等待收到 names 中的任一事件，返回 (事件名, 数据)；期间轮到真人就全下"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for e in client.get_received():
            if e['name'] in names:
                return e['name'], e['args'][0] if e['args'] else None
        if table.get_current_player() is me:
            client.emit('player_action', {'action': 'all_in', 'amount': 0})
        time.sleep(0.1)
    return None, None

log = io.StringIO()
with contextlib.redirect_stdout(log):
    c = m.socketio.test_client(m.app)
    c.emit('register_player', {'nickname': 'gameover_test'})
    c.emit('create_table', {'name': 'gameover_test', 'bots': {'beginner': 1}, 'initial_chips': 500})
    time.sleep(0.5)
    tid = next(k for k, t in m.tables.items() if t.title == 'gameover_test')
    table = m.tables[tid]
    me = next(p for p in table.players if not p.is_bot)
    c.get_received()
    c.emit('start_hand')
    game_over = None
    for hand in range(30):
        name, data = wait_for(c, ('game_over', 'show_next_round_vote'))
        if name == 'game_over':
            game_over = data
            break
        if name is None:
            break
        c.emit('vote_next_round', {'table_id': tid})

check('有一方输光后收到 game_over', game_over is not None, log.getvalue()[-500:])
if game_over:
    check('game_over 包含冠军与排名', game_over['champion'] and len(game_over['standings']) == 2
          and game_over['standings'][0]['chips'] == 1000 and game_over['standings'][1]['chips'] == 0, game_over)
    check('牌桌状态标记为 game_over（刷新页面可恢复弹窗）', table.get_table_state()['game_over'] is True)
    with contextlib.redirect_stdout(log):
        c.get_received()
        c.emit('restart_game', {'table_id': tid})
        time.sleep(0.5)
        names = [e['name'] for e in c.get_received()]
    check('重新开始：收到 game_restarted 与新手牌', 'game_restarted' in names and 'new_hand_started' in names, names)
    check('重新开始：筹码重置（加上盲注共 1000）', sum(p.chips for p in table.players) + table.pot == 1000
          and all(p.chips + p.total_bet == 500 for p in table.players), [(p.chips, p.total_bet) for p in table.players])
    check('重新开始：不再处于 game_over', table.get_table_state()['game_over'] is False)

with contextlib.redirect_stdout(log):
    c.emit('dissolve_table', {'table_id': tid})
    c.disconnect()
print('\n全部通过' if not fails else f'\n失败 {len(fails)} 项: {fails}')
