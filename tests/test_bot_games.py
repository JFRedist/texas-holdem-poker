"""
机器人对局测试：纯机器人连续打牌，检查不卡死、筹码守恒。
运行：python tests/test_bot_games.py
"""
import contextlib, io, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
time.sleep = lambda s: None
from poker_engine.table import Table, GameStage
from poker_engine.bot import Bot, BotLevel
from poker_engine.player import PlayerStatus, PlayerAction as A

# 统计机器人请求的非法动作（需要牌桌修正的金额），按等级分别计数
illegal = {}
_orig_execute = Table._execute_action
def _checked_execute(self, player, action, amount=0, strict=True):
    if not strict:
        owe = self.current_bet - player.current_bet
        max_to = player.current_bet + player.chips
        bad = ((action == A.CHECK and owe > 0)
               or (action == A.BET and (self.current_bet > 0 or (amount < self.min_bet() and amount < max_to)))
               or (action == A.RAISE and (self.current_bet == 0 or (amount < self.min_raise_to() and amount < max_to))))
        key = player.bot_level.value
        total, wrong = illegal.get(key, (0, 0))
        illegal[key] = (total + 1, wrong + bad)
    return _orig_execute(self, player, action, amount, strict)
Table._execute_action = _checked_execute
random.seed(3)
levels = [BotLevel.BEGINNER, BotLevel.INTERMEDIATE, BotLevel.ADVANCED, BotLevel.GOD]
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
print('illegal bot actions by level (total, illegal):', illegal)
bad_levels = {k: v for k, v in illegal.items() if v[1] and k != 'god'}
print('PASS 机器人只请求合法的下注/加注金额' if not bad_levels and err is None else f'FAIL 非法动作 {bad_levels} / {err}')
