"""
胜率模块测试：eval7 与 HandEvaluator 比牌结果一致、已知场景胜率正确、性能达标。
运行：python tests/test_equity.py
"""
import os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from poker_engine.card import Card, Suit, Rank
from poker_engine.hand_evaluator import HandEvaluator
from poker_engine.equity import eval7, cards_to_ints, equity_vs_random, equity_vs_known, preflop_equity

fails = []
def check(name, cond, info=''):
    print(('PASS ' if cond else 'FAIL ') + name + (f'  [{info}]' if info and not cond else ''))
    if not cond: fails.append(name)

DECK = [Card(s, r) for s in Suit for r in Rank]
RK = {'A': 14, 'K': 13, 'Q': 12, 'J': 11, 'T': 10}
SU = {'s': Suit.SPADES, 'h': Suit.HEARTS, 'd': Suit.DIAMONDS, 'c': Suit.CLUBS}
def cards(text):
    out = []
    for t in text.split():
        value = RK.get(t[0]) or int(t[0])
        out.append(next(c for c in DECK if c.rank.numeric_value == value and c.suit == SU[t[1]]))
    return out

# 1. 与参考评估器逐对比较
rng = random.Random(1)
mismatch = 0
for _ in range(20000):
    cs = rng.sample(DECK, 9)
    board, h1, h2 = cs[:5], cs[5:7], cs[7:9]
    ref = HandEvaluator.compare_hands(HandEvaluator.evaluate_hand(h1, board), HandEvaluator.evaluate_hand(h2, board))
    a, b = eval7(cards_to_ints(h1 + board)), eval7(cards_to_ints(h2 + board))
    mismatch += ((a > b) - (a < b)) != ref
check('eval7 与 HandEvaluator 比牌结果一致（2 万对）', mismatch == 0, mismatch)

# 2. 牌型内比较点数与踢脚（原先只比牌型大类，一对 2 和一对 A 被判平局）
check('一对 A 大于一对 2', eval7(cards_to_ints(cards('As Ah Kd 7c 3h 9s 4d'))) > eval7(cards_to_ints(cards('2s 2h Kd 7c 3h 9s 4d'))))
check('A-5 顺子小于 2-6 顺子', eval7(cards_to_ints(cards('As 2h 3d 4c 5h Ks Qd'))) < eval7(cards_to_ints(cards('6s 2h 3d 4c 5h Ks Qd'))))

# 3. 已知场景胜率
e = equity_vs_random(cards('As Ah'), cards('Kd 7c 3h'), 1, 4000, random.Random(2))['equity']
check('AA 在 K73 翻牌对 1 人胜率约 0.87', abs(e - 0.87) < 0.03, e)
e = equity_vs_known(cards('2s 2h'), [cards('Ac Ad')], cards('Kd 7c 3h'))
check('22 对 AA（K73 翻牌）精确胜率约 0.084', abs(e - 0.084) < 0.01, e)
e = equity_vs_known(cards('Qs Qh'), [cards('Kh Ks')], cards('Kd 7c 3h'))
check('QQ 对暗三 K 胜率很低', e < 0.05, e)
check('翻牌前 AA > KK > AKs > 22 > 72o（单挑）',
      preflop_equity(cards('As Ah'), 1) > preflop_equity(cards('Ks Kh'), 1) > preflop_equity(cards('As Ks'), 1)
      > preflop_equity(cards('2s 2h'), 1) > preflop_equity(cards('7s 2h'), 1))

# 4. 性能：高级机器人一次决策（1500 次、5 个对手）应远低于 1 秒
t = time.time()
equity_vs_random(cards('As Ah'), cards('Kd 7c 3h'), 5, 1500)
dt = time.time() - t
check(f'1500 次模拟 × 5 个对手耗时 {dt:.2f}s < 0.5s', dt < 0.5, dt)

print('\n全部通过' if not fails else f'\n失败 {len(fails)} 项: {fails}')
