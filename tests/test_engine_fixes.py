"""
引擎修复测试：机器人严格按顺序行动、记牌花色统计、洗牌随机源、大盲不被跳过、牌桌状态锁。
运行：python tests/test_engine_fixes.py
"""
import contextlib, io, os, random, secrets, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
time.sleep = lambda s: None  # 去掉机器人思考延迟
from poker_engine.table import Table, GameStage
from poker_engine.bot import Bot, BotLevel
from poker_engine.card import Card, Deck, Suit, Rank
from poker_engine.player import Player, PlayerAction as A

quiet = lambda: contextlib.redirect_stdout(io.StringIO())
fails = []
def check(name, cond, info=''):
    print(('PASS ' if cond else 'FAIL ') + name + (f'  [{info}]' if info and not cond else ''))
    if not cond: fails.append(name)

# 1. 纯机器人桌：每个机器人都在轮到自己时才行动，一次 process_bot_actions 就能打完一手牌
out_of_turn = []
_orig_execute = Table._execute_action
def _record_execute(self, player, action, amount=0, strict=True):
    if self.get_current_player() is not player:
        out_of_turn.append((player.nickname, action.value, self.game_stage.value))
    return _orig_execute(self, player, action, amount, strict)
Table._execute_action = _record_execute
random.seed(11)
unfinished = 0
for g in range(30):
    t = Table('t', 't', 10, 20, 9, 1000)
    t.deck.rng = random.Random(g)
    bots = [Bot(f'b{i}', f'B{i}', 1000, BotLevel.BEGINNER) for i in range(6)]
    with quiet():
        for b in bots: t.add_player(b)
        t.start_new_hand()
        t.process_bot_actions()
    if t.game_stage != GameStage.FINISHED:
        unfinished += 1
Table._execute_action = _orig_execute
check('机器人只在轮到自己时行动（不再有循环上限后的乱序补充处理）', not out_of_turn, out_of_turn[:3])
check('纯机器人桌一次处理就能打完一手牌', unfinished == 0, unfinished)

# 2. 记牌：公共牌的花色会从剩余张数中扣除
t = Table('t', 't', 10, 20, 9, 1000)
t.community_cards = [Card(Suit.HEARTS, Rank.ACE), Card(Suit.HEARTS, Rank.KING), Card(Suit.SPADES, Rank.TWO)]
info = t.get_card_tracking_info()['remaining_cards']
check('记牌按花色扣减', info['suits'].get('♥') == 11 and info['suits'].get('♠') == 12 and info['suits'].get('♦') == 13,
      info['suits'])
check('记牌按点数扣减', info['ranks']['A'] == 3 and info['ranks']['2'] == 3 and info['total_remaining'] == 49)

# 3. 洗牌默认使用系统随机源（不可预测），也可以注入固定随机源以便复现
check('默认洗牌随机源为 SystemRandom', isinstance(Deck().rng, secrets.SystemRandom))
d1, d2 = Deck(rng=random.Random(5)), Deck(rng=random.Random(5))
d1.shuffle(); d2.shuffle()
check('注入相同随机源洗牌结果相同', [str(c) for c in d1.cards] == [str(c) for c in d2.cards])
random.seed(1); a = Deck(); a.shuffle()
random.seed(1); b = Deck(); b.shuffle()
check('全局 random.seed 不能预测洗牌结果', [str(c) for c in a.cards] != [str(c) for c in b.cards])

# 4. 大盲按座位向前轮转，有人破产时不会有人跳过大盲
def make(n):
    t = Table('t', 't', 10, 20, max_players=9, initial_chips=1000)
    ps = [Player(f'p{i}', f'P{i}', 1000) for i in range(n)]
    with quiet():
        for p in ps: t.add_player(p)
    return t, ps

def blinds(t):
    return (next(p for p in t.players if p.is_dealer), next(p for p in t.players if p.is_small_blind),
            next(p for p in t.players if p.is_big_blind))

def new_hand(t):
    t.game_stage = GameStage.WAITING
    with quiet(): return t.start_new_hand()

t, ps = make(4)
new_hand(t)
d, sb, bb = blinds(t)
check('第一手：0 号位庄家，1 号小盲，2 号大盲', (d, sb, bb) == (ps[0], ps[1], ps[2]))
ps[1].chips = 0          # 小盲玩家破产
new_hand(t)
d, sb, bb = blinds(t)
check('小盲破产后，原 UTG（3 号）补上大盲而不是被跳过', bb is ps[3], bb.nickname)
check('原大盲（2 号）改交小盲', sb is ps[2], sb.nickname)

# 随机破产/补码：每手大盲都是上一手大盲之后的下一位有筹码玩家
random.seed(3)
err = None
for game in range(200):
    n = random.randint(3, 8)
    t, ps = make(n)
    new_hand(t)
    prev_bb = blinds(t)[2]
    for _ in range(30):
        for p in ps:
            if p is not prev_bb and random.random() < 0.15:
                p.chips = 0 if p.chips else 1000
        active = [p for p in ps if p.chips > 0]
        if len(active) < 2:
            break
        if not new_hand(t):
            break
        seats = t._seat_order()
        i = seats.index(prev_bb)
        expected = next(seats[(i + k) % len(seats)] for k in range(1, len(seats) + 1)
                        if seats[(i + k) % len(seats)].chips > 0 or seats[(i + k) % len(seats)].total_bet > 0)
        d, sb, bb = blinds(t)
        if bb is not expected:
            err = (game, bb.nickname, expected.nickname); break
        if len(t.hand_players) == 2 and d is not sb:
            err = ('heads-up dealer must be SB', game); break
        prev_bb = bb
    if err: break
check('随机破产后大盲总是交给上一位大盲之后的下一名玩家', err is None, err)

# 5. 牌桌状态锁：另一线程持有锁时，玩家动作要等锁释放后才执行
t, ps = make(3)
new_hand(t)
cur = t.get_current_player()
results = []
t.lock.acquire()
worker = threading.Thread(target=lambda: results.append(t.process_player_action(cur.id, A.CALL)))
with quiet():
    worker.start()
    worker.join(0.3)
    blocked = worker.is_alive() and not results
    t.lock.release()
    worker.join(2)
check('玩家动作在持有牌桌锁时等待', blocked and results and results[0]['success'])

print('\n全部通过' if not fails else f'\n失败 {len(fails)} 项: {fails}')
sys.exit(1 if fails else 0)
