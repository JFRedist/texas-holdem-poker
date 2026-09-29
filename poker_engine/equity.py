"""
胜率（权益）计算
Equity calculation for bots and helper tools

- eval7: 快速的 5~7 张牌评估，返回可直接比较大小的元组（牌型 + 点数/踢脚），
  牌型编号与 HandRank 一致（1 高牌 … 9 同花顺，10 皇家同花顺）
- equity_vs_random: 对若干名随机手牌对手的蒙特卡洛胜率
- equity_vs_known: 已知所有对手底牌时的精确胜率（剩余公共牌可穷举时穷举，否则抽样）
- preflop_equity: 翻牌前胜率，按手牌类型（点数 + 是否同花）与对手人数缓存
"""

import itertools
import random
from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Tuple

from .card import Card, Suit

_SUIT_INDEX = {Suit.HEARTS: 0, Suit.DIAMONDS: 1, Suit.CLUBS: 2, Suit.SPADES: 3}
FULL_DECK = [rank * 4 + suit for rank in range(2, 15) for suit in range(4)]


def card_to_int(card: Card) -> int:
    """牌编码为整数：点数 * 4 + 花色（点数 2~14）"""
    return card.rank.numeric_value * 4 + _SUIT_INDEX[card.suit]


def cards_to_ints(cards: Sequence[Card]) -> List[int]:
    return [card_to_int(c) for c in cards]


def _straight_high(rank_set) -> int:
    """返回顺子的最大点数（A-2-3-4-5 返回 5），没有顺子返回 0"""
    for high in range(14, 5, -1):
        if (high in rank_set and high - 1 in rank_set and high - 2 in rank_set
                and high - 3 in rank_set and high - 4 in rank_set):
            return high
    if 14 in rank_set and 2 in rank_set and 3 in rank_set and 4 in rank_set and 5 in rank_set:
        return 5
    return 0


def eval7(cards: Sequence[int]) -> Tuple[int, ...]:
    """评估 5~7 张牌中最好的五张，返回 (牌型, 关键点数...)，元组越大牌越大"""
    rank_count = [0] * 15
    suit_ranks: List[List[int]] = [[], [], [], []]
    for c in cards:
        r = c >> 2
        rank_count[r] += 1
        suit_ranks[c & 3].append(r)

    for ranks in suit_ranks:
        if len(ranks) >= 5:
            high = _straight_high(set(ranks))
            if high:
                return (10,) if high == 14 else (9, high)
            flush = sorted(ranks, reverse=True)[:5]
            flush_hand = (6, *flush)
            break
    else:
        flush_hand = None

    quads, trips, pairs, singles = [], [], [], []
    for r in range(14, 1, -1):
        n = rank_count[r]
        if n == 4:
            quads.append(r)
        elif n == 3:
            trips.append(r)
        elif n == 2:
            pairs.append(r)
        elif n == 1:
            singles.append(r)

    if quads:
        kicker = max([r for r in range(14, 1, -1) if rank_count[r] and r != quads[0]] or [0])
        return (8, quads[0], kicker)
    if trips and (len(trips) > 1 or pairs):
        pair = max(trips[1:] + pairs)
        return (7, trips[0], pair)
    if flush_hand:
        return flush_hand
    high = _straight_high({r for r in range(2, 15) if rank_count[r]})
    if high:
        return (5, high)
    if trips:
        return (4, trips[0], *sorted(singles + pairs, reverse=True)[:2])
    if len(pairs) >= 2:
        kicker = max(pairs[2:] + singles) if len(pairs) > 2 or singles else 0
        return (3, pairs[0], pairs[1], kicker)
    if pairs:
        return (2, pairs[0], *singles[:3])
    return (1, *singles[:5])


def _remaining_deck(known: Sequence[int]) -> List[int]:
    known_set = set(known)
    return [c for c in FULL_DECK if c not in known_set]


def _score(my_value, opp_values) -> float:
    """我的得分：独赢 1，与 k 人并列最大时 1/(k+1)，输 0"""
    best_opp = max(opp_values)
    if my_value > best_opp:
        return 1.0
    if my_value < best_opp:
        return 0.0
    return 1.0 / (1 + sum(1 for v in opp_values if v == my_value))


def equity_vs_random(hole: Sequence[Card], board: Sequence[Card], num_opponents: int,
                     iterations: int = 1000, rng: Optional[random.Random] = None) -> Dict[str, float]:
    """对 num_opponents 名随机手牌对手的蒙特卡洛胜率：{'equity', 'win', 'tie', 'lose'}"""
    rng = rng or random
    num_opponents = max(1, num_opponents)
    my_cards = cards_to_ints(hole)
    board_ints = cards_to_ints(board)
    deck = _remaining_deck(my_cards + board_ints)
    need_board = 5 - len(board_ints)
    need = need_board + 2 * num_opponents
    if need > len(deck):
        num_opponents = (len(deck) - need_board) // 2
        need = need_board + 2 * num_opponents

    wins = ties = 0
    equity = 0.0
    for _ in range(iterations):
        draw = rng.sample(deck, need)
        full_board = board_ints + draw[:need_board]
        mine = eval7(my_cards + full_board)
        opps = [eval7(draw[need_board + 2 * i: need_board + 2 * i + 2] + full_board) for i in range(num_opponents)]
        s = _score(mine, opps)
        equity += s
        if s == 1.0:
            wins += 1
        elif s > 0:
            ties += 1
    return {
        'equity': equity / iterations,
        'win': wins / iterations,
        'tie': ties / iterations,
        'lose': 1 - (wins + ties) / iterations,
    }


def equity_vs_known(hole: Sequence[Card], opponent_holes: Sequence[Sequence[Card]], board: Sequence[Card],
                    max_boards: int = 2000, rng: Optional[random.Random] = None,
                    dead_cards: Sequence[Card] = ()) -> float:
    """
    已知所有对手底牌时的胜率。剩余公共牌组合不超过 max_boards 时穷举（翻牌后），否则随机抽样（翻牌前）。
    dead_cards：已知不会再出现的牌（如弃牌玩家的底牌）。
    """
    rng = rng or random
    my_cards = cards_to_ints(hole)
    opp_cards = [cards_to_ints(h) for h in opponent_holes if len(h) == 2]
    if not opp_cards:
        return 1.0
    board_ints = cards_to_ints(board)
    deck = _remaining_deck(my_cards + board_ints + [c for h in opp_cards for c in h] + cards_to_ints(dead_cards))
    need = 5 - len(board_ints)

    if need == 0:
        runouts = [()]
    else:
        total = 1
        for i in range(need):
            total = total * (len(deck) - i) // (i + 1)
        if total <= max_boards:
            runouts = itertools.combinations(deck, need)
        else:
            runouts = (rng.sample(deck, need) for _ in range(max_boards))

    equity = 0.0
    count = 0
    for extra in runouts:
        full_board = board_ints + list(extra)
        mine = eval7(my_cards + full_board)
        equity += _score(mine, [eval7(h + full_board) for h in opp_cards])
        count += 1
    return equity / count if count else 0.0


def hand_class(hole: Sequence[Card]) -> Tuple[int, int, bool]:
    """翻牌前手牌类型：(大点数, 小点数, 是否同花)，共 169 种"""
    a, b = hole[0].rank.numeric_value, hole[1].rank.numeric_value
    return max(a, b), min(a, b), hole[0].suit == hole[1].suit and a != b


@lru_cache(maxsize=4096)
def _preflop_equity_cached(high: int, low: int, suited: bool, num_opponents: int) -> float:
    hole_ints = [high * 4 + 0, low * 4 + (0 if suited else 1)]
    rng = random.Random(high * 1000 + low * 10 + suited + num_opponents * 100000)
    deck = _remaining_deck(hole_ints)
    iterations = 6000  # 结果按手牌类型缓存，只算一次，多算一些降低抽样误差（约 ±0.6%）
    equity = 0.0
    need = 5 + 2 * num_opponents
    for _ in range(iterations):
        draw = rng.sample(deck, need)
        board = draw[:5]
        mine = eval7(hole_ints + board)
        opps = [eval7(draw[5 + 2 * i: 7 + 2 * i] + board) for i in range(num_opponents)]
        equity += _score(mine, opps)
    return equity / iterations


def preflop_equity(hole: Sequence[Card], num_opponents: int) -> float:
    """翻牌前对 num_opponents 名随机对手的胜率（结果缓存，同一手牌类型只算一次）"""
    high, low, suited = hand_class(hole)
    return _preflop_equity_cached(high, low, suited, max(1, min(num_opponents, 8)))
