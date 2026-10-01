"""
机器人强度基准（复式赛制）：两个等级单挑，每副牌打两次——第二次互换座位与底牌，
公共牌完全相同，以抵消拿牌运气。每手牌开始时双方筹码重置为 100 个大盲，
统计每 100 手赢得的大盲数（bb/100，正数表示前者更强）及其标准误差。
运行：python tests/bench_bot_strength.py [每组牌数，默认 500，实际手数为其两倍]
"""
import contextlib, io, math, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
time.sleep = lambda s: None  # 去掉机器人思考延迟
from poker_engine.table import Table, GameStage
from poker_engine.bot import Bot, BotLevel

DEALS = int(sys.argv[1]) if len(sys.argv) > 1 else 500
BB = 20
STACK = 100 * BB
PAIRS = [(BotLevel.GOD, BotLevel.ADVANCED), (BotLevel.ADVANCED, BotLevel.INTERMEDIATE),
         (BotLevel.INTERMEDIATE, BotLevel.BEGINNER), (BotLevel.ADVANCED, BotLevel.BEGINNER)]


def play_hand(first, second, deck_seed):
    """first 坐 0 号位（第一手牌的庄家），用 deck_seed 洗牌，返回每名玩家的输赢"""
    t = Table('bench', 'bench', BB // 2, BB, 2, STACK)
    with contextlib.redirect_stdout(io.StringIO()):
        for bot in (first, second):
            bot.chips = STACK
            t.add_player(bot)
        t.deck.rng = random.Random(deck_seed)
        t.start_new_hand()           # 洗牌、发底牌；之后发公共牌按同一副牌的顺序
        guard = 0
        while t.game_stage != GameStage.FINISHED and guard < 20:
            guard += 1
            t.process_bot_actions()
    return {first.id: first.chips - STACK, second.id: second.chips - STACK}


def match(level_a, level_b, deals, seed):
    rng = random.Random(seed)
    random.seed(seed)
    a, b = Bot('a', 'A', STACK, level_a), Bot('b', 'B', STACK, level_b)
    results = []
    for _ in range(deals):
        deck_seed = rng.randrange(1 << 30)
        r1 = play_hand(a, b, deck_seed)[a.id]
        r2 = play_hand(b, a, deck_seed)[a.id]
        results.append((r1 + r2) / BB)  # 一副牌两次合计赢得的大盲数
    mean = sum(results) / len(results)
    sd = math.sqrt(sum((x - mean) ** 2 for x in results) / (len(results) - 1))
    # 每副牌是 2 手，换算成每 100 手
    return mean / 2 * 100, sd / math.sqrt(len(results)) / 2 * 100


if __name__ == '__main__':
    pairs = PAIRS
    if len(sys.argv) > 3:
        # 指定两个等级：python tests/bench_bot_strength.py 500 advanced intermediate
        pairs = [(BotLevel(sys.argv[2]), BotLevel(sys.argv[3]))]
    for la, lb in pairs:
        start = time.time()
        result, err = match(la, lb, DEALS, 1)
        print(f'{la.value:>12} vs {lb.value:<12} {result:+8.1f} ± {err:4.1f} bb/100   '
              f'({DEALS * 2} 手, {time.time() - start:.0f}s)', flush=True)
