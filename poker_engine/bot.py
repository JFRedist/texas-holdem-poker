"""
机器人AI
Bot AI for poker game
"""

import random
from typing import List, Tuple, Dict, Optional
from enum import Enum
from .player import Player, PlayerAction, PlayerStatus
from .card import Card, Suit, Rank
from .hand_evaluator import HandEvaluator, HandRank
from .equity import equity_vs_random, equity_vs_known, preflop_equity
import itertools
import math


class BotLevel(Enum):
    """机器人等级"""
    BEGINNER = "beginner"  # 初级
    INTERMEDIATE = "intermediate"  # 中级
    ADVANCED = "advanced"  # 高级
    GOD = "god"  # 德州扑克之神 (能看到所有手牌)


class Bot(Player):
    """机器人玩家类"""
    
    def __init__(self, player_id: str, nickname: str, chips: int = 1000, level: BotLevel = BotLevel.BEGINNER):
        """
        初始化机器人
        
        Args:
            player_id: 机器人ID
            nickname: 机器人昵称
            chips: 初始筹码
            level: 机器人等级
        """
        super().__init__(player_id, nickname, chips, is_bot=True)
        self.bot_level = level
        self.opponent_patterns = {}  # 对手行为统计（由牌桌在每次行动后更新，高级机器人据此建模）
        self.session_stats = {'hands_played': 0}
    
    def decide_action(self, game_state: Dict) -> Tuple[PlayerAction, int]:
        """
        根据游戏状态决定下一步动作
        
        Args:
            game_state: 游戏状态字典，包含公共牌、底池、当前下注等信息
            
        Returns:
            Tuple[PlayerAction, int]: (动作类型, 下注金额)
        """
        # 检查基本状态
        if self.chips <= 0:
            return PlayerAction.FOLD, 0
        
        if self.status not in [PlayerStatus.PLAYING, PlayerStatus.ALL_IN]:
            return PlayerAction.FOLD, 0
        
        try:
            if self.bot_level == BotLevel.BEGINNER:
                result = self._beginner_strategy(game_state)
            elif self.bot_level == BotLevel.INTERMEDIATE:
                result = self._intermediate_strategy(game_state)
            elif self.bot_level == BotLevel.ADVANCED:
                result = self._advanced_strategy(game_state)
            elif self.bot_level == BotLevel.GOD:
                result = self._god_strategy(game_state)
            else:
                result = self._advanced_strategy(game_state)
            
            # 验证返回结果
            if result and len(result) == 2:
                action_type, amount = result
                # 确保动作类型有效
                if isinstance(action_type, PlayerAction) and isinstance(amount, (int, float)):
                    return action_type, int(amount)
            
            # 如果策略返回无效结果，使用兜底策略
            print(f"🤖 {self.nickname} 策略返回无效结果: {result}，使用兜底策略")
            return self._fallback_strategy(game_state)
            
        except Exception as e:
            print(f"🤖 {self.nickname} 决策异常: {e}，使用兜底策略")
            return self._fallback_strategy(game_state)
    
    def _bet(self, game_state: Dict, amount: int) -> Tuple[PlayerAction, int]:
        """无需跟注时主动下注 amount（不低于最小下注，超过筹码则全下）"""
        if game_state.get('current_bet', 0) > 0:
            # 桌上已有下注但自己已跟平（如翻牌前大盲的选择权）：主动下注即加注
            return self._raise(game_state, amount)
        amount = max(int(amount), game_state.get('min_bet', game_state.get('big_blind', 20)))
        if amount >= self.chips:
            return PlayerAction.ALL_IN, self.chips
        return PlayerAction.BET, amount

    def _raise(self, game_state: Dict, raise_by: int) -> Tuple[PlayerAction, int]:
        """
        在当前下注基础上加注 raise_by。返回的金额是「加注到」的总额（牌桌的约定），
        不低于最小加注，筹码不够时全下
        """
        current_bet = game_state.get('current_bet', 0)
        raise_to = max(current_bet + int(raise_by), game_state.get('min_raise_to', current_bet * 2))
        if raise_to - self.current_bet >= self.chips:
            return PlayerAction.ALL_IN, self.chips
        return PlayerAction.RAISE, raise_to

    def _fallback_strategy(self, game_state: Dict) -> Tuple[PlayerAction, int]:
        """兜底策略：确保总是返回有效动作"""
        current_bet = game_state.get('current_bet', 0)
        call_amount = current_bet - self.current_bet
        pot_size = game_state.get('pot_size', 0)
        
        # 如果无需跟注，就过牌
        if call_amount <= 0:
            return PlayerAction.CHECK, 0
        
        # 如果跟注金额超过筹码，就弃牌
        if call_amount >= self.chips:
            return PlayerAction.FOLD, 0
        
        # 计算底池赔率
        pot_odds = call_amount / (pot_size + call_amount) if (pot_size + call_amount) > 0 else 1
        
        # 如果是合理的跟注（考虑底池赔率和筹码比例），就跟注
        if call_amount <= self.chips * 0.25 or pot_odds < 0.33:  # 增加跟注阈值到25%，或底池赔率好
            return PlayerAction.CALL, call_amount
        
        # 否则弃牌
        return PlayerAction.FOLD, 0
    
    def _beginner_strategy(self, game_state: Dict) -> Tuple[PlayerAction, int]:
        """
        初级机器人策略：保守型，较少诈唬
        """
        if self.chips <= 0:
            return PlayerAction.FOLD, 0
            
        community_cards = game_state.get('community_cards', [])
        current_bet = game_state.get('current_bet', 0)
        big_blind = game_state.get('big_blind', 20)
        pot_size = game_state.get('pot_size', 0)
        
        # 评估手牌强度
        if len(community_cards) >= 3:
            hand_rank, _ = HandEvaluator.evaluate_hand(self.hole_cards, community_cards)
            hand_strength = hand_rank.rank_value / 10.0
        else:
            hand_strength = self._evaluate_preflop_hand()
        
        call_amount = current_bet - self.current_bet
        
        # 无需跟注的情况
        if call_amount == 0:
            if hand_strength > 0.7:  # 强牌才下注（新手下注尺度小：最小下注）
                return self._bet(game_state, big_blind)
            else:
                return PlayerAction.CHECK, 0
        
        # 需要跟注的情况
        if call_amount > self.chips:
            if hand_strength > 0.8:  # 只有非常强的牌才全下
                return PlayerAction.ALL_IN, self.chips
            else:
                return PlayerAction.FOLD, 0
        
        # 根据手牌强度决定 - 调整为更合理的阈值
        
        # 计算底池赔率
        pot_odds = call_amount / (pot_size + call_amount) if (pot_size + call_amount) > 0 else 1
        
        # 更宽松的弃牌阈值，避免过度弃牌
        if hand_strength < 0.15:  # 只有最垃圾的牌才弃牌
            return PlayerAction.FOLD, 0
        elif hand_strength < 0.35:
            # 边际牌：考虑底池赔率和随机性
            if pot_odds > 0.3:  # 底池赔率好的时候弃牌
                return PlayerAction.FOLD, 0
            elif random.random() < 0.7:  # 70% 跟注
                return PlayerAction.CALL, call_amount
            else:
                return PlayerAction.FOLD, 0
        elif hand_strength < 0.6:
            # 中等牌：基本跟注
            if random.random() < 0.85:  # 85% 跟注
                return PlayerAction.CALL, call_amount
            else:
                return PlayerAction.FOLD, 0
        else:
            # 强牌：跟注或加注
            if random.random() < 0.4:  # 40% 最小加注
                return self._raise(game_state, 0)
            else:
                return PlayerAction.CALL, call_amount
    
    def _intermediate_strategy(self, game_state: Dict) -> Tuple[PlayerAction, int]:
        """
        中级机器人策略：真实胜率 + 底池赔率。
        equity：对当前对手人数的真实胜率，用于和底池赔率比较（是否值得跟注）；
        strength：牌力，用于决定是否主动下注/加注——翻牌前取单挑胜率（否则多人局里连 AA 都不加注），
        翻牌后取蒙特卡洛胜率。
        """
        if self.chips <= 0:
            return PlayerAction.FOLD, 0

        community_cards = game_state.get('community_cards', [])
        pot_size = game_state.get('pot_size', 0)
        num_opponents = game_state.get('num_opponents', max(1, game_state.get('active_players', 2) - 1))
        position = game_state.get('position', 'middle')
        call_amount = game_state.get('to_call', max(0, game_state.get('current_bet', 0) - self.current_bet))

        if len(community_cards) >= 3:
            equity = self._improved_monte_carlo(community_cards, num_opponents, 1000)
            strength = equity
        else:
            equity = self._preflop_win_rate(num_opponents)
            strength = preflop_equity(self.hole_cards, 1)

        # 位置调整：后位信息更多，可以打得更宽一些
        position_bonus = {'early': -0.03, 'middle': 0, 'late': 0.03}.get(position, 0)
        strength = max(0.0, min(1.0, strength + position_bonus))

        # 无需跟注
        if call_amount == 0:
            if strength > 0.65:
                # 价值下注
                return self._bet(game_state, self._calculate_bet_size(pot_size, strength, 'value'))
            elif strength > 0.4 and len(community_cards) >= 3 and random.random() < 0.15:
                # 小概率半诈唬
                return self._bet(game_state, self._calculate_bet_size(pot_size, strength, 'bluff'))
            return PlayerAction.CHECK, 0

        pot_odds = call_amount / (pot_size + call_amount) if (pot_size + call_amount) > 0 else 1

        # 跟注即全下
        if call_amount >= self.chips:
            return (PlayerAction.ALL_IN, self.chips) if equity > pot_odds * 1.1 else (PlayerAction.FOLD, 0)

        if equity > pot_odds + 0.05:
            if strength > 0.75:
                # 强牌大幅加注：加注幅度按跟注后的底池计算
                return self._raise(game_state, self._calculate_bet_size(pot_size + call_amount, strength, 'value'))
            if strength > 0.62 and random.random() < 0.4:
                # 较强的牌有时最小加注
                return self._raise(game_state, 0)
            return PlayerAction.CALL, call_amount
        if equity > pot_odds - 0.03 and random.random() < 0.3:
            # 边际情况偶尔跟注，避免过于好读
            return PlayerAction.CALL, call_amount
        return PlayerAction.FOLD, 0

    def _advanced_strategy(self, game_state: Dict) -> Tuple[PlayerAction, int]:
        """
        高级机器人策略：真实胜率 + 对手建模 + 位置 + 筹码深度。
        - 面对下注时，按下注者的风格修正胜率（紧的玩家下注时范围更强，激进的玩家诈唬更多）
        - 翻牌前按位置决定开池范围，强牌再加注
        - 翻牌后价值下注按胜率定尺度；听牌半诈唬；河牌诈唬频率按下注尺度与对手弃牌倾向计算
        - 筹码越深，边缘牌跟注要求的胜率余量越大
        """
        if self.chips <= 0:
            return PlayerAction.FOLD, 0

        board = game_state.get('community_cards', [])
        pot = game_state.get('pot_size', 0)
        big_blind = game_state.get('big_blind', 20)
        num_opponents = game_state.get('num_opponents', max(1, game_state.get('active_players', 2) - 1))
        position = game_state.get('position', 'middle')
        call_amount = game_state.get('to_call', max(0, game_state.get('current_bet', 0) - self.current_bet))
        preflop = len(board) < 3

        opponents = [p for p in game_state.get('all_players', []) if p.id != self.id
                     and p.status in (PlayerStatus.PLAYING, PlayerStatus.ALL_IN)]
        profiles = [self._opponent_profile(p.id) for p in opponents] or [self._opponent_profile(None)]
        avg_tightness = sum(pr['tightness'] for pr in profiles) / len(profiles)

        if preflop:
            strength = preflop_equity(self.hole_cards, 1)
            equity = preflop_equity(self.hole_cards, num_opponents)
        else:
            equity = equity_vs_random(self.hole_cards, board, num_opponents, 1500)['equity']
            strength = equity

        # 面对下注：下注者的范围比随机手牌强，按其风格折算胜率
        if call_amount > 0 and opponents:
            aggressor = max(opponents, key=lambda p: p.current_bet)
            profile = self._opponent_profile(aggressor.id)
            factor = 0.85 - 0.3 * (profile['tightness'] - 0.5) + 0.2 * (profile['aggression'] - 0.5)
            equity *= max(0.6, min(1.0, factor))

        spr = self.chips / max(pot, big_blind)
        margin = 0.03 + 0.05 * min(spr, 10) / 10  # 筹码越深，边缘跟注越谨慎

        # ---------- 无需跟注 ----------
        if call_amount == 0:
            if preflop:
                # 翻牌前（大盲选择权或平跟的底池）：按位置的开池标准加注
                open_threshold = {'early': 0.64, 'middle': 0.60, 'late': 0.56}.get(position, 0.60)
                if strength >= open_threshold:
                    return self._bet(game_state, max(pot, 2 * big_blind))
                return PlayerAction.CHECK, 0
            value_threshold = 0.55 if avg_tightness < 0.4 else 0.6  # 对跟注站可以更薄地价值下注
            if equity >= 0.8:
                return self._bet(game_state, pot * 0.9)
            if equity >= value_threshold:
                return self._bet(game_state, pot * (0.5 + (equity - value_threshold)))
            if len(board) < 5 and 0.3 <= equity < value_threshold and num_opponents <= 2:
                # 听牌/中等牌半诈唬：后位更积极
                if random.random() < (0.3 if position == 'late' else 0.15):
                    return self._bet(game_state, pot * 0.5)
            if len(board) == 5 and equity < 0.2 and num_opponents <= 2:
                # 河牌诈唬：诈唬占下注范围的比例 b/(p+2b)，再乘以对手弃牌倾向
                bet = pot * 0.66
                if random.random() < avg_tightness * bet / (pot + 2 * bet):
                    return self._bet(game_state, bet)
            return PlayerAction.CHECK, 0

        # ---------- 面对下注 ----------
        pot_odds = call_amount / (pot + call_amount)
        if call_amount >= self.chips:
            # 跟注即全下：只看胜率是否够，不做「诈唬跟注」
            return (PlayerAction.ALL_IN, self.chips) if equity > pot_odds else (PlayerAction.FOLD, 0)

        if preflop:
            if strength >= 0.72:
                # QQ+、AK 等强牌再加注（约 3 倍）
                return self._raise(game_state, pot + call_amount)
            open_threshold = {'early': 0.62, 'middle': 0.58, 'late': 0.55}.get(position, 0.58)
            if call_amount <= big_blind and strength >= open_threshold:
                # 无人加注的底池：按位置开池加注
                return self._raise(game_state, pot + call_amount)
            if equity > pot_odds + margin:
                return PlayerAction.CALL, call_amount
            return PlayerAction.FOLD, 0

        if equity >= 0.75:
            return self._raise(game_state, (pot + call_amount) * 0.75)
        if equity > pot_odds + margin:
            return PlayerAction.CALL, call_amount
        if (len(board) >= 4 and num_opponents == 1 and position == 'late' and equity < 0.15
                and self._opponent_profile(opponents[0].id if opponents else None)['aggression'] > 0.6
                and random.random() < 0.05):
            # 对激进对手偶尔用空气牌加注反诈唬
            return self._raise(game_state, (pot + call_amount) * 0.75)
        return PlayerAction.FOLD, 0

    def _evaluate_preflop_hand(self) -> float:
        """
        翻牌前牌力（0~1）：由对 1 名随机对手的真实胜率线性换算，
        72o（约 35%）≈ 0.09，22（约 50%）≈ 0.36，AKs（约 67%）≈ 0.67，AA（约 85%）= 1
        """
        if len(self.hole_cards) != 2:
            return 0.0
        return max(0.0, min(1.0, (preflop_equity(self.hole_cards, 1) - 0.30) / 0.55))

    def _preflop_win_rate(self, num_opponents: int) -> float:
        """翻牌前对 num_opponents 名随机对手的真实胜率"""
        if len(self.hole_cards) != 2:
            return 0.0
        return preflop_equity(self.hole_cards, num_opponents)

    def _improved_monte_carlo(self, community_cards: List[Card], num_opponents: int, simulations: int = 1000) -> float:
        """蒙特卡洛胜率：完整比较牌型、点数与踢脚，平局按人数分摊"""
        if len(self.hole_cards) != 2:
            return 0.0
        return equity_vs_random(self.hole_cards, community_cards, num_opponents, simulations)['equity']

    def _calculate_bet_size(self, pot_size: int, win_prob: float, bet_type: str) -> int:
        """计算下注大小（中级机器人使用）"""
        if bet_type == 'value':
            # 价值下注：根据胜率调整大小
            if win_prob > 0.8:
                return int(pot_size * 0.8)  # 强牌大注
            elif win_prob > 0.65:
                return int(pot_size * 0.6)  # 中等牌中注
            else:
                return int(pot_size * 0.4)  # 弱牌小注
        elif bet_type == 'bluff':
            # 诈唬下注：通常较大
            return int(pot_size * 0.7)
        else:
            return int(pot_size * 0.5)

    # ---------- 对手建模 ----------

    def observe_new_hand(self, opponent_ids: List[str]):
        """新一手牌开始：记录本手牌参与的对手，用于统计入池率等"""
        self.session_stats['hands_played'] += 1
        for pid in opponent_ids:
            pattern = self._pattern(pid)
            pattern['hands'] += 1
            pattern['vpip_this_hand'] = False
            pattern['pfr_this_hand'] = False

    def update_opponent_pattern(self, player_id: str, action: PlayerAction, amount: int, context: Dict):
        """
        记录对手的一次行动（由牌桌在每次行动后调用）。
        统计：主动入池（翻牌前跟注/下注/加注）、翻牌前加注、激进行动（下注/加注/全下）与被动行动（跟注）
        """
        pattern = self._pattern(player_id)
        preflop = context.get('stage') == 'pre_flop'
        if action in (PlayerAction.CALL, PlayerAction.BET, PlayerAction.RAISE, PlayerAction.ALL_IN):
            if preflop and not pattern['vpip_this_hand']:
                pattern['vpip'] += 1
                pattern['vpip_this_hand'] = True
        if action in (PlayerAction.BET, PlayerAction.RAISE, PlayerAction.ALL_IN):
            pattern['aggressive'] += 1
            if preflop and not pattern['pfr_this_hand']:
                pattern['pfr'] += 1
                pattern['pfr_this_hand'] = True
        elif action == PlayerAction.CALL:
            pattern['passive'] += 1
        elif action == PlayerAction.FOLD:
            pattern['folds'] += 1

    def _pattern(self, player_id: str) -> Dict:
        if player_id not in self.opponent_patterns:
            self.opponent_patterns[player_id] = {
                'hands': 0, 'vpip': 0, 'pfr': 0, 'aggressive': 0, 'passive': 0, 'folds': 0,
                'vpip_this_hand': False, 'pfr_this_hand': False
            }
        return self.opponent_patterns[player_id]

    def _opponent_profile(self, player_id: Optional[str]) -> Dict[str, float]:
        """
        对手画像（带先验，样本少时接近平均玩家）：
        tightness = 1 - 入池率（先验入池率 30%），aggression = 激进行动占比（先验 50%）
        """
        pattern = self.opponent_patterns.get(player_id) if player_id else None
        if not pattern:
            return {'tightness': 0.7, 'aggression': 0.5}
        vpip_rate = (pattern['vpip'] + 1.5) / (pattern['hands'] + 5)
        aggression = (pattern['aggressive'] + 1) / (pattern['aggressive'] + pattern['passive'] + 2)
        return {'tightness': 1 - vpip_rate, 'aggression': aggression}

    def _god_strategy(self, game_state: Dict) -> Tuple[PlayerAction, int]:
        """
        德州扑克之神：能看到所有玩家的底牌。
        对所有仍在牌局中的对手（含已全下者）计算精确胜率（翻牌后穷举剩余公共牌，翻牌前抽样），
        弃牌玩家的底牌作为死牌排除，再按胜率与底池赔率决策。
        """
        if self.chips <= 0:
            return PlayerAction.FOLD, 0

        community_cards = game_state.get('community_cards', [])
        pot_size = game_state.get('pot_size', 0)
        big_blind = game_state.get('big_blind', 20)
        call_amount = game_state.get('to_call', max(0, game_state.get('current_bet', 0) - self.current_bet))
        all_players = game_state.get('all_players', [])

        opponents = [p for p in all_players if p.id != self.id and len(p.hole_cards) == 2
                     and p.status in (PlayerStatus.PLAYING, PlayerStatus.ALL_IN)]
        folded = [c for p in all_players if p.id != self.id and p.status == PlayerStatus.FOLDED for c in p.hole_cards]
        if not opponents:
            return (PlayerAction.CHECK, 0) if call_amount == 0 else (PlayerAction.CALL, call_amount)

        equity = equity_vs_known(self.hole_cards, [p.hole_cards for p in opponents], community_cards,
                                 dead_cards=folded)
        # 还能继续下注的对手（已全下的对手不会再跟注，对他们下注没有意义）
        can_respond = [p for p in opponents if p.status == PlayerStatus.PLAYING and p.chips > 0]
        print(f"🔮 德州扑克之神 {self.nickname}: 对 {len(opponents)} 名对手的真实胜率 {equity:.1%}")

        if call_amount == 0:
            if not can_respond:
                return PlayerAction.CHECK, 0
            if equity >= 0.8:
                return self._bet(game_state, pot_size)              # 大幅领先：满池下注榨取价值
            if equity >= 0.6:
                return self._bet(game_state, pot_size * 0.6)        # 领先：中等下注
            if len(community_cards) >= 4 and equity < 0.25 and random.random() < 0.2:
                # 转牌/河牌落后时偶尔诈唬，让对手无法通过「下注=领先」读牌
                return self._bet(game_state, pot_size * 0.6)
            return PlayerAction.CHECK, 0

        pot_odds = call_amount / (pot_size + call_amount)
        if call_amount >= self.chips:
            # 跟注即全下：胜率高于赔率就跟
            return (PlayerAction.ALL_IN, self.chips) if equity > pot_odds else (PlayerAction.FOLD, 0)
        if equity >= 0.75 and can_respond:
            return self._raise(game_state, pot_size + call_amount)  # 大幅领先：加注一个底池
        if equity > pot_odds:
            return PlayerAction.CALL, call_amount                    # 赔率合适：跟注
        return PlayerAction.FOLD, 0

    def to_dict(self, include_hole_cards: bool = False) -> dict:
        """扩展父类方法，增加机器人特有信息"""
        data = super().to_dict(include_hole_cards)
        data['bot_level'] = self.bot_level.value
        return data 