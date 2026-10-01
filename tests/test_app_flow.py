"""
服务端流程测试：行动超时、离桌后继续推进、同一玩家不能同时坐两张桌、德州扑克之神只限练习桌、
自动开局时给真人发底牌、your_turn 的最小下注额。
需要安装 requirements.txt 中的依赖（以 threading 模式导入 app，不需要 eventlet）。
运行：python tests/test_app_flow.py
"""
import contextlib, io, os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ['POKER_ASYNC_MODE'] = 'threading'
os.chdir(tempfile.mkdtemp())   # 数据库文件写到临时目录
time.sleep = lambda s: None    # 去掉机器人思考延迟
with contextlib.redirect_stdout(io.StringIO()):
    import app
from poker_engine.table import Table, GameStage
from poker_engine.player import Player, PlayerStatus, PlayerAction as A
from poker_engine.bot import Bot, BotLevel

quiet = lambda: contextlib.redirect_stdout(io.StringIO())
fails = []
def check(name, cond, info=''):
    print(('PASS ' if cond else 'FAIL ') + name + (f'  [{info}]' if info and not cond else ''))
    if not cond: fails.append(name)

# 记录服务端发出的事件；后台任务同步执行，便于断言
emitted = []
app.socketio.emit = lambda event, data=None, room=None, **kw: emitted.append((event, data, room))
app.socketio.start_background_task = lambda fn, *a, **kw: fn(*a, **kw)
app.ACTION_TIMEOUT_SECONDS = 0   # 默认不启动计时，超时逻辑单独测试

def reset():
    app.tables.clear(); app.player_sessions.clear(); app.session_tables.clear()
    app.next_round_votes.clear(); app._action_timers.clear(); app.players.clear(); emitted.clear()

def connect_sid():
    """测试客户端连接后服务端发出的 connected 事件里带有会话 id"""
    return [e for e in emitted if e[0] == 'connected'][-1][1]['session_id']

def error_messages():
    msgs = [e[1]['message'] for e in emitted if e[0] == 'error']
    emitted[:] = [e for e in emitted if e[0] != 'error']
    return msgs

def make_table(tid, members, **kw):
    t = Table(tid, tid, 10, 20, 9, 1000, **kw)
    with quiet():
        for m in members: t.add_player(m)
    app.tables[tid] = t
    return t

def start(t):
    with quiet(): t.start_new_hand()

# 1. your_turn 的最小下注 / 最小加注按当前规则计算，并告知超时秒数
reset()
h1, h2, h3 = Player('h1', 'H1'), Player('h2', 'H2'), Player('h3', 'H3')
t = make_table('t1', [h1, h2, h3])
start(t)
utg = t.get_current_player()
with quiet(): t.process_player_action(utg.id, A.RAISE, 60)
nxt = t.get_current_player()
payload = app.your_turn_payload(t, nxt)
check('your_turn 的 min_raise_to 为当前下注 + 上次加注幅度', payload['min_raise_to'] == 100, payload)
check('your_turn 的 min_bet 使用牌桌规则', payload['min_bet'] == t.min_bet())
reset()
ta = make_table('ta', [Player('a1', 'A1'), Player('a2', 'A2')], game_mode='ante', ante_percentage=0.05)
check('按比例下注模式的 min_bet 不是大盲', app.your_turn_payload(ta, ta.players[0])['min_bet'] == ta.min_bet() != ta.big_blind)

# 2. 行动超时：欠注时自动弃牌，无需跟注时自动过牌；玩家已行动后旧计时不生效
reset()
h1, h2, h3 = Player('h1', 'H1'), Player('h2', 'H2'), Player('h3', 'H3')
t = make_table('t2', [h1, h2, h3])
start(t)
cur = t.get_current_player()
key = (cur.id, t.hand_number, t.action_count)
with quiet(): r = app.handle_action_timeout('t2', *key)
check('超时且欠注时自动弃牌', r and r['success'] and cur.status == PlayerStatus.FOLDED, r)
check('超时动作会广播给全桌', any(e[0] == 'action_processed' and '超时' in e[1]['description'] for e in emitted))
with quiet(): r = app.handle_action_timeout('t2', *key)
check('同一次轮到的旧计时不会重复生效', r is None)
nxt = t.get_current_player()
with quiet(): t.process_player_action(nxt.id, A.CALL)
stale = (t.get_current_player().id, t.hand_number, t.action_count - 1)
with quiet(): r = app.handle_action_timeout('t2', *stale)
check('玩家已行动后旧计时不生效', r is None)
reset()
h1, h2 = Player('h1', 'H1'), Player('h2', 'H2')
t = make_table('t3', [h1, h2])
start(t)
with quiet(): t.process_player_action(t.get_current_player().id, A.CALL)   # 小盲补齐，轮到大盲可以过牌
bb = t.get_current_player()
with quiet(): r = app.handle_action_timeout('t3', bb.id, t.hand_number, t.action_count)
check('超时且无需跟注时自动过牌', r and r['success'] and r['action'] == 'check' and bb.status == PlayerStatus.PLAYING, r)

# 计时器：轮到真人时开始计时，到时自动行动
reset()
app.ACTION_TIMEOUT_SECONDS = 30
h1, h2, h3 = Player('h1', 'H1'), Player('h2', 'H2'), Player('h3', 'H3')
t = make_table('t4', [h1, h2, h3])
start(t)
cur = t.get_current_player()
with quiet(): app.arm_action_timer('t4', cur)
check('计时到期后替挂机玩家行动', cur.status == PlayerStatus.FOLDED and t.get_current_player() is not cur)
app.ACTION_TIMEOUT_SECONDS = 0

# 3. 当前行动者离桌后牌局继续（轮到机器人时机器人接着行动）
reset()
h1, h2 = Player('h1', 'H1'), Player('h2', 'H2')
b1 = Bot('b1', 'B1', 1000, BotLevel.BEGINNER)
t = make_table('t5', [h1, b1, h2])        # h1 庄家，b1 小盲，h2 大盲，翻牌前 h1 先行动，下一位是 b1
start(t)
check('前置：轮到 H1 行动', t.get_current_player() is h1)
client = app.socketio.test_client(app.app)
sid = connect_sid()
app.player_sessions[sid] = {'player_id': 'h1', 'nickname': 'H1'}
app.session_tables[sid] = 't5'
with quiet():
    client.emit('leave_table')
check('当前行动者离桌后牌局继续推进', t.get_current_player() is not None and t.get_current_player() is not h1
      or t.game_stage == GameStage.FINISHED, (t.game_stage.value, t.get_current_player()))
check('离桌后机器人接着行动', b1.has_acted or t.game_stage == GameStage.FINISHED)
client.disconnect()

# 4. 同一玩家不能同时坐两张桌
reset()
p = Player('p1', 'P1')
app.players['p1'] = p
make_table('t6', [p, Player('x', 'X')])
check('find_other_table 找到玩家所在的其他牌桌', app.find_other_table('p1', 't7') is app.tables['t6'])
check('当前牌桌不算其他牌桌', app.find_other_table('p1', 't6') is None)
make_table('t7', [Player('y', 'Y')])
client = app.socketio.test_client(app.app)
sid = connect_sid()
app.player_sessions[sid] = {'player_id': 'p1', 'nickname': 'P1'}
with quiet():
    client.emit('join_table', {'table_id': 't7', 'position': 3})
errors = error_messages()
check('已在其他牌桌时不能再加入第二张桌', errors and '请先离开' in errors[0] and app.tables['t7'].get_player('p1') is None, errors)
with quiet():
    client.emit('create_table', {'name': '新桌', 'small_blind': 10, 'big_blind': 20, 'initial_chips': 1000})
errors = error_messages()
check('已在其他牌桌时不能再建桌', errors and '请先离开' in errors[0], errors)
client.disconnect()

# 5. 德州扑克之神只能加在只有一名真人的练习桌上
reset()
t = make_table('t8', [Player('q1', 'Q1'), Player('q2', 'Q2')])
client = app.socketio.test_client(app.app)
sid = connect_sid()
app.player_sessions[sid] = {'player_id': 'q1', 'nickname': 'Q1'}
app.session_tables[sid] = 't8'
with quiet():
    client.emit('add_bot', {'level': 'god'})
errors = error_messages()
check('多真人桌不能添加德州扑克之神', errors and '德州扑克之神' in errors[0] and not any(getattr(p, 'bot_level', None) == BotLevel.GOD for p in t.players), errors)
client.disconnect()
reset()
t = make_table('t9', [Player('q1', 'Q1'), Bot('g1', 'G1', 1000, BotLevel.GOD)])
client = app.socketio.test_client(app.app)
sid = connect_sid()
app.player_sessions[sid] = {'player_id': 'q3', 'nickname': 'Q3'}
app.players['q3'] = Player('q3', 'Q3')
with quiet():
    client.emit('join_table', {'table_id': 't9', 'position': 4})
errors = error_messages()
check('有德州扑克之神的练习桌不能再加入第二名真人', errors and '德州扑克之神' in errors[0] and t.get_player('q3') is None, errors)
client.disconnect()

# 6. 自动开局时给真人发底牌
reset()
h1 = Player('h1', 'H1')
t = make_table('t10', [h1, Bot('b2', 'B2', 1000, BotLevel.BEGINNER)])
app.player_sessions['sid-h1'] = {'player_id': 'h1', 'nickname': 'H1'}
with quiet():
    app.handle_restart_needed('t10', None, {'hand_number': 0})
check('自动开局给真人发送底牌', any(e[0] == 'your_cards' and e[2] == 'sid-h1' for e in emitted))

print('\n全部通过' if not fails else f'\n失败 {len(fails)} 项: {fails}')
os._exit(1 if fails else 0)
