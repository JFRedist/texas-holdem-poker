"""
断线重连测试：弃牌的玩家重连后仍是弃牌，全下的玩家断线/重连后保留底池资格，
断线期间开始的新一手牌不给断线玩家发牌。
运行：python tests/test_reconnect.py
"""
import contextlib, io, os, sys
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
    for p, h in zip(t.hand_players, hole):
        p.hole_cards = cards(h)
    used = {(c.suit, c.rank) for h in hole for c in cards(h)} | {(c.suit, c.rank) for c in cards(board)}
    rest = [Card(s, r) for s in Suit for r in Rank if (s, r) not in used]
    t.deck.cards = rest + list(reversed(cards(board)))

def act(t, action, amount=0):
    p = t.get_current_player()
    with quiet():
        r = t.process_player_action(p.id, action, amount)
    return p, r

def reconnect(t, p):
    """与 app.py handle_join_table 重连分支相同的调用"""
    hand_in_progress = t.game_stage not in (GameStage.WAITING, GameStage.FINISHED)
    p.mark_reconnected(p in t._participants() and len(p.hole_cards) == 2, hand_in_progress)

def finish(t):
    with quiet():
        while t.game_stage != GameStage.FINISHED:
            r = t.process_game_flow()
            if t.game_stage == GameStage.FINISHED or not r:
                break
            p = t.get_current_player()
            if p is None:
                continue
            t.process_player_action(p.id, A.CHECK if p.current_bet == t.current_bet else A.CALL)

# 1. 弃牌后刷新页面（断线+重连）不能复活
t, ps = make([1000, 1000, 1000])      # P0 庄家, P1 小盲, P2 大盲，翻前 P0 先行动
with quiet(): t.start_new_hand()
folder, _ = act(t, A.FOLD)
held = list(folder.hole_cards)
folder.mark_disconnected()
check('弃牌玩家断线后仍是弃牌', folder.status == PlayerStatus.FOLDED, folder.status)
reconnect(t, folder)
check('弃牌玩家重连后仍是弃牌', folder.status == PlayerStatus.FOLDED, folder.status)
check('弃牌玩家重连后不在争夺底池的玩家中',
      folder not in [p for p in t.players if p.status in (PlayerStatus.PLAYING, PlayerStatus.ALL_IN)])

# 2. 全下玩家断线、重连都保留底池资格，牌最大时赢下底池
t, ps = make([200, 1000, 1000])       # P0 短码
with quiet(): t.start_new_hand()
rig(t, ['As Ah', 'Kd Kc', '7h 2d'], '9s 5c 3d Jh 4s')
shove, _ = act(t, A.ALL_IN)
check('全下成功', shove is ps[0] and shove.status == PlayerStatus.ALL_IN, shove.status)
shove.mark_disconnected()
check('全下玩家断线后仍有底池资格', shove.status == PlayerStatus.ALL_IN, shove.status)
reconnect(t, shove)
check('全下玩家重连后不会被当成破产', shove.status == PlayerStatus.ALL_IN, shove.status)
act(t, A.CALL)
act(t, A.CALL)
finish(t)
check('全下玩家重连后赢得主池', ps[0].chips == 600, ps[0].chips)

# 3. 全下玩家断线期间牌局结束，仍能赢得底池
t, ps = make([200, 1000, 1000])
with quiet(): t.start_new_hand()
rig(t, ['As Ah', 'Kd Kc', '7h 2d'], '9s 5c 3d Jh 4s')
shove, _ = act(t, A.ALL_IN)
shove.mark_disconnected()
act(t, A.CALL)
act(t, A.CALL)
finish(t)
check('全下玩家断线期间摊牌仍赢得主池', ps[0].chips == 600, ps[0].chips)

# 4. 仍需行动的玩家断线后重连：同一手牌内恢复为游戏中
t, ps = make([1000, 1000, 1000])
with quiet(): t.start_new_hand()
p = t.get_current_player()
p.mark_disconnected()
check('待行动玩家断线标记为断线', p.status == PlayerStatus.DISCONNECTED, p.status)
reconnect(t, p)
check('待行动玩家同一手牌内重连恢复游戏中', p.status == PlayerStatus.PLAYING, p.status)

# 5. 弃牌后断线，下一手牌不发牌；重连后等待下一手
t, ps = make([1000, 1000, 1000])
with quiet(): t.start_new_hand()
folder, _ = act(t, A.FOLD)
folder.mark_disconnected()
act(t, A.FOLD)                        # 只剩大盲，本手结束
finish(t)
with quiet(): ok = t.start_new_hand()
check('断线玩家不参与下一手牌', ok and folder not in t.hand_players and folder.status == PlayerStatus.DISCONNECTED,
      folder.status)
reconnect(t, folder)
check('断线玩家在别人的牌局中重连后等待下一手', folder.status == PlayerStatus.WAITING and folder.hole_cards == [],
      folder.status)

print()
print('全部通过' if not fails else f'{len(fails)} 项失败: {fails}')
sys.exit(1 if fails else 0)
