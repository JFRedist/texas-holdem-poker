"""
机器人策略场景测试：固定牌面下检查各等级的决策是否合理。
运行：python tests/test_bot_strategy.py
"""
import contextlib, io, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from poker_engine.bot import Bot, BotLevel
from poker_engine.player import Player, PlayerStatus, PlayerAction as A
from poker_engine.card import Card, Suit, Rank

fails = []
def check(name, cond, info=''):
    print(('PASS ' if cond else 'FAIL ') + name + (f'  [{info}]' if info and not cond else ''))
    if not cond: fails.append(name)

DECK = [Card(s, r) for s in Suit for r in Rank]
RK = {'A': 14, 'K': 13, 'Q': 12, 'J': 11, 'T': 10}
SU = {'s': Suit.SPADES, 'h': Suit.HEARTS, 'd': Suit.DIAMONDS, 'c': Suit.CLUBS}
def cards(text):
    return [next(c for c in DECK if c.rank.numeric_value == (RK.get(t[0]) or int(t[0])) and c.suit == SU[t[1]])
            for t in text.split()]

def bot(level, hole, chips=1000, bet=0):
    b = Bot('me', 'me', chips, level)
    b.hole_cards = cards(hole); b.status = PlayerStatus.PLAYING; b.current_bet = bet
    return b

def opp(hole, status=PlayerStatus.PLAYING, chips=1000, pid='o'):
    p = Player(pid, pid, chips); p.hole_cards = cards(hole); p.status = status
    return p

def state(board, me, others, pot=200, current_bet=0, bb=20):
    return {'community_cards': cards(board), 'current_bet': current_bet, 'to_call': max(0, current_bet - me.current_bet),
            'big_blind': bb, 'pot_size': pot, 'min_bet': bb, 'min_raise_to': current_bet + max(bb, current_bet),
            'active_players': 1 + len(others), 'num_opponents': len(others), 'position': 'middle',
            'all_players': [me] + others}

def decide(b, gs):
    with contextlib.redirect_stdout(io.StringIO()):
        return b.decide_action(gs)

# ===== 德州扑克之神 =====
me = bot(BotLevel.GOD, '2s 2h'); o = opp('Ac Ad')
act = decide(me, state('Kd 7c 3h', me, [o]))
check('之神：22 对 AA（同为一对）不再误判领先而下注', act[0] == A.CHECK, act)
act = decide(me, state('Kd 7c 3h', me, [o], pot=200, current_bet=150))
check('之神：22 面对 AA 的下注弃牌', act[0] == A.FOLD, act)

me = bot(BotLevel.GOD, 'Qs Qh'); o = opp('Kh Ks', PlayerStatus.ALL_IN, chips=0)
act = decide(me, state('Kd 7c 3h', me, [o]))
check('之神：不忽略已全下的对手（QQ 对暗三 K 不下注）', act[0] == A.CHECK, act)

me = bot(BotLevel.GOD, 'Ah 5h'); o = opp('Ks Kd')
act = decide(me, state('Kh 9h 2c', me, [o], pot=100, current_bet=30))   # 坚果同花听牌对暗三：约 26% 胜率 > 赔率 23%
check('之神：听牌胜率高于底池赔率时跟注（考虑后面的牌）', act[0] == A.CALL, act)
act = decide(me, state('Kh 9h 2c', me, [o], pot=100, current_bet=100))  # 需要 50% 胜率
check('之神：听牌胜率低于底池赔率时弃牌', act[0] == A.FOLD, act)

me = bot(BotLevel.GOD, 'As Ad'); o = opp('Kc Qc')
act = decide(me, state('Ah 7d 2s', me, [o]))
check('之神：大幅领先时主动下注', act[0] in (A.BET, A.RAISE, A.ALL_IN), act)
act = decide(me, state('Ah 7d 2s', me, [o], pot=200, current_bet=100))
check('之神：大幅领先面对下注时加注', act[0] in (A.RAISE, A.ALL_IN), act)

o_allin = opp('Kc Qc', PlayerStatus.ALL_IN, chips=0)
act = decide(me, state('Ah 7d 2s', me, [o_allin]))
check('之神：对手都已全下时不再下注', act[0] == A.CHECK, act)

me = bot(BotLevel.GOD, '7s 2h'); o = opp('Ac Ad')
act = decide(me, state('', me, [o], pot=30, current_bet=20, bb=20))
check('之神：翻牌前 72 对 AA 弃牌', act[0] == A.FOLD, act)

# ===== 翻牌前评分 =====
score = lambda h: bot(BotLevel.BEGINNER, h)._evaluate_preflop_hand()
order = ['As Ah', 'Ks Kh', 'As Ks', 'Qs Js', '2s 2h', '5s 4s', '7s 2h']
scores = [score(h) for h in order]
check('翻牌前评分排序 AA > KK > AKs > QJs > 22 > 54s > 72o', scores == sorted(scores, reverse=True), [round(x, 2) for x in scores])
check('AKs 不再高于 AA、QJs 不再等于 KK', score('As Ks') < score('As Ah') and score('Qs Js') < score('Ks Kh') - 0.2)

# ===== 中级 / 初级：翻牌前 =====
def preflop_state(me, n_opp, current_bet=20, pot=30, position='early'):
    others = [opp('2c 3d', pid=f'o{i}') for i in range(n_opp)]
    gs = state('', me, others, pot=pot, current_bet=current_bet)
    gs['position'] = position
    return gs
random.seed(0)
me = bot(BotLevel.INTERMEDIATE, 'As Ah')
acts = {decide(me, preflop_state(me, 5))[0] for _ in range(10)}
check('中级：多人局 AA 翻牌前加注', acts <= {A.RAISE, A.ALL_IN}, acts)
me = bot(BotLevel.INTERMEDIATE, '7s 2h')
acts = {decide(me, preflop_state(me, 5, current_bet=60, pot=90))[0] for _ in range(10)}
check('中级：72o 面对加注弃牌', acts == {A.FOLD}, acts)
me = bot(BotLevel.BEGINNER, '7s 2h')
acts = {decide(me, preflop_state(me, 3))[0] for _ in range(10)}
check('初级：72o 面对大盲弃牌', acts == {A.FOLD}, acts)
me = bot(BotLevel.BEGINNER, 'As Ah')
acts = {decide(me, preflop_state(me, 3))[0] for _ in range(20)}
check('初级：AA 不会弃牌', A.FOLD not in acts, acts)

print('\n全部通过' if not fails else f'\n失败 {len(fails)} 项: {fails}')
