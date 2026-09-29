"""
机器人对局测试：纯机器人连续打牌，检查不卡死、筹码守恒。
运行：python tests/test_bot_games.py
"""
import contextlib, io, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
time.sleep = lambda s: None
from poker_engine.table import Table, GameStage
from poker_engine.bot import Bot, BotLevel
from poker_engine.player import PlayerStatus
random.seed(3)
levels = [BotLevel.BEGINNER, BotLevel.INTERMEDIATE, BotLevel.GOD]
hands = 0; err = None
for g in range(12):
    t = Table('t', 't', 10, 20, 9, 1000)
    bots = [Bot(f'b{i}', f'B{i}', 1000, random.choice(levels)) for i in range(random.randint(2, 5))]
    with contextlib.redirect_stdout(io.StringIO()):
        for b in bots: t.add_player(b)
        for b in bots: b.chips = random.choice([60, 300, 1000])
    start = sum(b.chips for b in bots)
    for h in range(25):
        with contextlib.redirect_stdout(io.StringIO()):
            if not t.start_new_hand(): break
            r = t.process_bot_actions()
            guard = 0
            while t.game_stage != GameStage.FINISHED and guard < 20:
                guard += 1; r = t.process_bot_actions()
        hands += 1
        if t.game_stage != GameStage.FINISHED: err = ('stuck', t.game_stage.value); break
        if sum(b.chips for b in bots) != start: err = ('chips', sum(b.chips for b in bots), start); break
        t.game_stage = GameStage.WAITING
    if err: break
print('bot hands:', hands, 'error:', err)
