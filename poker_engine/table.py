"""
牌桌管理类
Table management for poker game
"""

import uuid
import time
import random
from typing import List, Dict, Optional, Tuple
from enum import Enum
from .card import Card, Deck
from .player import Player, PlayerStatus, PlayerAction
from .bot import Bot, BotLevel
from .hand_evaluator import HandEvaluator, HandRank
from .equity import equity_vs_random


class GameStage(Enum):
    """游戏阶段枚举"""
    WAITING = "waiting"
    PRE_FLOP = "pre_flop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"
    FINISHED = "finished"


class Table:
    """牌桌类"""
    
    def __init__(self, table_id: str, title: str, small_blind: int = 10, 
                 big_blind: int = 20, max_players: int = 9, initial_chips: int = 1000,
                 game_mode: str = "blinds", ante_percentage: float = 0.02):
        self.id = table_id
        self.title = title
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.max_players = max_players
        self.initial_chips = initial_chips
        
        # 新增游戏模式参数
        self.game_mode = game_mode  # "blinds" 或 "ante"
        self.ante_percentage = ante_percentage  # 按比例下注的百分比 (例如 0.02 = 2%)
        
        self.players: List[Player] = []
        self.seats: Dict[int, Optional[Player]] = {i: None for i in range(max_players)}
        
        self.game_stage = GameStage.WAITING
        self.hand_number = 0
        self.deck = Deck()
        self.community_cards: List[Card] = []
        self.pot = 0
        self.current_bet = 0
        self.min_raise = big_blind if game_mode == "blinds" else max(1, int(initial_chips * ante_percentage))
        self.last_raise_size = self.min_raise  # 本轮最近一次完整加注的幅度（最小加注 = 当前下注 + 该值）
        self.hand_players: List[Player] = []   # 本手牌发到牌的玩家（按座位顺序），用于行动顺序与边池结算
        self.dealer_id: Optional[str] = None
        self.last_actor_id: Optional[str] = None  # 本街最近一次主动行动的玩家，下一位从其后开始找

        self.dealer_position = 0
        self.current_player_position = 0
        
        self.enable_win_probability = True
        self.enable_card_tracking = True
        
        self.created_at = time.time()
        self.last_activity = time.time()
        self.on_bot_action = None  # 机器人完成一次行动后的回调钩子（由app层设置，用于逐步广播）
    
    def add_player(self, player: Player) -> bool:
        """添加玩家到牌桌"""
        if len(self.players) >= self.max_players:
            return False
        
        seat_number = self._find_empty_seat()
        if seat_number is None:
            return False
        
        if player.chips == 0:
            player.chips = self.initial_chips
        
        self.players.append(player)
        self.seats[seat_number] = player
        player.status = PlayerStatus.WAITING
        
        self.last_activity = time.time()
        return True
    
    def remove_player(self, player_id: str) -> Optional[Player]:
        """从牌桌移除玩家"""
        player = self.get_player(player_id)
        if not player:
            return None
        
        # 从座位中移除
        for seat_num, seated_player in self.seats.items():
            if seated_player and seated_player.id == player_id:
                self.seats[seat_num] = None
                break
        
        # 从玩家列表中移除
        self.players = [p for p in self.players if p.id != player_id]
        
        self.last_activity = time.time()
        return player
    
    def _find_empty_seat(self) -> Optional[int]:
        """查找空座位"""
        for seat_num in range(self.max_players):
            if self.seats[seat_num] is None:
                return seat_num
        return None
    
    def _seat_order(self) -> List[Player]:
        """按座位号排列的玩家（不在座位表中的玩家排在最后）"""
        seated = [self.seats[i] for i in sorted(self.seats) if self.seats[i] is not None]
        seated = [p for p in seated if p in self.players]
        return seated + [p for p in self.players if p not in seated]

    def _participants(self) -> List[Player]:
        """本手牌的参与者（按座位顺序）。服务重启后从数据库恢复的牌局没有该记录，按是否持有底牌推断"""
        if self.hand_players:
            return self.hand_players
        return [p for p in self._seat_order() if len(p.hole_cards) == 2]
    
    def start_new_hand(self) -> bool:
        """开始新一手牌：只有在线且有筹码的玩家发牌，筹码为 0 的玩家转为观战（BROKE）"""
        ordered = self._seat_order()
        active_players = [p for p in ordered if p.status != PlayerStatus.DISCONNECTED and p.chips > 0]
        if len(active_players) < 2:
            return False

        # 庄家按座位顺序轮换到下一位有筹码的玩家（第一手牌为第一位）
        if self.dealer_id is None or self.hand_number == 0:
            dealer = active_players[0]
        else:
            prev = next((p for p in ordered if p.id == self.dealer_id), None)
            if prev is None:
                dealer = active_players[0]
            else:
                start = ordered.index(prev)
                dealer = next(ordered[(start + i) % len(ordered)] for i in range(1, len(ordered) + 1)
                              if ordered[(start + i) % len(ordered)] in active_players)
        self.dealer_id = dealer.id
        self.dealer_position = active_players.index(dealer)

        # 重置游戏状态
        self.community_cards = []
        self.pot = 0
        self.current_bet = 0
        self.last_raise_size = self.min_raise
        self.hand_number += 1
        self.game_stage = GameStage.PRE_FLOP  # 明确设置为PRE_FLOP阶段
        self.hand_players = active_players
        self.last_actor_id = None

        self.deck.reset()
        self.deck.shuffle()

        for player in self.players:
            if player in active_players:
                continue
            # 不参与本手牌的玩家：清空上一手的底牌和下注，破产玩家转为观战
            player.reset_for_new_hand()
            if player.status != PlayerStatus.DISCONNECTED:
                player.status = PlayerStatus.BROKE if player.chips <= 0 else PlayerStatus.WAITING

        for player in active_players:
            # 先重置玩家状态，再发牌（reset_for_new_hand 会清除庄家/盲注标记）
            player.reset_for_new_hand()
            player.status = PlayerStatus.PLAYING
            hole_cards = self.deck.deal_cards(2)
            player.deal_hole_cards(hole_cards)

        # 清除所有玩家的位置标记（保险，防止残留）
        for player in self.players:
            player.is_dealer = False
            player.is_small_blind = False
            player.is_big_blind = False

        # 机器人记录本手牌的对手，用于统计入池率等
        for player in active_players:
            if isinstance(player, Bot):
                player.observe_new_hand([p.id for p in active_players if p is not player])

        # 设置当前庄家（必须在 reset 之后，否则标记会被重置）
        dealer.is_dealer = True
        print(f"🎯 庄家: {dealer.nickname} (位置 {self.dealer_position})")
        
        # 根据游戏模式收取初始下注
        if self.game_mode == "blinds":
            # 传统大小盲注模式：庄家下一位=小盲，再下一位=大盲（随庄家轮换）
            n = len(active_players)
            if n >= 2:
                dealer_idx = self.dealer_position % n
                if n == 2:
                    # 单挑局（heads-up）：庄家即小盲，另一人为大盲
                    sb_index = dealer_idx
                    bb_index = (dealer_idx + 1) % n
                else:
                    sb_index = (dealer_idx + 1) % n
                    bb_index = (dealer_idx + 2) % n
                sb_player = active_players[sb_index]
                bb_player = active_players[bb_index]
                
                # 设置小盲/大盲标记（供前端显示 SB/BB 徽章）
                sb_player.is_small_blind = True
                bb_player.is_big_blind = True
                
                sb_amount = sb_player.place_bet(self.small_blind)
                bb_amount = bb_player.place_bet(self.big_blind)
                self.pot += sb_amount + bb_amount
                self.current_bet = self.big_blind
                
                # 小盲注玩家需要补齐到大盲注才算完成初始行动
                sb_player.has_acted = False  # 小盲注玩家还需要决定是否跟注
                bb_player.has_acted = False  # 大盲注玩家有最后行动权
                
                print(f"🎮 大小盲注模式: 庄家={active_players[dealer_idx].nickname}, 小盲={sb_player.nickname}, 大盲={bb_player.nickname}")
        
        elif self.game_mode == "ante":
            # 按比例下注模式 - 所有人都下注相同比例
            ante_amount = int(self.initial_chips * self.ante_percentage)
            if ante_amount < 1:
                ante_amount = 1  # 最少1个筹码
            
            total_ante = 0
            for player in active_players:
                actual_ante = player.place_bet(ante_amount)
                total_ante += actual_ante
            
            self.pot = total_ante
            # 重要：ante模式下，初始current_bet应该为0，让玩家可以自由选择过牌或下注
            self.current_bet = 0
            
            # 所有玩家已经完成初始ante下注，现在可以选择行动（过牌或下注）
            for player in active_players:
                player.has_acted = False  # 允许玩家在ante基础上继续行动
                # 重要：重置玩家的current_bet，因为ante不算作"下注"，而是入场费
                player.current_bet = 0
            
            print(f"🎮 按比例下注模式: 每人缴纳ante ${ante_amount} (筹码的{self.ante_percentage*100:.1f}%), 总底池${total_ante}, 现在开始下注轮（current_bet=${self.current_bet})")
        
        self.last_activity = time.time()
        print(f"🎮 新手牌开始: 手牌#{self.hand_number}, 阶段={self.game_stage.value}, 活跃玩家={len(active_players)}, 模式={self.game_mode}")
        return True
    
    def process_player_action(self, player_id: str, action: PlayerAction, amount: int = 0) -> Dict:
        """处理玩家动作"""
        player = self.get_player(player_id)
        if not player:
            return {'success': False, 'message': '玩家不存在'}
        
        # 检查是否轮到该玩家行动
        current_player = self.get_current_player()
        if not current_player or current_player.id != player_id:
            return {'success': False, 'message': '现在不是您的回合'}
        
        try:
            amount = int(amount or 0)
        except (TypeError, ValueError):
            return {'success': False, 'message': '金额无效'}

        try:
            executed = self._execute_action(player, action, amount, strict=True)
            if not executed['success']:
                return executed
            actual_amount = executed['amount']
            action_description = executed['description']
            action = executed['action']
            self.last_activity = time.time()
            
            # 检查游戏流程
            flow_result = self.process_game_flow()
            
            result = {
                'success': True,
                'action': action.value,
                'amount': actual_amount,
                'description': action_description,
                'hand_complete': flow_result.get('hand_complete', False),
                'stage_changed': flow_result.get('stage_changed', False),
                'winners': flow_result.get('winners', [])
            }
            
            # 如果手牌结束，传递完整的获胜者和摊牌信息
            if flow_result.get('hand_complete'):
                result['winner'] = flow_result.get('winner')
                result['showdown_info'] = flow_result.get('showdown_info', {})
                print(f"🎯 玩家动作传递摊牌信息: winner={result['winner']}, showdown_info存在={bool(result['showdown_info'])}")
            
            return result
            
        except Exception as e:
            return {'success': False, 'message': f'动作执行失败: {str(e)}'}
    
    def min_bet(self) -> int:
        """最小下注额（盲注模式为大盲，按比例模式为 ante 额）"""
        return self.min_raise

    def min_raise_to(self) -> int:
        """最小加注到的总额：当前下注 + 本轮最近一次完整加注的幅度"""
        return self.current_bet + max(self.last_raise_size, self.min_bet())

    def _commit_chips(self, player: Player, to_amount: int) -> int:
        """把玩家本轮下注补到 to_amount（筹码不足则全下），返回实际投入，并更新当前下注/最小加注"""
        added = player.place_bet(max(0, to_amount - player.current_bet))
        self.pot += added
        if player.current_bet > self.current_bet:
            raise_size = player.current_bet - self.current_bet
            # 只有完整加注才更新最小加注幅度；不足额的全下加注不改变它
            if raise_size >= self.last_raise_size:
                self.last_raise_size = raise_size
            self.current_bet = player.current_bet
        return added

    def _execute_action(self, player: Player, action: PlayerAction, amount: int = 0, strict: bool = True) -> Dict:
        """
        按德州扑克规则执行一个动作。
        strict=True（真人）：非法金额直接拒绝；strict=False（机器人）：把金额修正到最接近的合法值。
        BET / RAISE 的 amount 均表示「本轮下注到的总额」。
        """
        owe = max(0, self.current_bet - player.current_bet)
        max_to = player.current_bet + player.chips  # 全下时本轮下注总额

        def done(act, added, desc):
            player.has_acted = True
            self.last_actor_id = player.id
            # 通知其他机器人，用于对手建模（盲注不经过这里，不会计入主动入池）
            for other in self.players:
                if isinstance(other, Bot) and other is not player:
                    other.update_opponent_pattern(player.id, act, added, {'stage': self.game_stage.value})
            return {'success': True, 'action': act, 'amount': added, 'description': desc}

        def reject(msg):
            return {'success': False, 'message': msg}

        if player.chips <= 0 and action != PlayerAction.FOLD:
            return reject('没有筹码，无法行动')

        if action == PlayerAction.FOLD:
            player.fold()
            return done(PlayerAction.FOLD, 0, "弃牌")

        if action == PlayerAction.CHECK:
            if owe > 0:
                if strict:
                    return reject('当前有下注，无法过牌')
                action = PlayerAction.CALL
            else:
                player.check()
                return done(PlayerAction.CHECK, 0, "过牌")

        if action == PlayerAction.CALL:
            if owe <= 0:
                if strict:
                    return reject('无需跟注')
                player.check()
                return done(PlayerAction.CHECK, 0, "过牌")
            added = self._commit_chips(player, self.current_bet)
            if player.chips == 0:
                return done(PlayerAction.ALL_IN, added, f"全下跟注 ${added}")
            return done(PlayerAction.CALL, added, f"跟注 ${added}")

        if action == PlayerAction.ALL_IN:
            added = self._commit_chips(player, max_to)
            return done(PlayerAction.ALL_IN, added, f"全下 ${added}")

        if action == PlayerAction.BET and self.current_bet > 0:
            if strict:
                return reject('已有下注，请选择跟注或加注')
            action = PlayerAction.RAISE
        if action == PlayerAction.RAISE and self.current_bet == 0:
            if strict:
                return reject('没有下注，请选择下注')
            action = PlayerAction.BET

        if action == PlayerAction.BET:
            minimum = self.min_bet()
        elif action == PlayerAction.RAISE:
            minimum = self.min_raise_to()
            # 已行动且只面对不足额全下加注的玩家不能再加注，只能跟注或弃牌
            if player.has_acted and self.current_bet - player.current_bet < self.last_raise_size and owe > 0:
                if strict:
                    return reject('对方全下不足一次完整加注，您只能跟注或弃牌')
                return self._execute_action(player, PlayerAction.CALL, 0, strict=False)
        else:
            return reject('无效的动作')

        if amount >= max_to:
            # 金额达到或超过全部筹码，按全下处理（全下可以低于最小额）
            added = self._commit_chips(player, max_to)
            return done(PlayerAction.ALL_IN, added, f"全下 ${added}")
        if amount < minimum:
            if strict:
                verb = '下注' if action == PlayerAction.BET else '加注到'
                return reject(f'最小{verb} ${minimum}')
            if minimum >= max_to:
                added = self._commit_chips(player, max_to)
                return done(PlayerAction.ALL_IN, added, f"全下 ${added}")
            amount = minimum

        added = self._commit_chips(player, amount)
        if action == PlayerAction.BET:
            return done(PlayerAction.BET, added, f"下注 ${amount}")
        return done(PlayerAction.RAISE, added, f"加注到 ${amount}")

    def _position_of(self, player: Player) -> str:
        """翻牌后的相对位置：越晚行动越有利。庄家与关煞位为 late，最先行动的约三分之一为 early"""
        order = [p for p in self._participants() if p.status in (PlayerStatus.PLAYING, PlayerStatus.ALL_IN)]
        if player not in order or len(order) <= 2:
            return 'late' if player.is_dealer else 'early'
        dealer_idx = next((i for i, p in enumerate(self._participants()) if p.is_dealer), 0)
        seats = self._participants()
        # 从庄家下一位开始排列的行动顺序
        acting = [seats[(dealer_idx + 1 + i) % len(seats)] for i in range(len(seats))]
        acting = [p for p in acting if p in order]
        frac = acting.index(player) / (len(acting) - 1)
        return 'late' if frac >= 0.67 else ('early' if frac <= 0.34 else 'middle')
    
    def _bot_game_state(self, player: Player) -> Dict:
        """机器人决策所需的牌局信息"""
        contenders = [p for p in self.players if p.status in (PlayerStatus.PLAYING, PlayerStatus.ALL_IN)]
        return {
            'community_cards': self.community_cards,
            'stage': self.game_stage.value,
            'current_bet': self.current_bet,
            'to_call': max(0, self.current_bet - player.current_bet),
            'big_blind': self.big_blind,
            'pot_size': self.pot,
            'min_bet': self.min_bet(),
            'min_raise_to': self.min_raise_to(),
            'min_raise': self.min_raise,
            # 仍在牌局中的人数（含已全下者），对手数 = 该值 - 1
            'active_players': len(contenders),
            'num_opponents': max(1, len(contenders) - 1),
            'position': self._position_of(player),
            'all_players': self.players  # 德州扑克之神可以看到所有玩家的底牌
        }
    
    def process_bot_actions(self):
        """处理机器人动作 - 持续处理直到轮到人类玩家或游戏结束"""
        from .bot import Bot
        import time
        
        max_iterations = 15  # 减少最大迭代次数防止死循环
        iterations = 0
        consecutive_no_action = 0  # 连续无动作计数
        global_timeout = time.time() + 30  # 30秒全局超时保护
        
        print(f"🤖 开始机器人处理 (最大{max_iterations}轮, 30秒超时)")
        
        while iterations < max_iterations and time.time() < global_timeout:
            iterations += 1
            had_action_this_round = False
            
            # 检查超时
            if time.time() >= global_timeout:
                print(f"⏰ 机器人处理超时，强制结束")
                break
            
            # 获取当前应该行动的玩家
            current_player = self.get_current_player()
            
            # 如果没有需要行动的玩家，立即检查游戏流程
            if not current_player:
                print(f"🔍 第{iterations}轮：没有需要行动的玩家")
                flow_result = self.process_game_flow()
                print(f"🎯 游戏流程检查结果: hand_complete={flow_result.get('hand_complete')}, stage_changed={flow_result.get('stage_changed')}")
                
                if flow_result.get('hand_complete'):
                    print(f"🏆 手牌结束，停止机器人处理")
                    return flow_result
                elif flow_result.get('stage_changed'):
                    print(f"📈 阶段变化，继续处理")
                    consecutive_no_action = 0  # 重置计数
                    continue
                else:
                    print(f"⚠️ 无玩家行动且无流程变化")
                    consecutive_no_action += 1
                    if consecutive_no_action >= 2:  # 减少到2次，更快响应
                        print(f"💀 连续{consecutive_no_action}轮无变化，强制结束处理")
                        # 尝试强制推进游戏流程
                        print(f"🔧 尝试强制推进游戏...")
                        force_result = self._force_advance_game_flow()
                        if force_result and force_result.get('hand_complete'):
                            print(f"🏆 强制推进导致手牌结束")
                            return force_result
                        break
                    continue
            
            # 如果轮到人类玩家，停止处理
            if not isinstance(current_player, Bot):
                print(f"轮到人类玩家 {current_player.nickname} 行动，停止机器人处理")
                break
                
            # 重置连续无动作计数
            consecutive_no_action = 0
            
            # 处理机器人行动
            player = current_player
            print(f"🤖 轮到机器人 {player.nickname} 行动，状态: {player.status.value}, 当前投注: {self.current_bet}, 机器人投注: {player.current_bet}")
            
            # 检查机器人状态是否合法
            if player.status not in [PlayerStatus.PLAYING, PlayerStatus.ALL_IN]:
                print(f"🤖 机器人 {player.nickname} 状态不合法: {player.status.value}，跳过")
                player.has_acted = True
                continue
            
            # 检查机器人是否有足够筹码
            if player.chips <= 0 and player.status != PlayerStatus.ALL_IN:
                print(f"🤖 机器人 {player.nickname} 筹码不足，自动全下")
                player.status = PlayerStatus.ALL_IN
                player.has_acted = True
                continue
            
            # 构建游戏状态
            game_state = self._bot_game_state(player)
            
            # 机器人决策 - 添加异常处理
            action = None
            try:
                action = player.decide_action(game_state)
            except Exception as e:
                print(f"❌ 机器人 {player.nickname} 决策出错: {e}")
                
            # 如果机器人无法决策，提供默认行动
            if not action:
                print(f"🤖 机器人 {player.nickname} 无法决策，使用默认策略")
                # 默认策略：如果能过牌就过牌，否则弃牌
                call_amount = self.current_bet - player.current_bet
                if call_amount == 0:
                    action = (PlayerAction.CHECK, 0)
                    print(f"🤖 {player.nickname} 默认行动: 过牌")
                else:
                    action = (PlayerAction.FOLD, 0)
                    print(f"🤖 {player.nickname} 默认行动: 弃牌")
            
            if action:
                action_type, amount = action
                action_desc = self._get_action_description(action_type, amount)
                
                # 根据机器人等级添加思考时间延迟
                from .bot import BotLevel
                thinking_delays = {
                    BotLevel.BEGINNER: 1.0,      # 初级 1秒
                    BotLevel.INTERMEDIATE: 1.0,  # 中级 1秒
                    BotLevel.ADVANCED: 1.0,      # 高级 1秒
                    BotLevel.GOD: 1.0            # 神级 1秒
                }
                
                delay = thinking_delays.get(player.bot_level, 0.0)
                if delay > 0:
                    print(f"🤖 {player.nickname} ({player.bot_level.value}) 思考中... ({delay}秒)")
                    time.sleep(delay)

                # 思考期间牌局可能已变化（如手牌结束或其他流程已替它行动），确认仍轮到它
                if self.get_current_player() is not player:
                    print(f"🤖 {player.nickname} 已不是当前行动玩家，放弃本次决策")
                    continue
                
                print(f"🤖 {player.nickname} 决定: {action_desc}")
                
                # 显示机器人手牌（用于调试）
                if len(player.hole_cards) == 2:
                    card1_str = f"{player.hole_cards[0].rank.symbol}{player.hole_cards[0].suit.value}"
                    card2_str = f"{player.hole_cards[1].rank.symbol}{player.hole_cards[1].suit.value}"
                    print(f"🤖 {player.nickname} 手牌: {card1_str} {card2_str}")
                
                # 直接处理机器人动作，不通过process_player_action避免递归（非法金额自动修正为合法值）
                try:
                    executed = self._execute_action(player, action_type, amount, strict=False)
                    if executed['success']:
                        print(f"🤖 {player.nickname} {executed['description']} (本轮投注: ${player.current_bet})")
                    elif player.status == PlayerStatus.PLAYING and player.chips > 0:
                        player.fold()
                        print(f"🤖 {player.nickname} 动作无效（{executed['message']}），弃牌")
                    else:
                        # 已全下/已出局的玩家不能被弃牌，否则会失去已投入筹码的争夺资格
                        print(f"🤖 {player.nickname} 无法行动（{executed['message']}），跳过")
                        continue

                    # 标记机器人已行动
                    player.has_acted = True
                    self.last_actor_id = player.id
                    had_action_this_round = True
                    print(f"✅ 机器人 {player.nickname} 已完成行动")
                    
                    # 调用外部回调（app层据此逐步广播桌面状态）
                    if self.on_bot_action:
                        try:
                            self.on_bot_action(player)
                        except Exception as e:
                            print(f"⚠️ 机器人行动回调失败: {e}")
                    
                except Exception as e:
                    print(f"❌ 机器人 {player.nickname} 执行动作时出错: {e}")
                    # 出错时强制弃牌
                    player.fold()
                    player.has_acted = True
                    had_action_this_round = True
                    print(f"🤖 {player.nickname} 因错误强制弃牌")
                
                # 检查游戏流程是否需要推进
                flow_result = self.process_game_flow()
                if flow_result['hand_complete']:
                    print(f"🏆 机器人动作导致手牌结束: {flow_result}")
                    # 返回手牌结束的结果，包含完整的摊牌信息
                    return flow_result
                elif flow_result['stage_changed']:
                    print(f"阶段变化: {flow_result}")
                    # 阶段变化后继续处理机器人
                    continue
                    
            else:
                print(f"❌ 机器人 {player.nickname} 彻底无法决策，强制弃牌")
                player.fold()
                player.has_acted = True
                had_action_this_round = True
            
            # 如果本轮没有任何动作，增加无动作计数
            if not had_action_this_round:
                consecutive_no_action += 1
                print(f"⚠️ 本轮无动作 ({consecutive_no_action}/3)")
                if consecutive_no_action >= 3:
                    print("连续3轮无动作，强制结束处理")
                    break
        
        print(f"🏁 机器人处理完成，共处理 {iterations} 轮")
        
        # 检查是否有遗留的机器人未完成行动
        remaining_bots = []
        for player in self.players:
            if (isinstance(player, Bot) and 
                player.status == PlayerStatus.PLAYING and 
                not player.has_acted):
                remaining_bots.append(player.nickname)
        
        if remaining_bots:
            print(f"⚠️ 发现未完成行动的机器人: {remaining_bots}")
            # 让这些机器人正常决策，而不是强制弃牌
            for player in self.players:
                if (isinstance(player, Bot) and 
                    player.status == PlayerStatus.PLAYING and 
                    not player.has_acted):
                    print(f"🔧 补充处理机器人 {player.nickname}")
                    
                    # 构建游戏状态，让机器人正常决策
                    game_state = self._bot_game_state(player)
                    
                    # 让机器人正常决策
                    action = None
                    try:
                        action = player.decide_action(game_state)
                        print(f"🤖 {player.nickname} 补充决策: {action}")
                    except Exception as e:
                        print(f"❌ 机器人 {player.nickname} 补充决策出错: {e}")
                    
                    # 如果机器人无法决策，使用更合理的兜底策略
                    if not action:
                        call_amount = self.current_bet - player.current_bet
                        if call_amount <= 0:
                            action = (PlayerAction.CHECK, 0)
                            print(f"🤖 {player.nickname} 兜底策略: 过牌")
                        elif call_amount <= player.chips * 0.1:  # 只有在成本很低时才跟注
                            action = (PlayerAction.CALL, call_amount)
                            print(f"🤖 {player.nickname} 兜底策略: 跟注${call_amount}")
                        else:
                            action = (PlayerAction.FOLD, 0)
                            print(f"🤖 {player.nickname} 兜底策略: 弃牌")
                    
                    # 执行机器人决策
                    if action:
                        action_type, amount = action
                        try:
                            # 防御：补充处理不在正常行动顺序内，不允许改变下注额（否则已行动玩家会突然欠注），
                            # 下注/加注/全下一律降级为跟注补齐或过牌
                            if action_type in (PlayerAction.BET, PlayerAction.RAISE, PlayerAction.ALL_IN):
                                action_type = PlayerAction.CALL
                            executed = self._execute_action(player, action_type, 0, strict=False)
                            if executed['success']:
                                print(f"🤖 {player.nickname} 补充处理: {executed['description']}")
                            elif player.status == PlayerStatus.PLAYING and player.chips > 0:
                                player.fold()
                                print(f"🤖 {player.nickname} 补充处理动作无效，弃牌")
                        except Exception as e:
                            print(f"❌ 执行机器人动作失败: {e}")
                            player.fold()
                            print(f"🤖 {player.nickname} 因错误弃牌")
                    
                    player.has_acted = True
                    
                    # 每个机器人决策间隔1秒（与主循环一致）
                    time.sleep(1.0)
                    # 调用外部回调逐步广播桌面状态
                    if self.on_bot_action:
                        try:
                            self.on_bot_action(player)
                        except Exception as e:
                            print(f"⚠️ 机器人行动回调失败: {e}")
        
        # 返回最终的游戏流程状态
        final_flow_result = self.process_game_flow()
        print(f"🏁 机器人处理完成，最终流程结果: hand_complete={final_flow_result.get('hand_complete')}, winner={final_flow_result.get('winner')}")
        return final_flow_result
    
    def add_player_at_position(self, player: Player, position: int) -> bool:
        """在指定位置添加玩家"""
        if position < 0 or position >= self.max_players:
            return False
        
        if self.seats[position] is not None:
            return False
        
        # 如果玩家已在其他位置，先移除
        for seat_num, seated_player in self.seats.items():
            if seated_player and seated_player.id == player.id:
                self.seats[seat_num] = None
                break
        
        # 添加到指定位置
        self.seats[position] = player
        
        # 如果不在玩家列表中，添加进去
        if player not in self.players:
            self.players.append(player)
        
        self.last_activity = time.time()
        return True
    
    def get_player_position(self, player_id: str) -> Optional[int]:
        """获取玩家的座位位置"""
        for position, player in self.seats.items():
            if player and player.id == player_id:
                return position
        return None

    def get_player(self, player_id: str) -> Optional[Player]:
        """获取指定ID的玩家"""
        for player in self.players:
            if player.id == player_id:
                return player
        return None
    
    def calculate_win_probability(self, player_id: str, simulations: int = 10000) -> Optional[Dict]:
        """计算玩家胜率"""
        if not self.enable_win_probability:
            return None
        
        player = self.get_player(player_id)
        if not player or len(player.hole_cards) != 2:
            return None

        # 对仍在牌局中的对手（手牌未知，按随机手牌）做蒙特卡洛模拟
        opponents = [p for p in self.players if p is not player
                     and p.status in (PlayerStatus.PLAYING, PlayerStatus.ALL_IN)]
        result = equity_vs_random(player.hole_cards, self.community_cards, max(1, len(opponents)),
                                  min(simulations, 5000))
        return {
            'win': round(result['win'], 3),
            'tie': round(result['tie'], 3),
            'lose': round(result['lose'], 3)
        }
    
    def get_card_tracking_info(self) -> Dict:
        """获取记牌信息"""
        if not self.enable_card_tracking:
            return {}
        
        # 统计已知的牌
        known_cards = []
        known_cards.extend(self.community_cards)
        
        # 统计每种花色和点数的剩余数量
        suits = ['hearts', 'diamonds', 'clubs', 'spades']
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
        
        remaining_cards = {
            'suits': {suit: 13 for suit in suits},
            'ranks': {rank: 4 for rank in ranks},
            'total_remaining': 52 - len(known_cards)
        }
        
        # 减去已知的牌
        for card in known_cards:
            card_dict = card.to_dict()
            suit = card_dict['suit']
            rank = card_dict['rank']
            
            if suit in remaining_cards['suits']:
                remaining_cards['suits'][suit] -= 1
            if rank in remaining_cards['ranks']:
                remaining_cards['ranks'][rank] -= 1
        
        return {
            'known_cards': [card.to_dict() for card in known_cards],
            'remaining_cards': remaining_cards
        }
    
    def get_current_player(self) -> Optional[Player]:
        """获取当前应该行动的玩家"""
        if self.game_stage == GameStage.WAITING or self.game_stage == GameStage.FINISHED:
            return None
        
        # 还在牌局中（未弃牌）的玩家，以及其中还能行动（有筹码）的玩家
        contenders = [p for p in self.players if p.status in (PlayerStatus.PLAYING, PlayerStatus.ALL_IN)]
        can_act = [p for p in contenders if p.status == PlayerStatus.PLAYING and p.chips > 0]
        if len(contenders) <= 1 or not can_act:
            return None
        if len(can_act) == 1:
            # 其他人都已全下：剩下的玩家只有在欠注时才需要行动（跟注或弃牌），否则无人可对抗
            only = can_act[0]
            return only if only.current_bet < self.current_bet else None

        # 行动顺序以本手牌发到牌的玩家（按座位）为准，庄家位置固定，再跳过不能行动的玩家
        order = [p for p in self._participants() if p in self.players] or contenders
        dealer_idx = next((i for i, p in enumerate(order) if p.is_dealer), 0)
        n = len(order)

        if self.game_mode == "ante":
            # 按比例下注模式：每条街都从庄家下一位开始
            start = (dealer_idx + 1) % n
        elif n == 2:
            # 单挑局：翻牌前庄家（小盲）先行动，翻牌后大盲先行动
            start = dealer_idx if self.game_stage == GameStage.PRE_FLOP else (dealer_idx + 1) % n
        elif self.game_stage == GameStage.PRE_FLOP:
            # 翻牌前：大盲下一位（UTG）先行动
            start = (dealer_idx + 3) % n
        else:
            # 翻牌后：庄家下一位先行动
            start = (dealer_idx + 1) % n

        # 本街已有人行动时，从上一位行动者的下一位开始找（加注后按座位顺序轮转，而不是回到本街首位）
        last_idx = next((i for i, p in enumerate(order) if p.id == self.last_actor_id), None)
        if last_idx is not None:
            start = (last_idx + 1) % n

        for i in range(n):
            player = order[(start + i) % n]
            if player not in can_act:
                continue
            if not player.has_acted or player.current_bet < self.current_bet:
                return player

        return None
    
    def get_table_state(self, player_id: Optional[str] = None) -> Dict:
        """获取牌桌状态"""
        current_player = self.get_current_player()
        return {
            'id': self.id,
            'title': self.title,
            'small_blind': self.small_blind,
            'big_blind': self.big_blind,
            'max_players': self.max_players,
            'game_mode': self.game_mode,
            'ante_percentage': self.ante_percentage,
            'game_stage': self.game_stage.value,
            'hand_number': self.hand_number,
            'community_cards': [card.to_dict() for card in self.community_cards],
            'pot': self.pot,
            'current_bet': self.current_bet,
            'current_player_id': current_player.id if current_player else None,
            'min_bet': self.min_bet(),
            'min_raise_to': self.min_raise_to(),
            'players': [p.to_dict(include_hole_cards=(p.id == player_id)) for p in self.players],
            'can_start': (len([p for p in self.players if p.chips > 0 and p.status != PlayerStatus.DISCONNECTED]) >= 2
                          and self.game_stage == GameStage.WAITING),
            'created_at': self.created_at,
            'last_activity': self.last_activity
        }
    
    def is_betting_round_complete(self) -> bool:
        """检查当前投注回合是否完成"""
        # 区分能继续行动的玩家和全下玩家
        contenders = [p for p in self.players if p.status in (PlayerStatus.PLAYING, PlayerStatus.ALL_IN)]
        playing_players = [p for p in contenders if p.status == PlayerStatus.PLAYING and p.chips > 0]
        all_in_players = [p for p in contenders if p.status == PlayerStatus.ALL_IN]

        print(f"投注回合检查: 可行动玩家={len(playing_players)}, 全下玩家={len(all_in_players)}")

        # 只剩一名未弃牌玩家，或没有人还能行动
        if len(contenders) <= 1 or not playing_players:
            return True

        # 只剩一名能行动的玩家：跟平（或无需跟注）后回合结束，欠注时必须先跟注或弃牌
        if len(playing_players) == 1:
            return playing_players[0].current_bet >= self.current_bet

        # 检查所有可以行动的玩家是否都已行动且投注相等
        players_needing_action = []

        for player in playing_players:
            # 如果玩家还有筹码但投注不相等，或者还未行动，则回合未完成
            if not player.has_acted or player.current_bet < self.current_bet:
                players_needing_action.append(f"{player.nickname}(投注${player.current_bet}, 行动状态:{player.has_acted})")
        
        if players_needing_action:
            print(f"投注回合未完成，还有玩家需要行动: {players_needing_action}")
            return False
        
        print("所有可行动玩家都已完成行动，投注轮结束")
        print(f"  - 可行动玩家投注状况: {[(p.nickname, p.current_bet, p.chips) for p in playing_players]}")
        print(f"  - 全下玩家投注状况: {[(p.nickname, p.current_bet, p.chips) for p in all_in_players]}")
        return True
    
    def advance_to_next_stage(self) -> bool:
        """进入下一个游戏阶段"""
        if self.game_stage == GameStage.PRE_FLOP:
            # 发 flop (3张公共牌)
            new_cards = self.deck.deal_cards(3)
            self.community_cards.extend(new_cards)
            self.game_stage = GameStage.FLOP
            # 显示 flop 牌
            flop_str = " ".join([f"{card.rank.symbol}{card.suit.value}" for card in new_cards])
            print(f"🃏 Flop: {flop_str}")
        elif self.game_stage == GameStage.FLOP:
            # 发 turn (第4张公共牌)
            new_card = self.deck.deal_cards(1)[0]
            self.community_cards.append(new_card)
            self.game_stage = GameStage.TURN
            turn_str = f"{new_card.rank.symbol}{new_card.suit.value}"
            print(f"🃏 Turn: {turn_str}")
        elif self.game_stage == GameStage.TURN:
            # 发 river (第5张公共牌)
            new_card = self.deck.deal_cards(1)[0]
            self.community_cards.append(new_card)
            self.game_stage = GameStage.RIVER
            river_str = f"{new_card.rank.symbol}{new_card.suit.value}"
            print(f"🃏 River: {river_str}")
            
            # 显示完整的公共牌
            community_str = " ".join([f"{card.rank.symbol}{card.suit.value}" for card in self.community_cards])
            print(f"🃏 完整公共牌: {community_str}")
        elif self.game_stage == GameStage.RIVER:
            # 进入摊牌阶段
            self.game_stage = GameStage.SHOWDOWN
            # 注意：不在这里调用_determine_winner，让process_game_flow处理
        else:
            return False
        
        # 重置当前投注和玩家下注金额，以及行动状态（全下玩家的本轮投注也清零，总投入保留在 total_bet）
        self.current_bet = 0
        self.last_raise_size = self.min_bet()
        self.last_actor_id = None
        for player in self.players:
            if player.status in (PlayerStatus.PLAYING, PlayerStatus.ALL_IN):
                player.current_bet = 0
                player.has_acted = False  # 重置行动状态
        
        self.last_activity = time.time()
        return True
    
    def is_hand_complete(self) -> bool:
        """检查本手牌是否结束"""
        # 包括全下的玩家在活跃玩家中
        active_players = [p for p in self.players if p.status in [PlayerStatus.PLAYING, PlayerStatus.ALL_IN]]
        
        # 如果只剩一个活跃玩家，游戏结束
        if len(active_players) <= 1:
            return True
        
        # 如果到了showdown阶段，游戏结束
        if self.game_stage == GameStage.SHOWDOWN:
            return True
        
        return False
    
    def _hand_str(self, player: Player) -> str:
        return " ".join(f"{c.rank.symbol}{c.suit.value}" for c in player.hole_cards)

    def _run_out_board(self):
        """所有人都无法继续下注时，把剩余公共牌发完"""
        missing = 5 - len(self.community_cards)
        if missing > 0:
            self.community_cards.extend(self.deck.deal_cards(missing))

    def _build_pots(self, contenders: List[Player]) -> List[Dict]:
        """
        按每位玩家本手牌总投入(total_bet)拆分主池/边池。
        弃牌玩家的投入进入对应层级的池子，但没有赢取资格。
        """
        contributors = [p for p in self._participants() if p.total_bet > 0]
        levels = sorted({p.total_bet for p in contenders if p.total_bet > 0})
        pots = []
        prev = 0
        for level in levels:
            amount = sum(min(p.total_bet, level) - min(p.total_bet, prev) for p in contributors)
            eligible = [p for p in contenders if p.total_bet >= level]
            if amount > 0:
                pots.append({'amount': amount, 'eligible': eligible})
            prev = level
        # 弃牌玩家超过所有在局玩家投入的部分（极少见）并入最后一个池
        leftover = sum(max(0, p.total_bet - prev) for p in contributors)
        if leftover and pots:
            pots[-1]['amount'] += leftover
        # 与实际底池核对，防止数据不一致导致筹码凭空增减
        diff = self.pot - sum(p['amount'] for p in pots)
        if diff and pots:
            print(f"⚠️ 底池核对差额 ${diff}，并入主池")
            pots[0]['amount'] += diff
        return pots

    def _odd_chip_order(self, players: List[Player]) -> List[Player]:
        """平分底池的零头按庄家左手边开始的顺序分配"""
        order = [p for p in self._participants() if p in players]
        dealer_idx = next((i for i, p in enumerate(self._participants()) if p.is_dealer), -1)
        n = max(1, len(self._participants()))
        return sorted(order, key=lambda p: (self._participants().index(p) - dealer_idx - 1) % n)

    def _determine_winner(self) -> Dict:
        """结算本手牌：支持弃牌获胜、摊牌比牌、边池、平分底池与退还无人跟注的筹码"""
        contenders = [p for p in self.players if p.status in (PlayerStatus.PLAYING, PlayerStatus.ALL_IN)]
        total_pot = self.pot

        showdown_info = {
            'winner': None,
            'winners': [],
            'pots': [],
            'showdown_players': [],
            'community_cards': [card.to_dict() for card in self.community_cards],
            'pot': total_pot,
            'is_showdown': len(contenders) > 1
        }

        if not contenders:
            print("⚠️ 结算时没有在局玩家，底池保留")
            self.game_stage = GameStage.FINISHED
            return showdown_info

        winnings: Dict[str, int] = {p.id: 0 for p in contenders}
        returned: Dict[str, int] = {p.id: 0 for p in contenders}
        hands = {}

        if len(contenders) == 1:
            # 其他人都弃牌：剩下的玩家拿走整个底池（其中自己未被跟注的部分属于退还）
            winner = contenders[0]
            others_max = max([p.total_bet for p in self._participants() if p is not winner] or [0])
            uncalled = min(max(0, winner.total_bet - others_max), total_pot)
            winner.chips += total_pot
            returned[winner.id] = uncalled
            winnings[winner.id] = total_pot - uncalled
            showdown_info['is_showdown'] = False
            showdown_info['win_reason'] = 'others_folded'
            showdown_info['pots'] = [{'amount': total_pot - uncalled, 'winners': [winner.nickname]}]
            if len(self.community_cards) >= 3 and len(winner.hole_cards) == 2:
                hands[winner.id] = HandEvaluator.evaluate_hand(winner.hole_cards, self.community_cards)
            print(f"{'🤖' if winner.is_bot else '👤'} {winner.nickname} 获胜（其他玩家弃牌），赢得 ${winnings[winner.id]}"
                  + (f"，退还未被跟注的 ${uncalled}" if uncalled else ""))
        else:
            # 摊牌：先把公共牌发完，再逐个池子比牌
            self._run_out_board()
            self.game_stage = GameStage.SHOWDOWN
            showdown_info['community_cards'] = [card.to_dict() for card in self.community_cards]
            for p in contenders:
                hands[p.id] = HandEvaluator.evaluate_hand(p.hole_cards, self.community_cards)

            print("=" * 60)
            print(f"🃏 摊牌 - 公共牌: {' '.join(f'{c.rank.symbol}{c.suit.value}' for c in self.community_cards)}")
            for p in contenders:
                print(f"  {'🤖' if p.is_bot else '👤'} {p.nickname}: {self._hand_str(p)} -> "
                      f"{HandEvaluator.hand_to_string(hands[p.id])}（投入 ${p.total_bet}）")

            for index, pot in enumerate(self._build_pots(contenders)):
                eligible = pot['eligible']
                if len(eligible) == 1:
                    # 只有一人有资格的池子 = 超出其他人承受范围、无人跟注的部分，原样退还
                    eligible[0].chips += pot['amount']
                    returned[eligible[0].id] += pot['amount']
                    print(f"  ↩️ 退还 {eligible[0].nickname} 无人跟注的 ${pot['amount']}")
                    continue
                best = eligible[0]
                for p in eligible[1:]:
                    if HandEvaluator.compare_hands(hands[p.id], hands[best.id]) > 0:
                        best = p
                pot_winners = [p for p in eligible if HandEvaluator.compare_hands(hands[p.id], hands[best.id]) == 0]
                share, remainder = divmod(pot['amount'], len(pot_winners))
                for i, p in enumerate(self._odd_chip_order(pot_winners)):
                    amount = share + (1 if i < remainder else 0)
                    p.chips += amount
                    winnings[p.id] += amount
                name = '主池' if not showdown_info['pots'] else f"边池{len(showdown_info['pots'])}"
                showdown_info['pots'].append({'amount': pot['amount'], 'winners': [p.nickname for p in pot_winners]})
                print(f"  💰 {name} ${pot['amount']}（{len(eligible)} 人争夺）→ {'、'.join(p.nickname for p in pot_winners)}"
                      + ("（平分）" if len(pot_winners) > 1 else ""))
            print("=" * 60)
            showdown_info['win_reason'] = 'best_hand'

        # 组装展示信息：按牌力从高到低排序，并列时名次相同
        def strength(p):
            hand = hands.get(p.id)
            return (hand[0].rank_value, hand[1]) if hand else (0, [])
        ordered = sorted(contenders, key=strength, reverse=True)
        rank = 0
        prev_hand = None
        for i, p in enumerate(ordered):
            hand = hands.get(p.id)
            if hand is None or prev_hand is None or HandEvaluator.compare_hands(hand, prev_hand) != 0:
                rank = i + 1
            prev_hand = hand
            showdown_info['showdown_players'].append({
                'player': p,
                'player_id': p.id,
                'nickname': p.nickname,
                'is_bot': p.is_bot,
                'hole_cards': [card.to_dict() for card in p.hole_cards],
                'hole_cards_str': self._hand_str(p),
                'hand_description': HandEvaluator.hand_to_string(hand) if hand else "未知牌型",
                'hand_name': hand[0].value[1] if hand else "",
                'rank_value': hand[0].rank_value if hand else 0,
                'rank': rank,
                'result': 'winner' if winnings[p.id] > 0 else 'loser',
                'winnings': winnings[p.id],
                'returned': returned[p.id],
                'final_chips': p.chips
            })

        winners = sorted((p for p in contenders if winnings[p.id] > 0), key=lambda p: winnings[p.id], reverse=True)
        if not winners:
            # 例如其他人只投入了 0：仍然视拿回筹码最多的人为本手牌赢家
            winners = sorted(contenders, key=lambda p: returned[p.id], reverse=True)[:1]
        showdown_info['winner'] = winners[0]
        showdown_info['winners'] = [{'player_id': p.id, 'nickname': p.nickname, 'amount': winnings[p.id], 'chips': p.chips}
                                    for p in winners]

        # 筹码输光的玩家转为观战，不再参与之后的牌局
        for p in self.hand_players:
            if p.chips <= 0 and p in self.players and p.status != PlayerStatus.DISCONNECTED:
                p.status = PlayerStatus.BROKE
                print(f"💸 {p.nickname} 筹码输光，转为观战")

        self.game_stage = GameStage.FINISHED
        return showdown_info

    def process_game_flow(self) -> Dict:
        """处理游戏流程，返回状态更新"""
        result = {
            'stage_changed': False,
            'hand_complete': False,
            'winner': None,
            'message': ''
        }
        
        # 如果游戏已经结束，不再处理
        if self.game_stage == GameStage.FINISHED:
            print(f"游戏已结束，跳过流程处理 (阶段: {self.game_stage.value})")
            return result
        
        # 包括全下的玩家在内的活跃玩家（用于判断是否需要继续游戏）
        active_players = [p for p in self.players if p.status in [PlayerStatus.PLAYING, PlayerStatus.ALL_IN]]
        print(f"游戏流程检查: 活跃玩家={len(active_players)}, 当前阶段={self.game_stage.value}, 底池=${self.pot}")
        
        # 打印玩家状态
        for player in self.players:
            print(f"  玩家 {player.nickname}: 状态={player.status.value}, 当前投注=${player.current_bet}, 筹码=${player.chips}")
        
        # 检查投注回合是否完成
        if self.is_betting_round_complete():
            print("投注回合完成！")
            
            # 先检查是否只剩一个玩家（提前结束）
            if len(active_players) <= 1:
                print("只剩一个玩家，手牌提前结束")
                showdown_result = self._determine_winner()
                result['hand_complete'] = True
                result['showdown_info'] = showdown_result
                result['winner'] = showdown_result.get('winner', None)
                if result['winner']:
                    result['message'] = f"{result['winner'].nickname} 获胜，赢得 ${showdown_result['pot']}"
            else:
                # 进入下一阶段
                print(f"进入下一阶段，当前阶段: {self.game_stage.value}")
                if self.advance_to_next_stage():
                    # 没有人还能下注（其他人都已全下）时，直接把剩余公共牌发完进入摊牌
                    while self.game_stage != GameStage.SHOWDOWN and self.is_betting_round_complete():
                        print("无人可继续下注，自动发下一张公共牌")
                        self.advance_to_next_stage()
                    result['stage_changed'] = True
                    result['message'] = f"进入 {self.game_stage.value} 阶段"
                    print(f"成功进入 {self.game_stage.value} 阶段")
                    
                    # 如果进入SHOWDOWN阶段，手牌结束，需要确定获胜者
                    if self.game_stage == GameStage.SHOWDOWN:
                        print("🏆 进入SHOWDOWN阶段，开始摊牌")
                        showdown_result = self._determine_winner()
                        result['hand_complete'] = True
                        result['showdown_info'] = showdown_result
                        result['winner'] = showdown_result.get('winner', None)
                        if result['winner']:
                            result['message'] = f"{result['winner'].nickname} 获胜，赢得 ${showdown_result['pot']}"
                        
                        # 摊牌完成后直接返回，不再处理FINISHED阶段
                        print(f"🏆 摊牌完成，返回结果，游戏阶段: {self.game_stage.value}")
                        return result
                    
                    # 如果进入FINISHED阶段，表示手牌结束
                    elif self.game_stage == GameStage.FINISHED:
                        print("🏆 游戏阶段为FINISHED，手牌已结束")
                        result['hand_complete'] = True
                        
                        # 这种情况通常是在_determine_winner中已经设置了游戏阶段为FINISHED
                        # 应该已经有摊牌信息了，不需要重复处理
                        print("⚠️ 游戏阶段已为FINISHED，可能缺少摊牌信息")
                        
                        # 强制查找获胜者
                        winner = None
                        max_chips = 0
                        
                        for player in self.players:
                            if player.chips > max_chips:
                                max_chips = player.chips
                                winner = player
                        
                        # 如果没找到，就选择第一个活跃玩家
                        if not winner:
                            active_players = [p for p in self.players if p.status == PlayerStatus.PLAYING]
                            if active_players:
                                winner = active_players[0]
                        
                        if winner:
                            result['winner'] = winner
                            result['message'] = f"{winner.nickname} 获胜"
                            print(f"🏆 确定获胜者: {winner.nickname}, 筹码: {winner.chips}")
                        else:
                            print("⚠️ 未找到获胜者，创建默认获胜者")
                            if self.players:
                                winner = self.players[0]
                                result['winner'] = winner
                                result['message'] = f"{winner.nickname} 获胜（默认）"
        else:
            print("投注回合未完成，等待更多玩家行动")
        
        return result

    def _force_advance_game_flow(self):
        """强制推进游戏流程 - 处理卡住情况"""
        print(f"🚨 强制推进游戏流程...")
        
        # 检查是否所有能行动的玩家都已行动
        playing_players = [p for p in self.players if p.status == PlayerStatus.PLAYING and p.chips > 0]
        all_in_players = [p for p in self.players if p.status == PlayerStatus.ALL_IN]
        folded_players = [p for p in self.players if p.status == PlayerStatus.FOLDED]
        
        print(f"  可行动玩家: {len(playing_players)}, 全下玩家: {len(all_in_players)}, 弃牌玩家: {len(folded_players)}")
        
        # 如果没有或只有1个可行动玩家，强制完成投注回合
        if len(playing_players) <= 1:
            print(f"  ✅ 强制标记投注回合完成")
            
            # 如果游戏阶段不是最终阶段，推进到下一阶段
            if self.game_stage not in [GameStage.SHOWDOWN, GameStage.FINISHED]:
                if self.advance_to_next_stage():
                    print(f"  📈 强制推进到下一阶段: {self.game_stage.value}")
                    return {'stage_changed': True, 'hand_complete': False}
            
            # 如果已经是最后阶段，强制结束手牌
            if self.game_stage in [GameStage.RIVER, GameStage.SHOWDOWN]:
                print(f"  🏆 强制结束手牌")
                winner_result = self._determine_winner()
                return {
                    'hand_complete': True,
                    'winner': winner_result.get('winner'),
                    'showdown_info': winner_result
                }
        
        # 检查是否所有可行动玩家都已全下
        active_players = [p for p in self.players if p.status in [PlayerStatus.PLAYING, PlayerStatus.ALL_IN]]
        if len(active_players) > 1 and len(playing_players) == 0:
            print(f"  🎯 所有玩家都已全下，直接进入摊牌")
            # 强制进入摊牌阶段
            if self.game_stage != GameStage.SHOWDOWN:
                self.game_stage = GameStage.SHOWDOWN
            winner_result = self._determine_winner()
            return {
                'hand_complete': True,
                'winner': winner_result.get('winner'),
                'showdown_info': winner_result
            }
        
        print(f"  ⚠️ 无法强制推进，维持当前状态")
        return None

    def _get_action_description(self, action_type: PlayerAction, amount: int) -> str:
        """获取动作的中文描述"""
        if action_type == PlayerAction.FOLD:
            return "弃牌"
        elif action_type == PlayerAction.CHECK:
            return "过牌"
        elif action_type == PlayerAction.CALL:
            return f"跟注 ${amount}"
        elif action_type == PlayerAction.BET:
            return f"下注 ${amount}"
        elif action_type == PlayerAction.RAISE:
            return f"加注到 ${amount}"
        elif action_type == PlayerAction.ALL_IN:
            return f"全下 ${amount}"
        else:
            return f"未知动作: {action_type.value}" 