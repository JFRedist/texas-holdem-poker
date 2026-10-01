"""
玩家类
Player class for poker game
"""

from typing import List, Optional
from enum import Enum
from .card import Card


class PlayerStatus(Enum):
    """玩家状态枚举"""
    WAITING = "waiting"      # 等待中
    PLAYING = "playing"      # 游戏中
    FOLDED = "folded"        # 弃牌
    ALL_IN = "all_in"        # 全下
    BROKE = "broke"          # 没有筹码（观察者）
    DISCONNECTED = "disconnected"  # 断线


class PlayerAction(Enum):
    """玩家动作枚举"""
    FOLD = "fold"           # 弃牌
    CHECK = "check"         # 过牌
    CALL = "call"           # 跟注
    BET = "bet"             # 下注
    RAISE = "raise"         # 加注
    ALL_IN = "all_in"       # 全下


class Player:
    """玩家类"""
    
    def __init__(self, player_id: str, nickname: str, chips: int = 1000, is_bot: bool = False):
        """
        初始化玩家
        
        Args:
            player_id: 玩家ID
            nickname: 昵称
            chips: 筹码数量
            is_bot: 是否为机器人
        """
        self.id = player_id
        self.nickname = nickname
        self.chips = chips
        self.is_bot = is_bot
        self.status = PlayerStatus.WAITING
        
        # 游戏相关状态
        self.hole_cards: List[Card] = []  # 底牌
        self.current_bet = 0              # 当前回合下注额
        self.total_bet = 0                # 本手牌总下注额
        self.is_dealer = False            # 是否为庄家
        self.is_small_blind = False       # 是否为小盲
        self.is_big_blind = False         # 是否为大盲
        self.has_acted = False            # 本轮是否已行动
        
        # 连接状态
        self.session_id: Optional[str] = None
        self.last_seen = None
        self.disconnected = False         # 断线标记（弃牌/全下的玩家断线时保留原状态，只打这个标记）
    
    def reset_for_new_hand(self):
        """为新手牌重置玩家状态"""
        self.hole_cards = []
        self.current_bet = 0
        self.total_bet = 0
        self.is_dealer = False
        self.is_small_blind = False
        self.is_big_blind = False
        self.has_acted = False
        if self.status not in [PlayerStatus.DISCONNECTED]:
            # 如果没有筹码，设置为观察者状态
            if self.chips <= 0:
                self.status = PlayerStatus.BROKE
            else:
                self.status = PlayerStatus.PLAYING
    
    def mark_disconnected(self):
        """断线：已弃牌、全下或破产的玩家保留原状态（弃牌不能复活，全下保留底池资格），
        只有仍需行动或等待中的玩家改为 DISCONNECTED"""
        self.disconnected = True
        if self.status in (PlayerStatus.PLAYING, PlayerStatus.WAITING):
            self.status = PlayerStatus.DISCONNECTED

    def mark_reconnected(self, in_current_hand: bool, hand_in_progress: bool):
        """重连：只恢复因断线而改成 DISCONNECTED 的状态，弃牌/全下/破产保持不变

        Args:
            in_current_hand: 是否是当前这手牌的参与者且仍持有底牌
            hand_in_progress: 当前是否有一手牌正在进行
        """
        self.disconnected = False
        if self.status != PlayerStatus.DISCONNECTED:
            return
        if self.chips <= 0:
            self.status = PlayerStatus.BROKE
        elif hand_in_progress and in_current_hand:
            self.status = PlayerStatus.PLAYING
        else:
            # 断线期间这手牌已结束或开了新的一手，没有底牌，等下一手
            self.status = PlayerStatus.WAITING

    def reset_for_new_round(self):
        """为新轮重置玩家状态"""
        self.current_bet = 0
        self.has_acted = False
    
    def deal_hole_cards(self, cards: List[Card]):
        """发底牌给玩家"""
        self.hole_cards = cards
    
    def can_act(self) -> bool:
        """检查玩家是否可以行动"""
        # 没有筹码的玩家不能行动，只能观察
        if self.chips <= 0 or self.status == PlayerStatus.BROKE:
            return False
        return (self.status == PlayerStatus.PLAYING and 
                not self.has_acted and 
                self.chips > 0)
    
    def can_bet(self, amount: int) -> bool:
        """检查玩家是否可以下注指定金额"""
        return self.chips >= amount and amount > 0
    
    def can_call(self, call_amount: int) -> bool:
        """检查玩家是否可以跟注"""
        return self.chips >= call_amount
    
    def can_raise(self, raise_amount: int) -> bool:
        """检查玩家是否可以加注"""
        return self.chips >= raise_amount
    
    def place_bet(self, amount: int) -> int:
        """
        下注
        
        Args:
            amount: 下注金额
            
        Returns:
            int: 实际下注金额
        """
        # 没有筹码的玩家不能下注
        if self.chips <= 0:
            print(f"⚠️ 玩家 {self.nickname} 没有筹码，无法下注")
            return 0
            
        if amount <= 0:
            return 0
            
        # 确保不超过玩家筹码
        actual_amount = min(amount, self.chips)
        
        self.chips -= actual_amount
        self.current_bet += actual_amount
        self.total_bet += actual_amount
        self.has_acted = True
        
        # 如果筹码用完，标记为全下状态（仍可参与胜负判定）
        if self.chips == 0:
            self.status = PlayerStatus.ALL_IN
            print(f"💸 玩家 {self.nickname} 全下，等待摊牌")
            
        return actual_amount
    
    def fold(self):
        """弃牌"""
        self.status = PlayerStatus.FOLDED
        self.has_acted = True
    
    def check(self):
        """过牌"""
        self.has_acted = True
    
    def call(self, call_amount: int) -> int:
        """
        跟注
        
        Args:
            call_amount: 需要跟注的金额
            
        Returns:
            int: 实际跟注金额
        """
        needed = call_amount - self.current_bet
        return self.place_bet(needed)
    
    def win_chips(self, amount: int):
        """赢得筹码"""
        self.chips += amount
    
    def get_hole_cards_dict(self) -> List[dict]:
        """获取底牌的字典表示"""
        return [card.to_dict() for card in self.hole_cards]
    
    def to_dict(self, include_hole_cards: bool = False) -> dict:
        """
        转换为字典格式
        
        Args:
            include_hole_cards: 是否包含底牌信息
            
        Returns:
            dict: 玩家信息字典
        """
        data = {
            'id': self.id,
            'nickname': self.nickname,
            'chips': self.chips,
            'is_bot': self.is_bot,
            'status': self.status.value,
            'current_bet': self.current_bet,
            'total_bet': self.total_bet,
            'is_dealer': self.is_dealer,
            'is_small_blind': self.is_small_blind,
            'is_big_blind': self.is_big_blind,
            'has_acted': self.has_acted,
            'disconnected': self.disconnected
        }
        
        if include_hole_cards:
            data['hole_cards'] = self.get_hole_cards_dict()
            
        return data
    
    def __str__(self) -> str:
        """返回玩家的字符串表示"""
        return f"Player({self.nickname}, chips={self.chips}, status={self.status.value})"
    
    def __repr__(self) -> str:
        """返回玩家的详细表示"""
        return (f"Player(id={self.id}, nickname={self.nickname}, "
                f"chips={self.chips}, is_bot={self.is_bot})") 