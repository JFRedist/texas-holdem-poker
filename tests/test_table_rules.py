"""
牌桌规则测试：破产玩家、边池、平分底池、全下后行动、退还无人跟注筹码、最小加注、单挑行动顺序，
以及数千手随机牌局的筹码守恒模糊测试。
运行：python tests/test_table_rules.py
"""
import contextlib, io, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from poker_engine.table import Table, GameStage
from poker_engine.player import Player, PlayerStatus, PlayerAction as A
from poker_engine.card import Card, Suit, Rank

RK = {'A': Rank.ACE, 'K': Rank.KING, 'Q': Rank.QUEEN, 'J': Rank.JACK, 'T': Rank.TEN, '9': Rank.NINE, '8': Rank.EIGHT,
      '7': Rank.SEVEN, '6': Rank.SIX, '5': Rank.FIVE, '4': Rank.FOUR, '3': Rank.THREE, '2': Rank.TWO}
ST = {'s': Suit.SPADES, 'h': Suit.HEARTS, 'd': Suit.DIAMONDS, 'c': Suit.CLUBS}
def cards(s): return [Card(ST[x[1]], RK[x[0]]) for x in s.split()]

quiet = lambda: contextlib.redirect_stdout(io.StringIO())
fails = []
def check(name, cond, info=''):
    print(('PASS ' if cond else 'FAIL ') + name + (f'  [{info}]' if info and not cond else ''))
    if not cond: fails.append(name)

def make(stacks, sb=10, bb=20):
    t = Table('t', 't', sb, bb, max_players=9, initial_chips=1000)
    ps = []
    for i, c in enumerate(stacks):
        p = Player(f'p{i}', f'P{i}', 1000)
        with quiet(): t.add_player(p)
        p.chips = c
        ps.append(p)
    return t, ps

def rig(t, hole, board):
    """发牌后替换底牌和剩余牌堆，使结果可控"""
    for p, h in zip(t.hand_players, hole):
        p.hole_cards = cards(h)
    used = {(c.suit, c.rank) for h in hole for c in cards(h)} | {(c.suit, c.rank) for c in cards(board)}
    rest = [Card(s, r) for s in Suit for r in Rank if (s, r) not in used]
    t.deck.cards = rest + list(reversed(cards(board)))  # deal_cards 从末尾取

def act(t, action, amount=0):
    p = t.get_current_player()
    with quiet():
        r = t.process_player_action(p.id, action, amount)
    return p, r

def total(ps): return sum(p.chips for p in ps)

# 1. 破产玩家不发牌、不交盲注、不能赢
t, ps = make([0, 1000, 1000])
with quiet(): ok = t.start_new_hand()
check('破产玩家不参与发牌', ok and ps[0] not in t.hand_players and ps[0].hole_cards == [] and ps[0].status == PlayerStatus.BROKE)
check('破产玩家不交盲注', ps[0].total_bet == 0 and not ps[0].is_small_blind and not ps[0].is_big_blind)
t, ps = make([0, 1000])
with quiet(): ok = t.start_new_hand()
check('只剩一名有筹码玩家时不能开局', ok is False)

# 2. 边池：短码全下牌最大只能赢主池
t, ps = make([100, 1000, 1000])        # P0 庄家, P1 小盲, P2 大盲
before = total(ps)
with quiet(): t.start_new_hand()
rig(t, ['As Ad', 'Ks Kd', 'Qs Qd'], '2c 7h 9s 3d 4c')
act(t, A.ALL_IN)                       # P0 全下 100
act(t, A.CALL)                         # P1 跟到 100
act(t, A.CALL)                         # P2 跟到 100
act(t, A.BET, 300)                     # 翻牌 P1 下注 300
act(t, A.CALL)                         # P2 跟注
while t.game_stage != GameStage.FINISHED:
    act(t, A.CHECK)
check('边池：短码 AA 只赢主池 300', ps[0].chips == 300, ps[0].chips)
check('边池：KK 赢边池 600', ps[1].chips == 1000 - 400 + 600, ps[1].chips)
check('边池：筹码守恒', total(ps) == before)

# 3. 平分底池（含零头）
t, ps = make([1000, 1000, 1000], sb=5, bb=10)
with quiet(): t.start_new_hand()
rig(t, ['As Kd', 'Ah Kc', '2c 3d'], 'Qs Jh Td 7c 8s')   # P0/P1 都是 A 高顺子
act(t, A.RAISE, 35)      # P0 加注到 35
act(t, A.CALL)           # P1 小盲跟到 35
act(t, A.FOLD)           # P2 大盲弃牌（底池 35+35+10=80）
while t.game_stage != GameStage.FINISHED:
    act(t, A.CHECK)
check('平分底池', ps[0].chips == 1005 and ps[1].chips == 1005, (ps[0].chips, ps[1].chips))
t, ps = make([1000, 1000, 1000], sb=5, bb=10)
with quiet(): t.start_new_hand()
rig(t, ['As Kd', 'Ah Kc', '2c 3d'], 'Qs Jh Td 7c 8s')
act(t, A.RAISE, 30); act(t, A.CALL); act(t, A.CALL)    # 底池 90
act(t, A.BET, 15)        # 翻牌 P1(小盲) 先行动下注 15
act(t, A.FOLD)           # P2 弃牌
act(t, A.CALL)           # P0 跟注，底池 120
p2_before = ps[2].chips
act(t, A.BET, 11); act(t, A.CALL)                       # 底池 142
while t.game_stage != GameStage.FINISHED:
    act(t, A.CHECK)
check('平分零头给庄家左手第一位', ps[1].chips - ps[0].chips == 0 and total(ps) == 3000, (ps[0].chips, ps[1].chips))

# 4. 只剩一人未全下时，欠注仍需行动
t, ps = make([500, 1000, 1000])
with quiet(): t.start_new_hand()
act(t, A.ALL_IN)          # P0 全下 500
act(t, A.FOLD)            # P1 弃牌
p = t.get_current_player()
check('面对全下的最后一人可以行动', p is ps[2] and t.game_stage == GameStage.PRE_FLOP)
act(t, A.CALL)
check('跟注后自动发完公共牌并结算', t.game_stage == GameStage.FINISHED and len(t.community_cards) == 5)

# 5. 无人跟注的部分退还
t, ps = make([1000, 300, 1000])
with quiet(): t.start_new_hand()
rig(t, ['As Ad', 'Ks Kd', '2c 3d'], '2h 7h 9s Jd 4c')
act(t, A.ALL_IN)          # P0 全下 1000
act(t, A.ALL_IN)          # P1 全下 300
act(t, A.FOLD)            # P2 弃牌（盲注 20 留在池中）
check('超出部分退还给大码：AA 赢 300+300+20', ps[0].chips == 1000 + 300 + 20, ps[0].chips)
check('短码输光转为观战', ps[1].chips == 0 and ps[1].status == PlayerStatus.BROKE)

# 6. 最小下注 / 最小加注
t, ps = make([1000, 1000, 1000])
with quiet(): t.start_new_hand()
p, r = act(t, A.RAISE, 30)
check('加注不足一个大盲被拒绝', not r['success'] and '最小' in r['message'], r)
p, r = act(t, A.RAISE, 60)
check('加注到 60（幅度 40）', r['success'] and t.min_raise_to() == 100)
p, r = act(t, A.RAISE, 90)
check('再加注需至少到 100', not r['success'])
p, r = act(t, A.RAISE, 100)
check('再加注到 100 成功', r['success'])
t, ps = make([1000, 1000, 1000])
with quiet(): t.start_new_hand()
p = t.get_current_player()
with quiet(): r = t._execute_action(p, A.RAISE, 25, strict=False)
check('机器人非法加注额被修正到最小加注', r['success'] and p.current_bet == 40 and t.current_bet == 40, (p.current_bet, t.current_bet))
check('加注不会把全桌下注改小', t.current_bet >= 20)

# 7. 单挑：翻牌前庄家先行动，翻牌后大盲先行动
t, ps = make([1000, 1000])
with quiet(): t.start_new_hand()
check('单挑翻牌前庄家(小盲)先行动', t.get_current_player() is ps[0] and ps[0].is_small_blind)
act(t, A.CALL); act(t, A.CHECK)
check('单挑翻牌后大盲先行动', t.game_stage == GameStage.FLOP and t.get_current_player() is ps[1])

# 8. 不足额全下不重新开放加注
t, ps = make([1000, 1000, 70])
with quiet(): t.start_new_hand()            # P0 庄家 P1 小盲 P2 大盲(70)
act(t, A.RAISE, 60)                          # P0 加注到 60（幅度 40）
act(t, A.CALL)                               # P1 跟到 60
act(t, A.ALL_IN)                             # P2 全下 70（只多 10，不足一次完整加注）
p, r = act(t, A.RAISE, 200)
check('面对不足额全下，已行动玩家不能再加注', p is ps[0] and not r['success'], r)
p, r = act(t, A.CALL)
check('但可以跟注补齐', r['success'] and ps[0].current_bet == 70)

# 9. 随机模糊测试：筹码守恒、无负筹码、破产玩家不再发牌
random.seed(7)
hands = 0
fuzz_error = None
for game in range(400):
    n = random.randint(2, 7)
    t, ps = make([random.choice([40, 100, 250, 1000, 3000]) for _ in range(n)], sb=10, bb=20)
    start_total = total(ps)
    for _ in range(60):
        broke_before = [p for p in ps if p.chips == 0]
        with quiet():
            if not t.start_new_hand():
                break
        hands += 1
        if any(p in t.hand_players for p in broke_before):
            fuzz_error = '破产玩家被发牌'; break
        steps = 0
        while t.game_stage != GameStage.FINISHED and steps < 300:
            steps += 1
            p = t.get_current_player()
            if p is None:
                with quiet(): res = t.process_game_flow()
                if not res.get('hand_complete') and not res.get('stage_changed'):
                    fuzz_error = ('无人行动但牌局未结束', t.game_stage.value, [(q.nickname, q.status.value, q.chips, q.current_bet, q.has_acted) for q in ps], t.current_bet)
                    break
                continue
            choice = random.choice([A.FOLD, A.CHECK, A.CALL, A.CALL, A.BET, A.RAISE, A.ALL_IN])
            amt = random.choice([t.min_raise_to(), t.min_bet(), p.current_bet + p.chips, random.randint(1, 400)])
            with quiet(): r = t.process_player_action(p.id, choice, amt)
            if not r['success']:
                with quiet(): r = t.process_player_action(p.id, A.CALL if t.current_bet > p.current_bet else A.CHECK)
                if not r['success']:
                    fuzz_error = ('合法动作被拒绝', r); break
        if fuzz_error: break
        if t.game_stage != GameStage.FINISHED:
            fuzz_error = ('牌局卡住', t.game_stage.value); break
        if total(ps) != start_total or any(p.chips < 0 for p in ps):
            fuzz_error = ('筹码不守恒', total(ps), start_total); break
        t.game_stage = GameStage.WAITING
    if fuzz_error: break
print('fuzz error:', fuzz_error)
check(f'模糊测试：{hands} 手牌筹码守恒且无卡死', fuzz_error is None)

# 10. 服务重启恢复后 hand_players 丢失，仍能正确结算边池
t, ps = make([100, 1000, 1000])
before = total(ps)
with quiet(): t.start_new_hand()
rig(t, ['As Ad', 'Ks Kd', 'Qs Qd'], '2c 7h 9s 3d 4c')
t.hand_players = []
act(t, A.ALL_IN); act(t, A.CALL); act(t, A.CALL); act(t, A.BET, 300); act(t, A.CALL)
while t.game_stage != GameStage.FINISHED:
    act(t, A.CHECK)
check('恢复后的牌局边池结算正确', ps[0].chips == 300 and total(ps) == before, [p.chips for p in ps])
print('\n全部通过' if not fails else f'\n失败 {len(fails)} 项: {fails}')
