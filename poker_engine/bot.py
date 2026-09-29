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
        self.hand_history = []  # 手牌历史
        self.opponent_patterns = {}  # 对手行为模式
        self.session_stats = {  # 会话统计
            'hands_played': 0,
            'vpip': 0,  # 主动入池率
            'pfr': 0,   # 翻前加注率
            'aggression_factor': 1.0,
            'showdown_wins': 0,
            'total_showdowns': 0
        }
    
    def decide_action(self, game_state: Dict) -> Tuple[PlayerAction, int]:
        """
        根据游戏状态决定下一步动作
        
        Args:
            game_state: 游戏状态字典，包含公共牌、底池、当前下注等信息
            
        Returns:
            Tuple[PlayerAction, int]: (动作类型, 下注金额)
        """
        # 更新统计数据
        self.session_stats['hands_played'] += 1
        
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
        中级机器人策略：改进的蒙特卡洛模拟，考虑底池赔率和位置
        """
        if self.chips <= 0:
            return PlayerAction.FOLD, 0
            
        community_cards = game_state.get('community_cards', [])
        current_bet = game_state.get('current_bet', 0)
        big_blind = game_state.get('big_blind', 20)
        pot_size = game_state.get('pot_size', 0)
        num_opponents = game_state.get('num_opponents', max(1, game_state.get('active_players', 2) - 1))
        position = game_state.get('position', 'middle')

        # 改进的胜率计算
        if len(community_cards) >= 3:
            win_probability = self._improved_monte_carlo(community_cards, num_opponents, 1000)
        else:
            # Pre-flop 胜率表
            win_probability = self._preflop_win_rate(num_opponents)
        
        # 位置调整
        position_bonus = {'early': -0.05, 'middle': 0, 'late': 0.08}.get(position, 0)
        adjusted_win_prob = max(0.05, min(0.95, win_probability + position_bonus))
        
        call_amount = current_bet - self.current_bet
        
        # 无需跟注
        if call_amount == 0:
            if adjusted_win_prob > 0.65:
                # 价值下注
                return self._bet(game_state, self._calculate_bet_size(pot_size, adjusted_win_prob, 'value'))
            elif adjusted_win_prob > 0.25 and random.random() < 0.15:
                # 小概率诈唬
                return self._bet(game_state, self._calculate_bet_size(pot_size, adjusted_win_prob, 'bluff'))
            else:
                return PlayerAction.CHECK, 0
        
        # 全下场景
        if call_amount >= self.chips:
            pot_odds = self.chips / (pot_size + self.chips)
            if adjusted_win_prob > pot_odds * 1.2:  # 需要较好的胜率
                return PlayerAction.ALL_IN, self.chips
            else:
                return PlayerAction.FOLD, 0
        
        # 计算底池赔率
        pot_odds = call_amount / (pot_size + call_amount) if (pot_size + call_amount) > 0 else 1
        
        # 决策逻辑
        if adjusted_win_prob > pot_odds + 0.1:
            if adjusted_win_prob > 0.75:
                # 强牌大幅加注：加注幅度按跟注后的底池计算
                return self._raise(game_state, self._calculate_bet_size(pot_size + call_amount, adjusted_win_prob, 'value'))
            elif adjusted_win_prob > 0.55:
                # 中等牌小幅（最小）加注或跟注
                if random.random() < 0.4 and self.chips > call_amount:
                    return self._raise(game_state, 0)
                return PlayerAction.CALL, call_amount
            else:
                return PlayerAction.CALL, call_amount
        elif adjusted_win_prob > pot_odds - 0.05:
            # 边际决策
            if random.random() < 0.3:
                return PlayerAction.CALL, call_amount
            else:
                return PlayerAction.FOLD, 0
        else:
            return PlayerAction.FOLD, 0
    
    def _advanced_strategy(self, game_state: Dict) -> Tuple[PlayerAction, int]:
        """
        高级机器人策略：GTO近似策略，对手建模，动态调整
        """
        if self.chips <= 0:
            return PlayerAction.FOLD, 0
            
        community_cards = game_state.get('community_cards', [])
        current_bet = game_state.get('current_bet', 0)
        big_blind = game_state.get('big_blind', 20)
        pot_size = game_state.get('pot_size', 0)
        num_opponents = game_state.get('num_opponents', max(1, game_state.get('active_players', 2) - 1))
        position = game_state.get('position', 'middle')
        betting_round = len(community_cards)
        stack_to_pot_ratio = self.chips / max(pot_size, big_blind)
        
        # 高级胜率计算
        if len(community_cards) >= 3:
            win_probability = self._advanced_monte_carlo(community_cards, num_opponents, 1500)
            hand_equity = self._calculate_hand_equity(community_cards)
        else:
            win_probability = self._advanced_preflop_strategy(num_opponents, position)
            hand_equity = win_probability
        
        # 对手建模调整
        opponent_adjustment = self._analyze_opponents(game_state)
        adjusted_win_prob = max(0.05, min(0.95, win_probability + opponent_adjustment))
        
        # 位置和筹码深度调整
        position_factor = {'early': 0.85, 'middle': 1.0, 'late': 1.15}.get(position, 1.0)
        stack_factor = min(1.2, max(0.8, math.log(stack_to_pot_ratio + 1) / 2))
        
        call_amount = current_bet - self.current_bet
        
        # 诈唬频率计算 (基于GTO理论)
        bluff_frequency = self._calculate_optimal_bluff_frequency(pot_size, call_amount, position)
        should_bluff = (random.random() < bluff_frequency and 
                       adjusted_win_prob < 0.35 and 
                       betting_round >= 3)
        
        # 无需跟注的情况
        if call_amount == 0:
            if should_bluff:
                return self._bet(game_state, self._calculate_optimal_bet_size(pot_size, 'bluff', position))
            elif adjusted_win_prob * position_factor > 0.6:
                return self._bet(game_state, self._calculate_optimal_bet_size(pot_size, 'value', position))
            elif adjusted_win_prob > 0.3 and random.random() < 0.2:
                # 小频率的阻挡下注
                return self._bet(game_state, int(0.3 * pot_size))
            else:
                return PlayerAction.CHECK, 0
        
        # 全下场景
        if call_amount >= self.chips:
            # 考虑隐含赔率
            implied_odds = self._calculate_implied_odds(game_state)
            effective_win_prob = adjusted_win_prob + implied_odds
            pot_odds = self.chips / (pot_size + self.chips)
            
            if effective_win_prob > pot_odds * 1.1 or should_bluff:
                return PlayerAction.ALL_IN, self.chips
            else:
                return PlayerAction.FOLD, 0
        
        # 正常下注场景
        pot_odds = call_amount / (pot_size + call_amount) if (pot_size + call_amount) > 0 else 1
        
        if should_bluff:
            # 诈唬策略
            if random.random() < 0.6:  # 60% 加注诈唬
                return self._raise(game_state, self._calculate_optimal_bet_size(pot_size + call_amount, 'bluff', position))
            return PlayerAction.CALL, call_amount
        
        # 价值策略
        if adjusted_win_prob * position_factor * stack_factor > pot_odds + 0.15:
            if adjusted_win_prob > 0.8:
                # 坚果牌，大幅加注
                return self._raise(game_state, self._calculate_optimal_bet_size(pot_size + call_amount, 'nuts', position))
            elif adjusted_win_prob > 0.65:
                # 强牌，适度加注
                if random.random() < 0.7:
                    return self._raise(game_state, self._calculate_optimal_bet_size(pot_size + call_amount, 'value', position))
                return PlayerAction.CALL, call_amount
            else:
                return PlayerAction.CALL, call_amount
        elif adjusted_win_prob * position_factor > pot_odds:
            # 边际价值，倾向跟注
            if random.random() < 0.6:
                return PlayerAction.CALL, call_amount
            else:
                return PlayerAction.FOLD, 0
        else:
            # 胜率不足，弃牌
            return PlayerAction.FOLD, 0
    
    def _evaluate_preflop_hand(self) -> float:
        """
        评估Pre-flop手牌强度
        
        Returns:
            float: 手牌强度 (0-1)
        """
        if len(self.hole_cards) != 2:
            return 0.0
        
        card1, card2 = self.hole_cards
        rank1, rank2 = card1.rank.numeric_value, card2.rank.numeric_value
        suited = card1.suit == card2.suit
        
        # 对子评估
        if rank1 == rank2:
            if rank1 >= 13:  # KK, AA
                return 0.85 + (rank1 - 13) * 0.05
            elif rank1 >= 10:  # TT, JJ, QQ
                return 0.7 + (rank1 - 10) * 0.05
            elif rank1 >= 7:  # 77, 88, 99
                return 0.5 + (rank1 - 7) * 0.05
            else:  # 22-66
                return 0.25 + (rank1 - 2) * 0.05
        
        # 非对子评估
        high_rank = max(rank1, rank2)
        low_rank = min(rank1, rank2)
        gap = high_rank - low_rank
        
        base_strength = 0.0
        
        # 高牌价值 - 提高基础强度
        if high_rank == 14:  # A
            base_strength += 0.4
            if low_rank >= 10:  # AK, AQ, AJ, AT
                base_strength += 0.3
            elif low_rank >= 7:  # A9-A7
                base_strength += 0.2
            else:  # A6-A2
                base_strength += 0.1
        elif high_rank >= 12:  # K, Q
            base_strength += 0.3
            if low_rank >= 9:
                base_strength += 0.2
            elif low_rank >= 6:
                base_strength += 0.1
        elif high_rank >= 10:  # J, T
            base_strength += 0.25
            if low_rank >= 8:
                base_strength += 0.15
            elif low_rank >= 5:
                base_strength += 0.05
        else:  # 9及以下
            base_strength += 0.1  # 给所有牌一个基础价值
        
        # 连牌奖励
        if gap == 1:  # 连牌
            base_strength += 0.15
        elif gap == 2:  # 一个空档
            base_strength += 0.1
        elif gap == 3:  # 两个空档
            base_strength += 0.05
        
        # 同花奖励
        if suited:
            base_strength += 0.12
            if gap <= 3:  # 同花连牌
                base_strength += 0.08
        
        return min(0.92, base_strength)
    
    def _preflop_win_rate(self, num_opponents: int) -> float:
        """基于手牌和对手数量的预计算胜率表"""
        hand_strength = self._evaluate_preflop_hand()
        
        # 根据对手数量调整胜率
        opponent_factor = max(0.7, 1.0 - (num_opponents - 1) * 0.1)
        
        return hand_strength * opponent_factor
    
    def _improved_monte_carlo(self, community_cards: List[Card], num_opponents: int, simulations: int = 1000) -> float:
        """蒙特卡洛胜率：完整比较牌型、点数与踢脚，平局按人数分摊"""
        if len(self.hole_cards) != 2:
            return 0.0
        return equity_vs_random(self.hole_cards, community_cards, num_opponents, simulations)['equity']

    def _advanced_monte_carlo(self, community_cards: List[Card], num_opponents: int, simulations: int = 1500) -> float:
        """高级蒙特卡洛模拟，考虑对手范围"""
        base_win_rate = self._improved_monte_carlo(community_cards, num_opponents, simulations)
        
        # 根据对手紧松度调整
        avg_tightness = sum(pattern.get('tightness', 0.5) for pattern in self.opponent_patterns.values())
        avg_tightness = avg_tightness / len(self.opponent_patterns) if self.opponent_patterns else 0.5
        
        # 紧的对手通常有更强的范围
        tightness_adjustment = (avg_tightness - 0.5) * 0.1
        
        return max(0.05, min(0.95, base_win_rate - tightness_adjustment))
    
    def _advanced_preflop_strategy(self, num_opponents: int, position: str) -> float:
        """高级翻前策略"""
        base_strength = self._evaluate_preflop_hand()
        
        # 位置调整
        position_bonus = {'early': -0.1, 'middle': 0, 'late': 0.15}.get(position, 0)
        
        # 对手数量调整
        opponent_penalty = (num_opponents - 1) * 0.08
        
        # 根据会话统计调整
        if self.session_stats['hands_played'] > 10:
            # 如果我们一直在输，变得更保守
            if self.session_stats.get('showdown_wins', 0) < self.session_stats.get('total_showdowns', 1) * 0.3:
                base_strength *= 0.9
        
        adjusted_strength = base_strength + position_bonus - opponent_penalty
        return max(0.05, min(0.95, adjusted_strength))
    
    def _calculate_bet_size(self, pot_size: int, win_prob: float, bet_type: str) -> int:
        """计算最优下注大小"""
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
    
    def _calculate_optimal_bet_size(self, pot_size: int, bet_type: str, position: str) -> int:
        """计算最优下注大小（高级版本）"""
        base_multiplier = {
            'value': 0.6,
            'bluff': 0.7,
            'nuts': 0.85,
            'blocking': 0.3
        }.get(bet_type, 0.5)
        
        # 位置调整
        position_multiplier = {'early': 0.9, 'middle': 1.0, 'late': 1.1}.get(position, 1.0)
        
        return max(10, int(pot_size * base_multiplier * position_multiplier))
    
    def _calculate_optimal_bluff_frequency(self, pot_size: int, bet_amount: int, position: str) -> float:
        """基于GTO理论计算最优诈唬频率"""
        if pot_size == 0:
            return 0.05
        
        # 基本GTO公式：诈唬频率 = 下注额 / (底池 + 下注额)
        base_frequency = bet_amount / (pot_size + bet_amount) if (pot_size + bet_amount) > 0 else 0.1
        
        # 位置调整
        position_bonus = {'early': -0.02, 'middle': 0, 'late': 0.03}.get(position, 0)
        
        return max(0.02, min(0.25, base_frequency + position_bonus))
    
    def _calculate_hand_equity(self, community_cards: List[Card]) -> float:
        """计算手牌权益"""
        if len(community_cards) < 3:
            return self._evaluate_preflop_hand()
        
        hand_rank, _ = HandEvaluator.evaluate_hand(self.hole_cards, community_cards)
        base_equity = hand_rank.rank_value / 10.0
        
        # 考虑听牌可能性
        if len(community_cards) < 5:
            draw_potential = self._calculate_draw_potential(community_cards)
            base_equity += draw_potential * 0.1
        
        return min(0.95, base_equity)
    
    def _calculate_draw_potential(self, community_cards: List[Card]) -> float:
        """计算听牌潜力"""
        potential = 0.0
        
        all_cards = self.hole_cards + community_cards
        
        # 检查同花听牌
        suit_counts = {}
        for card in all_cards:
            suit_counts[card.suit] = suit_counts.get(card.suit, 0) + 1
        
        max_suit_count = max(suit_counts.values()) if suit_counts else 0
        if max_suit_count == 4:  # 同花听牌
            potential += 0.4
        elif max_suit_count == 3:  # 可能的同花听牌
            potential += 0.1
        
        # 检查顺子听牌（简化版本）
        ranks = sorted([card.rank.numeric_value for card in all_cards])
        consecutive_count = 1
        max_consecutive = 1
        
        for i in range(1, len(ranks)):
            if ranks[i] == ranks[i-1] + 1:
                consecutive_count += 1
                max_consecutive = max(max_consecutive, consecutive_count)
            else:
                consecutive_count = 1
        
        if max_consecutive == 4:  # 顺子听牌
            potential += 0.3
        elif max_consecutive == 3:  # 可能的顺子听牌
            potential += 0.1
        
        return min(0.5, potential)
    
    def _analyze_opponents(self, game_state: Dict) -> float:
        """分析对手并调整策略"""
        if not self.opponent_patterns:
            return 0.0
        
        adjustment = 0.0
        
        # 分析平均对手紧松度
        avg_tightness = sum(p.get('tightness', 0.5) for p in self.opponent_patterns.values())
        avg_tightness = avg_tightness / len(self.opponent_patterns)
        
        # 对紧的对手更保守
        if avg_tightness > 0.7:
            adjustment -= 0.08
        elif avg_tightness < 0.3:
            adjustment += 0.05
        
        # 分析平均攻击性
        avg_aggression = sum(p.get('aggression', 0.5) for p in self.opponent_patterns.values())
        avg_aggression = avg_aggression / len(self.opponent_patterns)
        
        # 对激进的对手更小心
        if avg_aggression > 0.7:
            adjustment -= 0.05
        
        return adjustment
    
    def _calculate_implied_odds(self, game_state: Dict) -> float:
        """计算隐含赔率"""
        pot_size = game_state.get('pot_size', 0)
        
        # 估算对手剩余筹码
        opponent_stack_estimate = 0
        for pattern in self.opponent_patterns.values():
            # 这里可以根据对手历史行为估算其筹码量
            opponent_stack_estimate += 500  # 简化估算
        
        if pot_size == 0:
            return 0.0
        
        # 隐含赔率 = 潜在收益 / 当前底池
        implied_ratio = min(0.3, opponent_stack_estimate / (pot_size * 10))
        
        return implied_ratio
    
    def update_opponent_pattern(self, player_id: str, action: PlayerAction, amount: int, context: Dict):
        """
        更新对手行为模式记录
        
        Args:
            player_id: 对手ID
            action: 对手动作
            amount: 下注金额
            context: 游戏上下文
        """
        if player_id not in self.opponent_patterns:
            self.opponent_patterns[player_id] = {
                'aggression': 0.5,  # 攻击性
                'tightness': 0.5,   # 紧松度
                'bluff_frequency': 0.1,  # 诈唬频率
                'action_count': 0
            }
        
        pattern = self.opponent_patterns[player_id]
        pattern['action_count'] += 1
        
        # 更新攻击性
        if action in [PlayerAction.BET, PlayerAction.RAISE]:
            pattern['aggression'] = min(1.0, pattern['aggression'] + 0.05)
        elif action == PlayerAction.FOLD:
            pattern['aggression'] = max(0.0, pattern['aggression'] - 0.02)
        
        # 更新紧松度
        if action == PlayerAction.FOLD:
            pattern['tightness'] = min(1.0, pattern['tightness'] + 0.03)
        elif action in [PlayerAction.CALL, PlayerAction.BET, PlayerAction.RAISE]:
            pattern['tightness'] = max(0.0, pattern['tightness'] - 0.02)
    
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