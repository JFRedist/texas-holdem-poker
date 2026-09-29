"""
机器人强度基准：不同等级单挑对战，每手牌开始时双方筹码重置为 100 个大盲，
统计每 100 手赢得的大盲数（bb/100，正数表示前者更强）。
运行：python tests/bench_bot_strength.py [每组手数，默认 300]
"""
import contextlib, io, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
time.sleep = lambda s: None  # 去掉机器人思考延迟
from poker_engine.table import Table, GameStage
from poker_engine.bot import Bot, BotLevel

HANDS = int(sys.argv[1]) if len(sys.argv) > 1 else 300
BB = 20
PAIRS = [(BotLevel.GOD, BotLevel.ADVANCED), (BotLevel.ADVANCED, BotLevel.INTERMEDIATE),
         (BotLevel.INTERMEDIATE, BotLevel.BEGINNER), (BotLevel.ADVANCED, BotLevel.BEGINNER)]


def match(level_a, level_b, hands, seed):
    random.seed(seed)
    t = Table('bench', 'bench', BB // 2, BB, 2, 100 * BB)
    a, b = Bot('a', 'A', 100 * BB, level_a), Bot('b', 'B', 100 * BB, level_b)
    with contextlib.redirect_stdout(io.StringIO()):
        t.add_player(a); t.add_player(b)
    net = 0
    for _ in range(hands):
        a.chips = b.chips = 100 * BB
        with contextlib.redirect_stdout(io.StringIO()):
            t.game_stage = GameStage.WAITING
            t.start_new_hand()
            guard = 0
            while t.game_stage != GameStage.FINISHED and guard < 20:
                guard += 1
                t.process_bot_actions()
        net += a.chips - 100 * BB
    return net / BB / hands * 100


if __name__ == '__main__':
    for la, lb in PAIRS:
        start = time.time()
        # 两个随机种子各打一半，减少单一序列的运气成分
        result = (match(la, lb, HANDS // 2, 1) + match(la, lb, HANDS - HANDS // 2, 2)) / 2
        print(f'{la.value:>12} vs {lb.value:<12} {result:+8.1f} bb/100   ({HANDS} 手, {time.time() - start:.0f}s)', flush=True)
