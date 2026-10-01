"""
下一轮投票测试：手牌进行中投票不能重开（底池不能被清零），重开时断线玩家不发牌。
运行：python tests/test_next_round.py
"""
import contextlib, io, os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('POKER_ASYNC_MODE', 'threading')
os.chdir(tempfile.mkdtemp())  # app 导入时会在当前目录创建 sqlite 数据库，放到临时目录
quiet = lambda: contextlib.redirect_stdout(io.StringIO())
with quiet():
    import app as server
from poker_engine.table import Table, GameStage
from poker_engine.player import Player, PlayerStatus, PlayerAction as A
from poker_engine.bot import Bot

fails = []
def check(name, cond, info=''):
    print(('PASS ' if cond else 'FAIL ') + name + (f'  [{info}]' if info and not cond else ''))
    if not cond: fails.append(name)

server.socketio.start_background_task = lambda *a, **k: None  # 不启动机器人后台处理

def setup(n_players, bots=0):
    t = Table('vt', 'vt', 10, 20, max_players=9, initial_chips=1000)
    ps = [Player(f'v{i}', f'V{i}', 1000) for i in range(n_players)] + [Bot(f'b{i}', f'B{i}', 1000) for i in range(bots)]
    with quiet():
        for p in ps: t.add_player(p)
    server.tables[t.id] = t
    server.next_round_votes.pop(t.id, None)
    return t, ps

def connect(player):
    client = server.socketio.test_client(server.app)
    sid = server.socketio.server.manager.sid_from_eio_sid(client.eio_sid, '/')
    server.player_sessions[sid] = {'player_id': player.id}
    return client

def vote(client, table):
    with quiet():
        client.emit('vote_next_round', {'table_id': table.id})
    return client.get_received()

# 1. 人机桌上唯一的真人在手牌进行中投票：不重开，底池和筹码不变
t, ps = setup(1, bots=1)
with quiet(): t.start_new_hand()
with quiet(): t.process_player_action(t.get_current_player().id, A.RAISE, 200)
pot, hand, chips = t.pot, t.hand_number, sum(p.chips for p in ps)
c = connect(ps[0])
got = vote(c, t)
check('手牌进行中投票不会开始新一手', t.hand_number == hand and t.game_stage == GameStage.PRE_FLOP)
check('手牌进行中投票不会清空底池', t.pot == pot and sum(p.chips for p in ps) + t.pot == 2000, (t.pot, pot))
check('手牌进行中投票收到错误提示', any(e['name'] == 'error' for e in got), [e['name'] for e in got])
check('手牌进行中的投票不被记录', not server.next_round_votes.get(t.id))
with quiet(): server.start_next_round(t.id)
check('start_next_round 在手牌进行中不执行', t.hand_number == hand and t.pot == pot)

# 2. 手牌结束后投票：开始新一手，断线玩家不发牌
t, ps = setup(3)
with quiet():
    t.start_new_hand()
    while t.game_stage != GameStage.FINISHED:
        t.process_player_action(t.get_current_player().id, A.FOLD)
ps[2].status = PlayerStatus.DISCONNECTED
hand = t.hand_number
c0, c1 = connect(ps[0]), connect(ps[1])
vote(c0, t)
check('只有部分玩家投票时不开局', t.hand_number == hand)
vote(c1, t)
check('全部投票后开始新一手', t.hand_number == hand + 1 and t.game_stage == GameStage.PRE_FLOP)
check('断线玩家不发牌且保持断线状态', ps[2].status == PlayerStatus.DISCONNECTED and ps[2].hole_cards == []
      and ps[2] not in t.hand_players, (ps[2].status, len(ps[2].hole_cards)))
check('玩家状态是 PlayerStatus 而不是字符串', all(isinstance(p.status, PlayerStatus) for p in ps),
      [p.status for p in ps])
check('在线玩家正常发牌', all(len(p.hole_cards) == 2 and p.status == PlayerStatus.PLAYING for p in ps[:2]))
check('当前行动者不是断线玩家', t.get_current_player() in ps[:2])

print('\n全部通过' if not fails else f'\n失败 {len(fails)} 项: {fails}')
sys.exit(1 if fails else 0)
