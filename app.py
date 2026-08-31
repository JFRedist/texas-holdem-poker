"""
德州扑克游戏主应用
Texas Hold'em Poker Game Main Application
"""

# ⚠️ 必须在导入其他库之前完成 eventlet monkey patch，
# 否则 time.sleep 等调用会阻塞整个服务器（所有玩家连接卡死）
import eventlet
eventlet.monkey_patch()

import uuid
import time
import re
import traceback
from typing import Dict, List, Optional
from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit, join_room, leave_room, rooms
import threading
import sqlite3
from datetime import datetime
import json

from poker_engine import Player, Table, Bot, BotLevel
from poker_engine.player import PlayerAction, PlayerStatus
from poker_engine.table import GameStage
from database import db
from game_logger import (
    log_table_created, log_hand_started, log_hand_ended, 
    log_player_action, log_stage_change, game_logger
)
from table_state_manager import (
    record_table_state, register_restart_callback, mark_restart_completed,
    TableStateChange
)
from player_persistence import update_player_chips, get_player


# 创建Flask应用
app = Flask(__name__)
app.config['SECRET_KEY'] = 'poker_game_secret_key_2025'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', 
                  logger=False, engineio_logger=False, ping_timeout=30, ping_interval=25)

# Socket.IO错误处理
@socketio.on_error_default
def default_error_handler(e):
    """默认错误处理器"""
    if 'Session is disconnected' in str(e):
        # 会话断开连接是正常的网络状况，只记录调试信息
        print(f"🔌 Socket会话断开连接: {request.sid}")
    else:
        # 其他错误需要记录详细信息
        print(f"❌ Socket.IO错误: {e}")
        import traceback
        traceback.print_exc()
    return False  # 不向客户端发送错误信息

# 全局状态管理
tables: Dict[str, Table] = {}
players: Dict[str, Player] = {}
player_sessions: Dict[str, str] = {}  # session_id -> player_id
session_tables: Dict[str, str] = {}   # session_id -> table_id

# 游戏日志状态管理
table_sessions: Dict[str, int] = {}   # table_id -> session_id (日志会话ID)
current_hands: Dict[str, int] = {}    # table_id -> hand_id (当前手牌ID)

# 添加下一轮开始相关的数据结构
next_round_votes = {}  # {table_id: {player_id: True/False}}

def process_bot_actions(table_id: str):
    """处理机器人动作"""
    try:
        if table_id not in tables:
            return
        
        table = tables[table_id]
        
        # 设置机器人逐步行动回调：每个机器人行动后立即广播桌面状态，让玩家看到节奏
        def _bot_action_callback(player):
            try:
                socketio.emit('table_updated', table.get_table_state(), room=table_id)
            except Exception as e:
                print(f"⚠️ 机器人行动广播失败: {e}")
        table.on_bot_action = _bot_action_callback
        
        # 🔧 修复：如果游戏已结束，不处理机器人动作
        if table.game_stage == GameStage.FINISHED:
            print(f"🛑 游戏已结束，停止机器人处理 (table_id: {table_id})")
            return None
        
        # 检查是否有机器人需要行动，如果有就先通知前端
        current_player = table.get_current_player()
        if current_player and current_player.is_bot:
            # 获取机器人等级和对应的思考时间 - 每个机器人决策间隔1秒
            from poker_engine.bot import BotLevel
            thinking_delays = {
                BotLevel.BEGINNER: 1.0,      # 初级 1秒
                BotLevel.INTERMEDIATE: 1.0,  # 中级 1秒
                BotLevel.ADVANCED: 1.0,      # 高级 1秒
                BotLevel.GOD: 1.0            # 德州扑克之神 1秒
            }
            delay = thinking_delays.get(current_player.bot_level, 0.0)
            
            # 增强调试信息
            print(f"🤖 机器人行动准备: {current_player.nickname}")
            print(f"  - 机器人ID: {current_player.id}")
            print(f"  - 机器人类型: {type(current_player)}")
            print(f"  - 是否是Bot实例: {isinstance(current_player, Bot)}")
            print(f"  - bot_level属性存在: {hasattr(current_player, 'bot_level')}")
            if hasattr(current_player, 'bot_level'):
                print(f"  - 机器人等级: {current_player.bot_level}")
                print(f"  - 等级值: {current_player.bot_level.value}")
                print(f"  - 等级类型: {type(current_player.bot_level)}")
                print(f"  - 思考时间: {delay}秒")
            else:
                print(f"  - ❌ 机器人缺少bot_level属性，使用默认延迟1秒")
                delay = 1.0
            
            # 通知前端机器人正在思考
            socketio.emit('bot_thinking', {
                'bot_name': current_player.nickname,
                'bot_level': current_player.bot_level.value,
                'thinking_time': delay
            }, room=table_id)
        
        result = table.process_bot_actions()
        
        # 调试：打印机器人处理结果
        print(f"🤖 机器人处理结果: {result}")
        print(f"🤖 游戏阶段: {table.game_stage.value}")
        
        # 检查是否手牌结束
        if result and result.get('hand_complete'):
            print(f"🏆 机器人处理导致手牌结束")
            showdown_info = result.get('showdown_info', {})
            winner = result.get('winner')
            print(f"🏆 准备调用handle_hand_end，winner: {winner}, showdown_info: {showdown_info}")
            handle_hand_end(table_id, winner, showdown_info)
            return result
        else:
            print(f"🔍 手牌未结束，继续游戏流程")
        
        # 广播更新后的桌面状态
        socketio.emit('table_updated', table.get_table_state(), room=table_id)
        
        # 检查是否轮到人类玩家行动
        current_player = table.get_current_player()
        if current_player and not current_player.is_bot:
            # 检查玩家是否有筹码
            if current_player.chips <= 0 or current_player.status.value == 'broke':
                print(f"🚫 玩家 {current_player.nickname} 没有筹码，跳过行动通知")
                return result
                
            # 找到该玩家的session并发送行动通知
            player_session = None
            for session_id, session_info in player_sessions.items():
                if session_info['player_id'] == current_player.id:
                    player_session = session_id
                    break
            
            if player_session:
                print(f"🎯 轮到人类玩家 {current_player.nickname} 行动")
                socketio.emit('your_turn', {
                    'current_bet': table.current_bet,
                    'min_bet': table.big_blind,
                    'pot': table.pot,
                    'your_bet': current_player.current_bet,
                    'your_chips': current_player.chips
                }, room=player_session)
                
                return result
    except Exception as e:
        print(f"❌ 处理机器人动作失败: {e}")
        return None

def handle_restart_needed(table_id: str, state_type, data: Dict):
    """处理需要重启的回调"""
    try:
        print(f"🔄 收到重启信号: {table_id} - {data}")
        
        # 检查房间是否还存在
        if table_id not in tables:
            print(f"❌ 房间 {table_id} 不存在，跳过重启")
            return
        
        table = tables[table_id]
        hand_number = data.get('hand_number', 0)
        
        print(f"🔍 检查房间状态: table_id={table_id}, 房间存在=True")
        print(f"🔍 房间玩家数量: {len(table.players)}")
        
        # 检查玩家状态
        active_players = [p for p in table.players if p.status != PlayerStatus.DISCONNECTED]
        print(f"🔍 当前玩家状态:")
        for player in table.players:
            player_type = "🤖" if player.is_bot else "👤"
            print(f"  {player_type} {player.nickname}: 状态={player.status.value}, 筹码=${player.chips}")
        
        if len(active_players) < 2:
            print(f"❌ 玩家数量不足，无法重启 (需要>=2，当前={len(active_players)})")
            mark_restart_completed(table_id, hand_number, success=False)
            return
        
        print("✅ 房间检查通过，开始新手牌...")
        
        # 开始新手牌
        success = table.start_new_hand()
        if not success:
            print(f"❌ 新手牌创建失败")
            mark_restart_completed(table_id, hand_number, success=False)
            return
        
        print(f"✅ 新手牌创建成功，手牌编号: {table.hand_number}")
        
        # 记录手牌开始到日志数据库
        if table_id in table_sessions:
            session_id_log = table_sessions[table_id]
            hand_id = log_hand_started(session_id_log, table.hand_number, table_id)
            current_hands[table_id] = hand_id
        
        # 记录状态变化
        record_table_state(
            table_id, TableStateChange.HAND_STARTED,
            game_stage=table.game_stage.value,
            hand_number=table.hand_number,
            player_count=len(table.players),
            active_player_count=len(active_players),
            pot=table.pot,
            current_bet=table.current_bet
        )
        
        # 发送手牌给人类玩家
        for player in table.players:
            if not player.is_bot and player.status == PlayerStatus.PLAYING:
                player_session = None
                for session_id, player_id in player_sessions.items():
                    if player_id == player.id:
                        player_session = session_id
                        break
                
                if player_session and len(player.hole_cards) == 2:
                    print(f"📤 发送手牌给玩家: {player.nickname}")
                    socketio.emit('your_cards', {
                        'hole_cards': [card.to_dict() for card in player.hole_cards]
                    }, room=player_session)
        
        # 广播新手牌开始
        print(f"📡 广播新手牌开始事件...")
        socketio.emit('hand_started', {
            'table': table.get_table_state()
        }, room=table_id)
        
        print(f"房间 {table.title} 自动开始新手牌")
        
        # 后台显示所有玩家的手牌
        print("=" * 50)
        print(f"🃏 新一轮玩家手牌信息 (手牌#{table.hand_number})：")
        for i, player in enumerate(table.players):
            if player.status == PlayerStatus.PLAYING and len(player.hole_cards) == 2:
                card1 = player.hole_cards[0]
                card2 = player.hole_cards[1]
                card1_str = f"{card1.rank.symbol}{card1.suit.value}"
                card2_str = f"{card2.rank.symbol}{card2.suit.value}"
                player_type = "🤖" if player.is_bot else "👤"
                print(f"  {player_type} {player.nickname}: {card1_str} {card2_str} (筹码: ${player.chips}, 状态: {player.status.value})")
        print(f"🎯 游戏阶段: {table.game_stage.value}")
        print(f"💰 当前底池: ${table.pot}")
        print(f"💵 当前投注: ${table.current_bet}")
        print("=" * 50)
        
        # 启动机器人处理
        def start_bot_processing():
            time.sleep(1)  # 给玩家一点时间接收状态
            process_bot_actions(table_id)
        
        threading.Thread(target=start_bot_processing, daemon=True).start()
        
        # 标记重启完成
        mark_restart_completed(table_id, hand_number, success=True)
        
        # 🔧 新增：在重启前保存所有玩家筹码到数据库
        print(f"💾 保存玩家筹码到数据库...")
        for player in table.players:
            if not player.is_bot:  # 只保存人类玩家
                try:
                    update_player_chips(player.id, player.chips)
                    print(f"💰 保存玩家筹码: {player.nickname} -> ${player.chips}")
                except Exception as e:
                    print(f"❌ 保存筹码失败: {player.nickname} - {e}")
        
        # 如果房间没有人类玩家了，关闭房间
        human_players = [p for p in table.players if not p.is_bot]
        if len(human_players) == 0:
            print(f"房间 {table_id} 已关闭（无人类玩家）")
            if table_id in tables:
                del tables[table_id]
            if table_id in next_round_votes:
                del next_round_votes[table_id]
        
    except Exception as e:
        print(f"❌ 处理重启失败: {e}")
        hand_number = data.get('hand_number', 0)
        mark_restart_completed(table_id, hand_number, success=False)


def validate_nickname(nickname: str) -> bool:
    """验证昵称格式"""
    if not nickname or len(nickname.strip()) == 0:
        return False
    
    nickname = nickname.strip()
    if len(nickname) > 20 or len(nickname) < 1:
        return False
    
    # 允许中文、英文、数字和基本符号
    pattern = r'^[\u4e00-\u9fa5a-zA-Z0-9_\-\s]+$'
    return bool(re.match(pattern, nickname))


# REST API 路由

@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/lobby')
def lobby():
    """大厅页面"""
    return render_template('lobby.html')


@app.route('/table/<table_id>')
def table_page(table_id):
    """牌桌页面"""
    if table_id not in tables:
        return "牌桌不存在", 404
    return render_template('table.html', table_id=table_id)


@app.route('/api/join', methods=['POST'])
def join_game():
    """加入游戏 - 创建或获取用户"""
    try:
        data = request.get_json()
        nickname = data.get('nickname', '').strip()
        
        if not validate_nickname(nickname):
            return jsonify({
                'success': False,
                'message': '昵称无效。请使用2-20个字符，仅包含字母、数字、中文和基本符号。'
            }), 400
        
        # 检查是否已存在该昵称的用户
        existing_user = db.get_user_by_nickname(nickname)
        
        if existing_user:
            # 用户已存在，返回现有用户信息
            player_id = existing_user['id']
            print(f"用户 {nickname} 已存在，ID: {player_id}")
        else:
            # 创建新用户
            player_id = db.create_user(nickname)
            print(f"创建新用户 {nickname}，ID: {player_id}")
        
        # 更新用户活动时间
        db.update_user_activity(player_id)
        
        # 获取最新用户信息
        user_data = db.get_user(player_id)
        
        # 创建Player对象（用于游戏逻辑）
        if player_id not in players:
            player = Player(player_id, nickname, user_data['chips'])
            players[player_id] = player
        
        return jsonify({
            'success': True,
            'player': {
                'id': player_id,
                'nickname': nickname,
                'chips': user_data['chips']
            }
        })
        
    except Exception as e:
        print(f"加入游戏失败: {e}")
        return jsonify({
            'success': False,
            'message': '服务器错误，请稍后重试'
        }), 500


@app.route('/api/tables', methods=['GET'])
def get_tables():
    """获取所有活跃房间列表"""
    try:
        # 从数据库获取活跃房间
        db_tables = db.get_all_active_tables()
        
        # 获取请求者已加入的房间（用于大厅显示"进入房间"而不是"房间已满"）
        player_id = request.args.get('player_id')
        member_table_ids = set()
        if player_id:
            try:
                member_table_ids = set(db.get_player_table_ids(player_id))
            except Exception as e:
                print(f"获取玩家房间列表失败: {e}")
        
        # 转换为前端需要的格式
        tables_data = []
        for table_data in db_tables:
            # 同步内存中的Table对象
            table_id = table_data['id']
            if table_id not in tables:
                # 如果内存中没有，创建一个新的Table对象
                table = Table(
                    table_id=table_id,
                    title=table_data['title'],
                    small_blind=table_data['small_blind'],
                    big_blind=table_data['big_blind'],
                    max_players=table_data['max_players'],
                    initial_chips=table_data['initial_chips']
                )
                tables[table_id] = table
            
            # 构建返回数据
            table_info = {
                'id': table_id,
                'title': table_data['title'],
                'small_blind': table_data['small_blind'],
                'big_blind': table_data['big_blind'],
                'max_players': table_data['max_players'],
                'current_players': table_data['player_count'],
                'game_stage': table_data['game_stage'],
                'game_mode': table_data.get('game_mode', 'blinds'),
                'ante_percentage': table_data.get('ante_percentage', 0.02),
                'created_by': table_data['creator_nickname'],
                'created_by_id': table_data['created_by'],
                'created_at': table_data['created_at'],
                'is_member': table_id in member_table_ids
            }
            tables_data.append(table_info)
        
        return jsonify({
            'success': True,
            'tables': tables_data
        })
        
    except Exception as e:
        print(f"获取房间列表失败: {e}")
        return jsonify({
            'success': False,
            'message': '获取房间列表失败'
        }), 500


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """获取服务器统计信息"""
    try:
        # 获取在线玩家数（通过session管理）
        online_players = len(player_sessions)
        print(f"🔍 当前在线玩家数: {online_players}, 会话: {list(player_sessions.keys())}")
        
        # 获取活跃房间数 - 使用内存中的tables而不是数据库
        active_tables = len(tables)
        
        # 计算总游戏中玩家数
        total_players_in_game = 0
        for table in tables.values():
            human_players = [p for p in table.players if not p.is_bot]
            total_players_in_game += len(human_players)
        
        stats = {
            'online_players': online_players,
            'active_tables': active_tables,
            'players_in_game': total_players_in_game
        }
        
        print(f"📊 统计信息: {stats}")
        
        return jsonify({
            'success': True,
            'stats': stats
        })
        
    except Exception as e:
        print(f"获取统计信息失败: {e}")
        return jsonify({
            'success': False,
            'message': '获取统计信息失败'
        }), 500


@app.route('/api/showdown_history/<table_id>', methods=['GET'])
def get_showdown_history(table_id):
    """获取牌桌的摊牌历史记录"""
    try:
        from game_logger import game_logger
        
        # 获取该牌桌的最近几手摊牌记录
        with game_logger.get_connection() as conn:
            cursor = conn.cursor()
            
            # 查询最近10手的摊牌详情
            cursor.execute('''
                SELECT h.id, h.hand_number, h.ended_at, h.winner_nickname, h.pot,
                       sd.player_id, sd.nickname, sd.is_bot, sd.hole_cards, 
                       sd.hand_description, sd.rank_position, sd.result, sd.winnings
                FROM hands h
                LEFT JOIN showdown_details sd ON h.id = sd.hand_id
                WHERE h.table_id = ? AND h.status = 'completed' 
                      AND sd.hand_id IS NOT NULL
                ORDER BY h.ended_at DESC, sd.rank_position ASC
                LIMIT 100
            ''', (table_id,))
            
            rows = cursor.fetchall()
                
            # 按手牌组织数据
            hands_data = {}
            for row in rows:
                hand_id = row[0]
                if hand_id not in hands_data:
                    hands_data[hand_id] = {
                        'hand_id': hand_id,
                        'hand_number': row[1],
                        'ended_at': row[2],
                        'winner_nickname': row[3],
                        'pot': row[4],
                        'players': []
                    }
                
                hands_data[hand_id]['players'].append({
                    'player_id': row[5],
                    'nickname': row[6],
                    'is_bot': bool(row[7]),
                    'hole_cards': json.loads(row[8]) if row[8] else [],
                    'hand_description': row[9],
                    'rank_position': row[10],
                    'result': row[11],
                    'winnings': row[12]
                })
            
            # 转换为列表并按时间排序
            history = list(hands_data.values())
            history.sort(key=lambda x: x['ended_at'], reverse=True)
            
            return jsonify({
                'success': True,
                'history': history[:10]  # 只返回最近10手
            })
            
    except Exception as e:
        print(f"获取摊牌历史失败: {e}")
        return jsonify({
            'success': False,
            'message': f'获取摊牌历史失败: {str(e)}'
        }), 500


@app.route('/api/player_showdown_summary/<player_id>', methods=['GET'])
def get_player_showdown_summary(player_id):
    """获取玩家摊牌统计摘要"""
    try:
        from game_logger import game_logger
        
        with game_logger.get_connection() as conn:
            cursor = conn.cursor()
            
            # 查询玩家的摊牌统计
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_showdowns,
                    SUM(CASE WHEN result = 'winner' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN result = 'loser' THEN 1 ELSE 0 END) as losses,
                    SUM(winnings) as total_winnings,
                    AVG(CASE WHEN result = 'winner' THEN winnings ELSE 0 END) as average_winnings,
                    nickname
                FROM showdown_details 
                WHERE player_id = ?
                GROUP BY player_id
            ''', (player_id,))
            
            row = cursor.fetchone()
            
            if not row or row[0] == 0:
                return jsonify({
                    'success': True,
                    'has_data': False,
                    'message': '暂无摊牌记录'
                })
            
            total_showdowns, wins, losses, total_winnings, avg_winnings, nickname = row
            win_rate = round((wins / total_showdowns * 100), 1) if total_showdowns > 0 else 0
            
            # 获取手牌类型分布
            cursor.execute('''
                SELECT hand_rank, COUNT(*) as count
                FROM showdown_details
                WHERE player_id = ?
                GROUP BY hand_rank
                ORDER BY count DESC
            ''', (player_id,))
            
            hand_types = dict(cursor.fetchall())
            
            return jsonify({
                'success': True,
                'has_data': True,
                'nickname': nickname,
                'overall_stats': {
                    'total_showdowns': total_showdowns,
                    'wins': wins,
                    'losses': losses,
                    'win_rate': win_rate,
                    'total_winnings': int(total_winnings) if total_winnings else 0,
                    'average_winnings': round(avg_winnings, 2) if avg_winnings else 0
                },
                'hand_type_distribution': hand_types
            })
        
    except Exception as e:
        print(f"获取玩家摊牌统计失败: {e}")
        return jsonify({
            'success': False,
            'message': f'获取玩家摊牌统计失败: {str(e)}'
        }), 500


@app.route('/api/player_showdown_history/<player_id>', methods=['GET'])
def get_player_showdown_history(player_id):
    """获取玩家摊牌历史记录"""
    try:
        from game_logger import game_logger
        limit = request.args.get('limit', 10, type=int)
        limit = min(limit, 50)  # 最多50条记录
        
        with game_logger.get_connection() as conn:
            cursor = conn.cursor()
            
            # 查询玩家的摊牌历史
            cursor.execute('''
                SELECT 
                    sd.hand_id, h.hand_number, h.ended_at, h.winner_nickname, h.pot,
                    sd.nickname, sd.is_bot, sd.hole_cards, sd.hand_description,
                    sd.rank_position, sd.result, sd.winnings
                FROM showdown_details sd
                JOIN hands h ON sd.hand_id = h.id
                WHERE sd.player_id = ?
                ORDER BY h.ended_at DESC
                LIMIT ?
            ''', (player_id, limit))
            
            rows = cursor.fetchall()
            
            history = []
            for row in rows:
                history.append({
                    'hand_id': row[0],
                    'hand_number': row[1],
                    'ended_at': row[2],
                    'winner_nickname': row[3],
                    'pot': row[4],
                    'nickname': row[5],
                    'is_bot': bool(row[6]),
                    'hole_cards': json.loads(row[7]) if row[7] else [],
                    'hand_description': row[8],
                    'rank_position': row[9],
                    'result': row[10],
                    'winnings': row[11]
                })
            
            return jsonify({
                'success': True,
                'history': history
            })
            
    except Exception as e:
        print(f"获取玩家摊牌历史失败: {e}")
        return jsonify({
            'success': False,
            'message': f'获取玩家摊牌历史失败: {str(e)}'
        }), 500


@app.route('/api/card_tracking', methods=['POST'])
def api_card_tracking():
    """记牌助手API，仅有权限账号可用"""
    try:
        data = request.get_json() or {}
        table_id = data.get('table_id')
        player_id = data.get('player_id')
        if not table_id or not player_id:
            return jsonify({'success': False, 'message': '参数缺失'}), 400

        # 校验玩家是否有权限
        player_data = db.get_user(player_id)
        if not player_data or not player_data.get('has_helper', 0):
            return jsonify({'success': False, 'message': '无权限访问此功能'}), 403

        # 获取内存中的Table对象
        table = tables.get(table_id)
        if not table:
            # 尝试从数据库恢复（略），这里只查内存
            return jsonify({'success': False, 'message': '房间不存在'}), 404

        info = table.get_card_tracking_info()
        return jsonify({'success': True, 'data': info})
    except Exception as e:
        print(f"记牌助手API异常: {e}")
        return jsonify({'success': False, 'message': '服务器错误'}), 500


@app.route('/api/win_probability', methods=['POST'])
def api_win_probability():
    """胜率计算API，所有玩家可用"""
    try:
        data = request.get_json() or {}
        table_id = data.get('table_id')
        player_id = data.get('player_id')
        if not table_id or not player_id:
            return jsonify({'success': False, 'message': '参数缺失'}), 400

        # 获取内存中的Table对象
        table = tables.get(table_id)
        if not table:
            return jsonify({'success': False, 'message': '房间不存在'}), 404

        result = table.calculate_win_probability(player_id)
        if not result:
            return jsonify({'success': False, 'message': '无法计算胜率，可能未发牌'}), 400
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        print(f"胜率计算API异常: {e}")
        return jsonify({'success': False, 'message': '服务器错误'}), 500


# WebSocket 事件处理

@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    try:
        print(f"Client connected: {request.sid}")
        emit('connected', {'session_id': request.sid})
    except Exception as e:
        print(f"连接处理错误: {e}")


@socketio.on('disconnect')
def handle_disconnect():
    """处理玩家断线"""
    try:
        session_id = request.sid
        
        if session_id in player_sessions:
            player_info = player_sessions[session_id]
            nickname = player_info['nickname']
            player_id = player_info['player_id']
            
            print(f"玩家 {nickname} 断线")
            
            # 立即清理会话，避免重复计数
            del player_sessions[session_id]
            print(f"会话 {session_id} 立即清理完成")
            
            # 从session_tables中清理
            if session_id in session_tables:
                del session_tables[session_id]
            
            # 广播更新统计信息
            online_players = len(player_sessions)
            active_tables = len(tables)
            socketio.emit('stats_update', {
                'online_players': online_players,
                'active_tables': active_tables
            })
            
            # 设置30秒后移除玩家（如果没有重新连接）
            def remove_player_delayed():
                import time
                time.sleep(30)
                
                # 检查玩家是否重新连接
                reconnected = False
                for sid, session in player_sessions.items():
                    if session['player_id'] == player_id:
                        reconnected = True
                        break
                
                if not reconnected:
                    print(f"30秒后移除未重连的玩家 {nickname}")
                    
                    # 从所有房间中移除玩家
                    tables_to_check = []
                    for table_id, table in list(tables.items()):
                        players_to_remove = [p for p in table.players if p.id == player_id]
                        for player in players_to_remove:
                            table.remove_player(player.id)
                            db.leave_table(table_id, player.id)  # 从数据库移除
                            socketio.emit('player_left', {
                                'nickname': player.nickname,
                                'remaining_players': len(table.players)
                            }, room=table_id)
                            tables_to_check.append(table_id)
                    
                    # 检查并清理空房间
                    for table_id in set(tables_to_check):
                        check_and_cleanup_table(table_id)
                        
                    # 再次广播更新统计信息
                    online_players = len(player_sessions)
                    active_tables = len(tables)
                    socketio.emit('stats_update', {
                        'online_players': online_players,
                        'active_tables': active_tables
                    })
            
            # 玩家断线：标记为断线状态，不移除玩家（30秒内可重连，页面跳转/刷新场景）
            for table_id, table in list(tables.items()):
                for player in table.players:
                    if player.id == player_id:
                        if player.status != PlayerStatus.BROKE:
                            player.status = PlayerStatus.DISCONNECTED
                            print(f"玩家 {nickname} 在房间 {table.title} 标记为断线")
                        # 广播更新的房间状态（其他玩家看到"断线"标识）
                        socketio.emit('table_updated', table.get_table_state(), room=table_id)
                        break
            
            socketio.start_background_task(remove_player_delayed)
            
            print(f"玩家 {nickname} 断线，会话已清理，等待重连...")
    except Exception as e:
        print(f"处理断线错误: {e}")


@socketio.on('register_player')
def handle_register_player(data):
    """处理玩家注册"""
    try:
        nickname = data.get('nickname', '').strip()
        if not nickname:
            emit('error', {'message': '昵称不能为空'})
            return
        
        # 检查是否已经有相同昵称的玩家在线
        existing_player = None
        for table_id, table in tables.items():
            for player in table.players:
                if player.nickname == nickname and not player.is_bot:
                    existing_player = player
                    break
            if existing_player:
                break
        
        # 清理当前会话的重复会话（基于昵称）
        old_sessions_to_remove = []
        for sid, session_info in player_sessions.items():
            if session_info['nickname'] == nickname and sid != request.sid:
                old_sessions_to_remove.append(sid)
        
        if old_sessions_to_remove:
            print(f"发现玩家 {nickname} 的重复会话，清理旧会话")
            for old_sid in old_sessions_to_remove:
                print(f"移除旧会话: {old_sid}")
                if old_sid in player_sessions:
                    del player_sessions[old_sid]
                if old_sid in session_tables:
                    del session_tables[old_sid]
                # 断开旧连接
                try:
                    socketio.disconnect(old_sid)
                except Exception as e:
                    print(f"断开旧连接失败: {e}")
            
            print(f"玩家 {nickname} 旧会话已清理")
        
        # 创建或获取玩家数据
        player_data = db.get_user_by_nickname(nickname)
        if not player_data:
            # 使用database.py的create_user方法创建用户
            player_id = db.create_user(nickname)
            player_data = db.get_user(player_id)
        
        if not player_data:
            emit('error', {'message': '玩家创建失败'})
            return
        
        # 注册会话
        session_id = request.sid
        player_sessions[session_id] = {
            'player_id': player_data['id'],
            'nickname': nickname,
            'timestamp': datetime.now()
        }
        
        print(f"玩家会话注册成功: {nickname} (ID: {player_data['id']}, Session: {session_id})")
        
        emit('register_response', {
            'success': True,
            'nickname': nickname,
            'player_id': player_data['id'],
            'chips': player_data.get('chips', 1000),
            'has_helper': player_data.get('has_helper', 0)
        })
        
        # 广播更新统计信息
        online_players = len(player_sessions)
        active_tables = len(tables)
        socketio.emit('stats_update', {
            'online_players': online_players,
            'active_tables': active_tables
        })
        
    except Exception as e:
        print(f"玩家注册错误: {e}")
        emit('error', {'message': '注册失败，请重试'})


@socketio.on('create_table')
def handle_create_table(data):
    """创建牌桌"""
    try:
        session_id = request.sid
        if session_id not in player_sessions:
            emit('error', {'message': '请先登录'})
            return
        
        player_info = player_sessions[session_id]
        player_id = player_info['player_id']
        nickname = player_info['nickname']
        
        # 获取创建参数
        title = data.get('name', data.get('title', '新牌桌')).strip()
        small_blind = int(data.get('small_blind', 10))
        big_blind = int(data.get('big_blind', 20))
        max_players = int(data.get('max_players', 9))
        initial_chips = int(data.get('initial_chips', 1000))
        bots_config = data.get('bots', {})
        
        # 验证参数
        if not title or len(title) > 50:
            emit('error', {'message': '房间名称无效'})
            return
        
        if small_blind <= 0 or big_blind <= small_blind or max_players < 2 or max_players > 9:
            emit('error', {'message': '游戏参数无效'})
            return
        
        # 生成房间ID
        import uuid
        table_id = str(uuid.uuid4())
        
        # 创建房间到数据库
        try:
            db_table_id = db.create_table(
                title=title,
                created_by=player_id,
                small_blind=small_blind,
                big_blind=big_blind,
                max_players=max_players,
                initial_chips=initial_chips
            )
            if db_table_id:
                table_id = db_table_id
        except Exception as e:
            print(f"数据库创建房间失败: {e}")
            emit('error', {'message': '创建房间失败，请重试'})
            return
        
        # 创建内存中的Table对象
        table = Table(
            table_id=table_id,
            title=title,
            small_blind=small_blind,
            big_blind=big_blind,
            max_players=max_players,
            initial_chips=initial_chips
        )
        
        tables[table_id] = table
        
        # 创建Player对象
        player_data = db.get_user(player_id)
        if not player_data:
            emit('error', {'message': '玩家数据获取失败'})
            return
        
        player = Player(player_id, nickname, initial_chips)
        
        # 创建者自动加入房间
        if table.add_player(player) and db.join_table(table_id, player_id):
            join_room(table_id)
            session_tables[session_id] = table_id
            
            # 添加机器人
            bots_added = 0
            total_bots_requested = 0
            if bots_config:
                from poker_engine.bot import Bot, BotLevel
                import uuid
                
                bot_names = {
                    'beginner': ['新手', '菜鸟', '学徒', '小白', '萌新'],
                    'intermediate': ['老司机', '高手', '大神', '专家', '老手'],
                    'advanced': ['大师', '传奇', '王者', '至尊', '无敌']
                }
                
                for level, count in bots_config.items():
                    if level in bot_names and count > 0:
                        total_bots_requested += count
                        available_names = bot_names[level]
                        
                        for i in range(count):
                            if len(table.players) >= max_players:
                                break
                                
                            bot_name = f"{available_names[i % len(available_names)]}{bots_added + 1}"
                            bot_id = str(uuid.uuid4())
                            
                            try:
                                level_enum = BotLevel[level.upper()]
                            except KeyError:
                                level_enum = BotLevel.BEGINNER
                            
                            bot = Bot(bot_id, bot_name, initial_chips, level_enum)
                            
                            if table.add_player(bot):
                                # 在users表中创建机器人记录
                                with db.get_connection() as conn:
                                    cursor = conn.cursor()
                                    current_time = time.time()
                                    cursor.execute('''
                                        INSERT OR IGNORE INTO users (id, nickname, chips, created_at, last_active)
                                        VALUES (?, ?, ?, ?, ?)
                                    ''', (bot_id, bot_name, initial_chips, current_time, current_time))
                                    conn.commit()
                                
                                # 将机器人也保存到数据库，正确设置is_bot标识
                                if db.join_table(table_id, bot_id):
                                    # 手动更新机器人的is_bot和bot_level字段
                                    with db.get_connection() as conn:
                                        cursor = conn.cursor()
                                        cursor.execute('''
                                            UPDATE table_players 
                                            SET is_bot = 1, bot_level = ?
                                            WHERE table_id = ? AND player_id = ?
                                        ''', (level_enum.value, table_id, bot_id))
                                        conn.commit()
                                        print(f"✅ 机器人 {bot_name} 数据库标识已更新: is_bot=1, bot_level={level_enum.value}")
                                bots_added += 1
                                print(f"机器人 {bot_name} ({level}) 加入房间 {title}")
                            else:
                                print(f"添加机器人 {bot_name} 失败")
            
            emit('room_created', {
                'success': True,
                'table_id': table_id,
                'message': f'房间 "{title}" 创建成功！添加了 {bots_added}/{total_bots_requested} 个机器人'
            })
            
            # 同时发送table_joined事件
            table_state = table.get_table_state()
            print(f"🔍 发送table_joined事件，玩家数: {len(table_state.get('players', []))}")
            for p in table_state.get('players', []):
                print(f"  - {p.get('nickname')} (is_bot: {p.get('is_bot')})")
            
            emit('table_joined', {
                'success': True,
                'table_id': table_id,
                'table': table_state
            })
            
            # 广播新房间创建给所有在大厅的用户
            socketio.emit('lobby_update', {
                'type': 'new_table',
                'table': {
                    'id': table_id,
                    'title': title,
                    'small_blind': small_blind,
                    'big_blind': big_blind,
                    'max_players': max_players,
                    'current_players': len([p for p in table.players if not p.is_bot]),
                    'game_stage': 'waiting',
                    'created_by': nickname
                }
            })
            
            # 广播更新统计信息
            online_players = len(player_sessions)
            active_tables = len(tables)
            socketio.emit('stats_update', {
                'online_players': online_players,
                'active_tables': active_tables
            })
            
            print(f"玩家 {player.nickname} 创建并加入房间 {title} (ID: {table_id}), 添加了 {bots_added} 个机器人")
        else:
            emit('error', {'message': '加入房间失败'})
            
    except Exception as e:
        print(f"创建房间失败: {e}")
        emit('error', {'message': f'创建房间失败: {str(e)}'})


@socketio.on('join_table')
def handle_join_table(data):
    """加入牌桌"""
    try:
        session_id = request.sid
        table_id = data.get('table_id')
        
        if session_id not in player_sessions:
            emit('error', {'message': '请先登录'})
            return
        
        if not table_id:
            emit('error', {'message': '房间ID无效'})
            return
        
        # 检查房间是否存在，先从内存检查，再从数据库检查
        table = tables.get(table_id)
        if not table:
            # 如果内存中没有，尝试从数据库加载
            db_table = db.get_table(table_id)
            if not db_table:
                emit('error', {'message': '房间不存在'})
                return
            
            # 重新创建内存中的Table对象
            table = Table(
                table_id=table_id,
                title=db_table['title'],
                small_blind=db_table['small_blind'],
                big_blind=db_table['big_blind'],
                max_players=db_table['max_players'],
                initial_chips=db_table['initial_chips']
            )
            tables[table_id] = table
            print(f"从数据库重新加载房间: {table.title}")
        
        player_id = player_sessions[session_id]['player_id']
        nickname = player_sessions[session_id]['nickname']
        
        # 动态获取或创建玩家对象
        player = players.get(player_id)
        if not player:
            # 从数据库获取玩家信息
            player_data = db.get_user(player_id)
            if not player_data:
                emit('error', {'message': '玩家数据不存在'})
                return
            # 创建玩家对象 - 使用表格的初始筹码设置
            player = Player(player_id, nickname, table.initial_chips)
            players[player_id] = player
            print(f"动态创建玩家对象: {nickname} (ID: {player_id})")
            # 将 has_helper 字段加入 player_sessions
            player_sessions[session_id]['has_helper'] = player_data.get('has_helper', 0)
        
        # 检查玩家是否已在房间中（重连情况）
        db_players = db.get_table_players(table_id)
        existing_player = None
        
        for db_player in db_players:
            if db_player['player_id'] == player_id:
                existing_player = db_player
                break
        
        if existing_player:
            # 玩家重连
            session_tables[session_id] = table_id
            join_room(table_id)
            
            # 重新加载所有玩家到内存（包括机器人）
            for db_player in db_players:
                table_player = table.get_player(db_player['player_id'])
                if not table_player:
                    # 内存中没有，需要重新添加
                    if db_player.get('is_bot', False):
                        # 重新创建机器人
                        from poker_engine.bot import Bot, BotLevel
                        try:
                            # 优先使用数据库中的机器人等级（创建/添加时已正确记录 bot_level）
                            print(f"🔄 重新创建机器人: {db_player['nickname']}")
                            db_level = db_player.get('bot_level')
                            if db_level:
                                try:
                                    level = BotLevel[db_level.upper()]
                                    print(f"  - 使用数据库等级: {db_level}")
                                except KeyError:
                                    level = BotLevel.BEGINNER
                                    print(f"  - 数据库等级无效({db_level})，默认为初级机器人")
                            else:
                                # 旧数据兜底：从nickname推断机器人等级
                                print(f"  - 数据库无等级记录，从昵称推断")
                                if '新手' in db_player['nickname'] or '菜鸟' in db_player['nickname'] or '学徒' in db_player['nickname'] or '小白' in db_player['nickname'] or '萌新' in db_player['nickname']:
                                    level = BotLevel.BEGINNER
                                    print(f"  - 检测为初级机器人")
                                elif '老司机' in db_player['nickname'] or '高手' in db_player['nickname'] or '大神' in db_player['nickname'] or '专家' in db_player['nickname'] or '老手' in db_player['nickname']:
                                    level = BotLevel.INTERMEDIATE
                                    print(f"  - 检测为中级机器人")
                                elif '大师' in db_player['nickname'] or '传奇' in db_player['nickname'] or '王者' in db_player['nickname'] or '至尊' in db_player['nickname'] or '无敌' in db_player['nickname']:
                                    level = BotLevel.ADVANCED
                                    print(f"  - 检测为高级机器人")
                                elif '德州之神' in db_player['nickname'] or '扑克天神' in db_player['nickname'] or '全知全能' in db_player['nickname'] or '透视眼' in db_player['nickname'] or '作弊之王' in db_player['nickname']:
                                    level = BotLevel.GOD
                                    print(f"  - 检测为德州扑克之神机器人")
                                else:
                                    level = BotLevel.BEGINNER
                                    print(f"  - 未匹配，默认为初级机器人")
                            
                            bot = Bot(db_player['player_id'], db_player['nickname'], db_player['chips'], level)
                            bot.current_bet = db_player['current_bet']
                            bot.status = PlayerStatus[db_player['status'].upper()]
                            table.add_player_at_position(bot, db_player['position'])
                            print(f"  - ✅ 机器人创建成功，等级: {bot.bot_level}, 类型: {type(bot.bot_level)}")
                        except Exception as e:
                            print(f"  - ❌ 重新创建机器人失败: {e}")
                            import traceback
                            traceback.print_exc()
                    else:
                        # 重新创建人类玩家
                        if db_player['player_id'] == player_id:
                            player.chips = db_player['chips']
                            player.current_bet = db_player['current_bet']
                            player.status = PlayerStatus[db_player['status'].upper()]
                            table.add_player_at_position(player, db_player['position'])
            
            table_state = table.get_table_state(player_id)
            # 标记是否处于下一轮投票阶段（一局结束后刷新页面也能恢复投票按钮）
            table_state['next_round_voting'] = (table.game_stage == GameStage.FINISHED)
            if table_state['next_round_voting']:
                human_players = [p for p in table.players if not p.is_bot]
                votes = next_round_votes.get(table_id, {})
                table_state['next_round_votes'] = len(votes)
                table_state['next_round_required'] = len(human_players)
                table_state['next_round_i_voted'] = player_id in votes

            emit('table_joined', {
                'success': True,
                'table_id': table_id,
                'table': table_state,
                'reconnected': True
            })
            
            # 恢复断线玩家的状态（页面跳转/刷新后的重连）
            table_player = table.get_player(player_id)
            if table_player and table_player.status == PlayerStatus.DISCONNECTED:
                if table_player.chips > 0:
                    table_player.status = (PlayerStatus.WAITING if table.game_stage == GameStage.WAITING
                                           else PlayerStatus.PLAYING)
                    print(f"玩家 {nickname} 重连，状态恢复为 {table_player.status.value}")
                else:
                    table_player.status = PlayerStatus.BROKE
                    print(f"玩家 {nickname} 重连，无筹码恢复为观察者")
            
            # 如果游戏正在进行且玩家有手牌，发送手牌
            table_player = table.get_player(player_id)
            if table_player and table.game_stage != GameStage.WAITING and len(table_player.hole_cards) == 2:
                emit('your_cards', {
                    'hole_cards': [card.to_dict() for card in table_player.hole_cards]
                })
                print(f"玩家 {player.nickname} 重连，发送手牌: {[f'{card.rank.symbol}{card.suit.value}' for card in table_player.hole_cards]}")
            
            print(f"玩家 {player.nickname} 重连到房间 {table.title}")
            return
        
        # 新玩家加入 - 处理选座位参数
        position = data.get('position')  # 从前端获取选择的座位
        if db.join_table(table_id, player_id, position):
            # 内存中也要加入指定位置
            if position is not None and table.add_player_at_position(player, position):
                session_tables[session_id] = table_id
                join_room(table_id)
            elif position is None and table.add_player(player):  # 兼容没有指定位置的情况
                session_tables[session_id] = table_id
                join_room(table_id)
            else:
                emit('error', {'message': f'座位{position + 1}已被占用或添加失败'})
                return
            
            emit('table_joined', {
                'success': True,
                'table_id': table_id,
                'table': table.get_table_state(player_id),
                'reconnected': False
            })
            
            # 向房间内其他玩家广播新玩家加入
            emit('player_joined', {
                'player': {
                    'id': player.id,
                    'nickname': player.nickname,
                    'chips': player.chips,
                    'position': table.get_player_position(player_id)
                }
            }, room=table_id, include_self=False)
            
            print(f"玩家 {player.nickname} 加入房间 {table.title}")
        else:
            emit('error', {'message': '无法加入房间'})
            
    except Exception as e:
        print(f"加入房间失败: {e}")
        emit('error', {'message': f'加入房间失败: {str(e)}'})


@socketio.on('get_table_state')
def handle_get_table_state(data):
    """手动获取牌桌状态 - 用于处理连接问题时的备用方案"""
    try:
        session_id = request.sid
        table_id = data.get('table_id')
        
        if session_id not in player_sessions:
            emit('error', {'message': '请先登录'})
            return
        
        if not table_id:
            emit('error', {'message': '房间ID无效'})
            return
        
        # 检查房间是否存在
        table = tables.get(table_id)
        if not table:
            emit('error', {'message': '房间不存在'})
            return
        
        player_id = player_sessions[session_id]['player_id']
        
        # 确保玩家在正确的Socket.IO房间中
        join_room(table_id)
        session_tables[session_id] = table_id
        
        # 发送牌桌状态
        table_state = table.get_table_state(player_id)
        print(f"🔄 手动发送牌桌状态给 {session_id}，玩家数: {len(table_state.get('players', []))}")
        for p in table_state.get('players', []):
            print(f"  - {p.get('nickname')} (is_bot: {p.get('is_bot')})")
        
        emit('table_joined', {
            'success': True,
            'table_id': table_id,
            'table': table_state,
            'reconnected': True  # 标记为重连，避免重复通知
        })
        
        # 如果玩家有手牌，也发送手牌信息
        table_player = table.get_player(player_id)
        if table_player and table.game_stage != GameStage.WAITING and len(table_player.hole_cards) == 2:
            emit('your_cards', {
                'hole_cards': [card.to_dict() for card in table_player.hole_cards]
            })
        
    except Exception as e:
        print(f"❌ 获取牌桌状态异常: {e}")
        traceback.print_exc()
        emit('error', {'message': '服务器错误'})


@socketio.on('add_bot')
def handle_add_bot(data):
    """添加机器人到牌桌"""
    try:
        session_id = request.sid
        if session_id not in player_sessions:
            emit('error', {'message': '请先登录'})
            return
        
        # 查找玩家所在的房间
        table_id = None
        for tid, table in tables.items():
            for player in table.players:
                if player.id == player_sessions[session_id]['player_id']:
                    table_id = tid
                    break
            if table_id:
                break
        
        if not table_id or table_id not in tables:
            emit('error', {'message': '您不在任何房间中'})
            return
        
        table = tables[table_id]
        
        # 检查房间是否已满
        if len(table.players) >= table.max_players:
            emit('error', {'message': '房间已满'})
            return
        
        # 获取机器人等级
        from poker_engine.bot import Bot, BotLevel
        import uuid
        
        level_str = data.get('level', 'beginner')
        try:
            level_enum = BotLevel[level_str.upper()]
        except KeyError:
            level_enum = BotLevel.BEGINNER
        
        # 生成机器人名称
        bot_names = {
            'beginner': ['新手', '菜鸟', '学徒', '小白', '萌新'],
            'intermediate': ['老司机', '高手', '大神', '专家', '老手'],
            'advanced': ['大师', '传奇', '王者', '至尊', '无敌'],
            'god': ['德州之神', '扑克天神', '全知全能', '透视眼', '作弊之王']
        }
        
        available_names = bot_names.get(level_str, ['机器人'])
        existing_bots = [p for p in table.players if p.is_bot]
        bot_name = f"{available_names[len(existing_bots) % len(available_names)]}{len(existing_bots) + 1}"
        
        # 创建机器人
        bot_id = str(uuid.uuid4())
        bot = Bot(bot_id, bot_name, table.initial_chips, level_enum)
        
        # 添加到房间
        if table.add_player(bot):
            # 同时添加到数据库，正确设置机器人标识
            if db.join_table(table_id, bot_id):
                # 手动更新机器人的is_bot和bot_level字段
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        UPDATE table_players 
                        SET is_bot = 1, bot_level = ?
                        WHERE table_id = ? AND player_id = ?
                    ''', (level_enum.value, table_id, bot_id))
                    conn.commit()
                    print(f"✅ 手动添加机器人 {bot_name} 数据库标识已更新: is_bot=1, bot_level={level_enum.value}")
            
            # 发送机器人添加成功消息
            socketio.emit('bot_added', {
                'success': True,
                'bot': bot.to_dict(),
                'message': f'机器人 {bot_name} ({level_str}) 已加入房间'
            }, room=table_id)
            
            # 广播更新后的桌面状态给所有玩家
            socketio.emit('table_updated', table.get_table_state(), room=table_id)
            
            print(f"机器人 {bot_name} ({level_str}) 加入房间 {table.title}")
        else:
            emit('error', {'message': '添加机器人失败'})
            
    except Exception as e:
        print(f"添加机器人失败: {e}")
        emit('error', {'message': f'添加机器人失败: {str(e)}'})



@socketio.on('start_hand')
def handle_start_hand():
    """开始手牌"""
    try:
        session_id = request.sid
        if session_id not in player_sessions:
            emit('error', {'message': '请先登录'})
            return
        
        # 查找玩家所在的房间
        table_id = None
        player_id = player_sessions[session_id]['player_id']
        
        for tid, table in tables.items():
            for player in table.players:
                if player.id == player_id:
                    table_id = tid
                    break
            if table_id:
                break
        
        if not table_id or table_id not in tables:
            emit('error', {'message': '您不在任何房间中'})
            return
        
        table = tables[table_id]
        
        # 检查玩家数量
        if len(table.players) < 2:
            emit('error', {'message': '至少需要2名玩家才能开始游戏'})
            return
        
        # 检查游戏状态
        if table.game_stage != GameStage.WAITING:
            emit('error', {'message': '游戏已在进行中'})
            return
        
        # 开始新手牌
        if table.start_new_hand():
            # 广播手牌开始事件
            socketio.emit('hand_started', {
                'table': table.get_table_state(),
                'message': '新手牌开始！'
            }, room=table_id)
            
            # 发送玩家手牌给各自的玩家
            for player in table.players:
                if not player.is_bot and player.hole_cards:
                    player_session = None
                    for sid, session in player_sessions.items():
                        if session['player_id'] == player.id:
                            player_session = sid
                            break
                    
                    if player_session:
                        print(f"📤 发送手牌给玩家 {player.nickname}: {[f'{card.rank.symbol}{card.suit.value}' for card in player.hole_cards]}")
                        socketio.emit('your_cards', {
                            'hole_cards': [card.to_dict() for card in player.hole_cards]
                        }, room=player_session)
            
            print(f"房间 {table.title} 开始新手牌")
            
            # 后台显示所有玩家的手牌
            print("=" * 50)
            print(f"🃏 新一轮玩家手牌信息 (手牌#{table.hand_number})：")
            for i, player in enumerate(table.players):
                if player.status == PlayerStatus.PLAYING and len(player.hole_cards) == 2:
                    card1 = player.hole_cards[0]
                    card2 = player.hole_cards[1]
                    card1_str = f"{card1.rank.symbol}{card1.suit.value}"
                    card2_str = f"{card2.rank.symbol}{card2.suit.value}"
                    player_type = "🤖" if player.is_bot else "👤"
                    print(f"  {player_type} {player.nickname}: {card1_str} {card2_str} (筹码: ${player.chips}, 状态: {player.status.value})")
            print(f"🎯 游戏阶段: {table.game_stage.value}")
            print(f"💰 当前底池: ${table.pot}")
            print(f"💵 当前投注: ${table.current_bet}")
            print("=" * 50)
            
            # 开始机器人处理和行动通知
            socketio.start_background_task(process_bot_actions_delayed, table_id)
        else:
            emit('error', {'message': '开始游戏失败'})
            
    except Exception as e:
        print(f"开始手牌失败: {e}")
        emit('error', {'message': f'开始游戏失败: {str(e)}'})


@socketio.on('player_action')
def handle_player_action(data):
    """处理玩家动作"""
    try:
        session_id = request.sid
        
        if session_id not in player_sessions:
            emit('error', {'message': '请先登录'})
            return
        
        if session_id not in session_tables:
            emit('error', {'message': '请先加入房间'})
            return
        
        player_id = player_sessions[session_id]['player_id']
        table_id = session_tables[session_id]
        table = tables.get(table_id)
        
        if not table:
            emit('error', {'message': '房间不存在'})
            return
        
        action_str = data.get('action')
        amount = data.get('amount', 0)
        
        if not action_str:
            emit('error', {'message': '无效的动作'})
            return
        
        # 转换字符串动作为枚举
        from poker_engine.player import PlayerAction
        action_map = {
            'fold': PlayerAction.FOLD,
            'check': PlayerAction.CHECK,
            'call': PlayerAction.CALL,
            'bet': PlayerAction.BET,
            'raise': PlayerAction.RAISE,
            'all_in': PlayerAction.ALL_IN
        }
        
        action = action_map.get(action_str.lower())
        if not action:
            emit('error', {'message': f'无效的动作: {action_str}'})
            return
        
        # 执行玩家动作
        result = table.process_player_action(player_id, action, amount)
        
        # 记录玩家动作到日志数据库
        if table_id in current_hands and result.get('success'):
            hand_id = current_hands[table_id]
            player = table.get_player(player_id)
            if player:
                log_player_action(
                    hand_id, player_id, player.nickname, action_str, 
                    amount, table.game_stage.value, 
                    player.chips + result.get('amount', 0),  # chips_before
                    player.chips  # chips_after
                )
        
        # 调试：打印result的完整内容
        print(f"🔍 玩家动作处理结果: {result}")
        
        if result.get('success'):
            # 发送动作处理结果
            emit('action_processed', {
                'table': table.get_table_state(),
                'action': result.get('action'),
                'player_id': player_id,
                'amount': result.get('amount', 0),
                'description': result.get('description', '')
            }, room=table_id)
            
            # 检查手牌是否结束
            hand_ended = False
            winners = []
            
            if result.get('hand_complete'):
                print(f"🏆 玩家动作直接导致手牌结束")
                hand_ended = True
                showdown_info = result.get('showdown_info', {})
                winner = result.get('winner')
            else:
                # 手牌未结束，处理机器人动作
                try:
                    print(f"👤 {result.get('description', '')} 完成，开始处理机器人动作...")
                    bot_result = process_bot_actions(table_id)  # 使用修改后的函数
                    print(f"🔍 机器人处理结果: {bot_result}")
                    
                    # 检查机器人动作后是否手牌结束
                    if bot_result and bot_result.get('hand_complete'):
                        print(f"🏆 机器人动作导致手牌结束")
                        hand_ended = True
                        showdown_info = bot_result.get('showdown_info', {})
                        winner = bot_result.get('winner')
                    # 注意：process_bot_actions已经会发送状态更新和行动通知了
                except Exception as bot_error:
                    print(f"处理机器人动作时出错: {bot_error}")
                    # 即使机器人处理出错，也要发送状态更新
                    emit('table_updated', table.get_table_state(), room=table_id)
            
            # 统一处理手牌结束后的状态记录
            if hand_ended:
                print(f"🏆 手牌结束，调用handle_hand_end函数")
                handle_hand_end(table_id, winner, showdown_info)
            
    except Exception as e:
        print(f"处理玩家动作失败: {e}")
        emit('error', {'message': f'动作执行失败: {str(e)}'})


@socketio.on('leave_table')
def handle_leave_table():
    """离开牌桌"""
    try:
        session_id = request.sid
        
        if session_id not in player_sessions:
            return
        
        if session_id not in session_tables:
            return
        
        player_id = player_sessions[session_id]['player_id']
        table_id = session_tables[session_id]
        table = tables.get(table_id)
        
        if table:
            # 从牌桌移除玩家
            table.remove_player(player_id)
            
            # 从数据库移除玩家
            db.leave_table(table_id, player_id)
            
            # 向房间内其他玩家广播玩家离开
            emit('player_left', {
                'player_id': player_id
            }, room=table_id, include_self=False)
            
            print(f"玩家 {player_id} 离开房间 {table.title}")
            
            # 立即检查是否需要清理房间
            check_and_cleanup_table(table_id)
        
        # 清理会话
        if session_id in session_tables:
            del session_tables[session_id]
        
        leave_room(table_id)
        
        # 广播大厅更新
        socketio.emit('lobby_update')
        
        # 获取统计信息并广播
        online_players = len(player_sessions)
        active_tables = len(tables)
        socketio.emit('stats_update', {
            'online_players': online_players,
            'active_tables': active_tables
        })
        
    except Exception as e:
        print(f"离开房间失败: {e}")


@socketio.on('dissolve_table')
def handle_dissolve_table(data):
    """解散房间（仅创建者）"""
    try:
        session_id = request.sid
        if session_id not in player_sessions:
            emit('error', {'message': '请先登录'})
            return
        
        table_id = data.get('table_id')
        if not table_id or table_id not in tables:
            emit('error', {'message': '房间不存在'})
            return
        
        player_id = player_sessions[session_id]['player_id']
        table = tables[table_id]
        
        # 校验创建者身份（以数据库记录为准）
        db_table = db.get_table(table_id)
        if not db_table or db_table.get('created_by') != player_id:
            emit('error', {'message': '只有房间创建者才能解散房间'})
            return
        
        title = table.title
        print(f"💥 创建者解散房间: {title} ({table_id})")
        
        # 通知房间内所有玩家（含创建者自己）
        socketio.emit('table_dissolved', {
            'table_id': table_id,
            'title': title,
            'message': f'房间 "{title}" 已被创建者解散'
        }, room=table_id)
        
        # 清理房间内所有玩家的会话绑定
        for sid, tid in list(session_tables.items()):
            if tid == table_id:
                del session_tables[sid]
        
        # 关闭数据库记录（标记 is_active=0 并清理玩家记录）
        db.close_specific_table(table_id)
        
        # 从内存中删除房间
        del tables[table_id]
        
        # 清理相关记录
        if table_id in next_round_votes:
            del next_round_votes[table_id]
        if table_id in table_sessions:
            del table_sessions[table_id]
        if table_id in current_hands:
            del current_hands[table_id]
        
        # 广播大厅更新
        socketio.emit('lobby_update')
        socketio.emit('stats_update', {
            'online_players': len(player_sessions),
            'active_tables': len(tables)
        })
        
        # 给创建者单独确认（如果创建者不在房间连接中）
        emit('table_dissolved', {
            'table_id': table_id,
            'title': title,
            'message': '房间已解散'
        })
        
    except Exception as e:
        print(f"解散房间失败: {e}")
        import traceback
        traceback.print_exc()
        emit('error', {'message': '解散房间失败'})


def check_and_cleanup_table(table_id):
    """立即检查并清理单个房间"""
    try:
        if table_id not in tables:
            return
        
        table = tables[table_id]
        human_players = [p for p in table.players if not p.is_bot]
        
        # 如果房间没有人类玩家，立即关闭
        if len(human_players) == 0:
            print(f"房间 {table.title} 没有人类玩家，立即关闭")
            
            # 从数据库关闭房间
            db.close_specific_table(table_id)
            
            # 从内存中删除房间
            if table_id in tables:
                del tables[table_id]
                print(f"从内存中清理房间: {table_id}")
            
            # 清理投票记录
            if table_id in next_round_votes:
                del next_round_votes[table_id]
                print(f"清理房间 {table_id} 的投票记录")
            
            return True
        
        return False
        
    except Exception as e:
        print(f"检查清理房间 {table_id} 时出错: {e}")
        return False

def cleanup_empty_tables():
    """定期清理空房间、机器人房间和长时间无活动的房间"""
    try:
        print("🧹 开始定期维护...")
        
        # 1. 使用数据库清理功能
        closed_count = db.close_empty_tables()
        
        # 2. 清理内存中的房间
        tables_to_remove = []
        for table_id, table in tables.items():
            should_remove = False
            
            # 检查是否为空房间
            if len(table.players) == 0:
                should_remove = True
                print(f"   发现空房间: {table.title}")
            
            # 检查是否只有机器人
            human_players = [p for p in table.players if not p.is_bot]
            if len(human_players) == 0 and len(table.players) > 0:
                should_remove = True
                print(f"   发现纯机器人房间: {table.title}")
            
            # 检查是否有破产玩家卡住的情况
            broke_players = [p for p in table.players if p.chips <= 0]
            if len(broke_players) > 0:
                print(f"   发现破产玩家 {len(broke_players)} 个在房间 {table.title}")
                # 移除破产玩家
                for player in broke_players:
                    if player in table.players:
                        table.players.remove(player)
                        print(f"     移除破产玩家: {player.nickname}")
            
            if should_remove:
                tables_to_remove.append(table_id)
        
        # 移除内存中的房间
        for table_id in tables_to_remove:
            if table_id in tables:
                table_title = tables[table_id].title
                del tables[table_id]
                print(f"   从内存中清理房间: {table_title}")
                
                # 清理相关的会话数据
                if table_id in next_round_votes:
                    del next_round_votes[table_id]
                if table_id in table_sessions:
                    del table_sessions[table_id]
                if table_id in current_hands:
                    del current_hands[table_id]
        
        # 3. 清理断开连接的玩家会话
        disconnected_sessions = []
        for session_id, session_info in player_sessions.items():
            # 检查会话是否还有效（这里可以添加更多检查）
            player_id = session_info.get('player_id')
            if not player_id:
                disconnected_sessions.append(session_id)
        
        for session_id in disconnected_sessions:
            if session_id in player_sessions:
                player_info = player_sessions[session_id]
                del player_sessions[session_id]
                print(f"   清理断开的会话: {player_info.get('nickname', 'Unknown')}")
        
        # 4. 优化数据库（每10次清理执行一次）
        import random
        if random.randint(1, 10) == 1:
            try:
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('PRAGMA optimize')
                    conn.commit()
                print("   📊 数据库优化完成")
            except Exception as e:
                print(f"   ❌ 数据库优化失败: {e}")
        
        total_cleaned = closed_count + len(tables_to_remove) + len(disconnected_sessions)
        if total_cleaned > 0:
            print(f"✅ 定期维护完成: 清理了 {total_cleaned} 项 (房间: {closed_count + len(tables_to_remove)}, 会话: {len(disconnected_sessions)})")
        else:
            print("✅ 定期维护完成: 无需清理")
            
        # 5. 显示当前状态
        print(f"📊 当前状态: {len(tables)} 个活跃房间, {len(player_sessions)} 个玩家会话")
        
    except Exception as e:
        print(f"❌ 清理房间时出错: {e}")
        import traceback
        traceback.print_exc()


@socketio.on('vote_next_round')
def handle_vote_next_round(data):
    """处理下一轮投票"""
    try:
        session_id = request.sid
        if session_id not in player_sessions:
            emit('error', {'message': '未找到玩家会话'})
            return
        
        table_id = data.get('table_id')
        print(f"🗳️ 投票请求: table_id={table_id}, 当前房间数={len(tables)}")
        print(f"🗳️ 当前房间列表: {list(tables.keys())}")
        
        # 检查房间是否存在
        if not table_id:
            print(f"❌ 无效的房间ID")
            emit('error', {'message': '无效的房间ID'})
            return
            
        if table_id not in tables:
            print(f"❌ 房间 {table_id} 不存在")
            # 尝试从数据库恢复房间信息或提示用户
            emit('error', {'message': '房间不存在，请重新创建房间'})
            return
        
        table = tables[table_id]
        player_id = player_sessions[session_id]['player_id']
        
        # 检查玩家是否在房间中
        player = None
        for p in table.players:
            if p.id == player_id:
                player = p
                break
        
        if not player:
            emit('error', {'message': '玩家不在房间中'})
            return
        
        # 初始化投票记录
        if table_id not in next_round_votes:
            next_round_votes[table_id] = {}
        
        # 记录投票
        next_round_votes[table_id][player_id] = True
        print(f"玩家 {player.nickname} 投票开始下一轮")
        
        # 机器人自动投票
        for p in table.players:
            if p.is_bot and p.id not in next_round_votes[table_id]:
                next_round_votes[table_id][p.id] = True
                print(f"机器人 {p.nickname} 自动投票开始下一轮")
        
        # 检查是否所有人类玩家都投票了
        all_voted = True
        human_players = [p for p in table.players if not p.is_bot]
        print(f"🗳️ 投票检查: 人类玩家数={len(human_players)}, 当前投票数={len(next_round_votes[table_id])}")
        
        for p in human_players:  # 只检查人类玩家
            if p.id not in next_round_votes[table_id]:
                all_voted = False
                print(f"🗳️ 玩家 {p.nickname} 还未投票")
                break
        
        if all_voted:
            print(f"✅ 所有人类玩家都已投票，准备开始下一轮")
        
        # 广播投票状态
        vote_status = {
            'votes': len(next_round_votes[table_id]),
            'required': len(human_players),
            'players_voted': [p.nickname for p in table.players if p.id in next_round_votes[table_id]]
        }
        socketio.emit('next_round_vote_update', vote_status, room=table_id)
        
        # 如果所有人都投票了，开始下一轮
        if all_voted:
            print(f"🎮 所有人投票完成，调用start_next_round")
            start_next_round(table_id)
                        
    except Exception as e:
        print(f"下一轮投票错误: {e}")
        emit('error', {'message': '投票失败'})

def start_next_round(table_id):
    """开始下一轮游戏"""
    try:
        if table_id not in tables:
            return
        
        table = tables[table_id]
        
        # 清理投票记录
        if table_id in next_round_votes:
            del next_round_votes[table_id]
        
        # 重置所有玩家状态
        for player in table.players:
            player.status = 'playing'
            player.current_bet = 0
            player.total_bet = 0
            player.has_acted = False
            player.hole_cards = []
        
        # 开始新手牌
        success = table.start_new_hand()
        print(f"🎮 table.start_new_hand() 返回: {success}")
        
        if not success:
            print(f"❌ 新手牌开始失败")
            return
        
        print(f"🎮 房间 {table.title} 开始下一轮")
        
        # 广播新手牌开始
        game_state = table.get_table_state()
        print(f"🎮 广播new_hand_started事件到房间 {table_id}")
        socketio.emit('new_hand_started', game_state, room=table_id)
        
        # 广播玩家手牌给各自的玩家
        for player in table.players:
            if not player.is_bot and player.hole_cards:
                player_session = None
                for sid, session in player_sessions.items():
                    if session['player_id'] == player.id:
                        player_session = sid
                        break
                
                if player_session:
                    print(f"📤 发送手牌给玩家 {player.nickname}: {[f'{card.rank.symbol}{card.suit.value}' for card in player.hole_cards]}")
                    socketio.emit('your_cards', {
                        'hole_cards': [card.to_dict() for card in player.hole_cards]
                    }, room=player_session)
        
        # 开始机器人处理
        socketio.start_background_task(process_bot_actions_delayed, table_id)
        
    except Exception as e:
        print(f"开始下一轮错误: {e}")

def process_bot_actions_delayed(table_id, delay=1):
    """延迟处理机器人动作"""
    import time
    time.sleep(delay)
    if table_id in tables:
        print(f"🤖 开始处理机器人动作 (table_id: {table_id})")
        process_bot_actions(table_id)

def handle_hand_end(table_id, winner, showdown_info):
    """处理手牌结束"""
    try:
        if table_id not in tables:
            print(f"❌ handle_hand_end: 房间 {table_id} 不存在")
            return
        
        table = tables[table_id]
        
        # 调试：打印传入的信息
        print(f"🏆 handle_hand_end 收到获胜者: {winner}")
        print(f"🏆 摊牌信息: {showdown_info}")
        
        # 确保 winner 是玩家对象，而不是字典
        winner_player = None
        if winner:
            if hasattr(winner, 'nickname'):
                # winner 是玩家对象
                winner_player = winner
                print(f"🎯 获胜者是Player对象: {winner_player.nickname}")
            elif isinstance(winner, dict):
                # winner 是字典，需要转换为玩家对象
                winner_id = winner.get('id')
                if winner_id:
                    winner_player = table.get_player(winner_id)
                if not winner_player:
                    # 如果找不到，根据昵称查找
                    winner_nickname = winner.get('nickname')
                    for player in table.players:
                        if player.nickname == winner_nickname:
                            winner_player = player
                            break
                print(f"🎯 获胜者是字典，转换为Player对象: {winner_player.nickname if winner_player else '未找到'}")
        else:
            print("🎯 没有获胜者信息")
        
        # 如果还没有找到获胜者，强制创建一个
        if not winner_player:
            print("⚠️ 没有获胜者信息，创建默认获胜者")
            if table.players:
                # 找筹码最多的玩家
                winner_player = max(table.players, key=lambda p: p.chips)
                print(f"🏆 创建默认获胜者: {winner_player.nickname}")
        
        # 记录手牌结束到数据库
        if table_id in current_hands:
            hand_id = current_hands[table_id]
            winner_id = winner_player.id if winner_player else None
            winner_nickname = winner_player.nickname if winner_player else None
            winning_amount = showdown_info.get('pot', table.pot)
            community_cards = [card.to_dict() for card in table.community_cards]
            
            log_hand_ended(hand_id, winner_id, winner_nickname, 
                          winning_amount, table.pot, community_cards, showdown_info)
        
        # 保存玩家筹码到数据库
        for player in table.players:
            if not player.is_bot:
                update_player_chips(player.id, player.chips)
        
        # 处理获胜者信息
        winner_list = []
        winner_message = "手牌结束"
        showdown_players = []
        
        if winner_player:
            # 计算获胜奖金 - 使用底池数量
            winning_amount = showdown_info.get('pot', table.pot)
            winner_list = [{
                'nickname': winner_player.nickname, 
                'chips': winner_player.chips,
                'amount': winning_amount  # 添加奖金信息
            }]
            if showdown_info.get('win_reason') == 'others_folded':
                winner_message = f"手牌结束，{winner_player.nickname} 获胜（其他玩家弃牌）"
            else:
                winner_message = f"手牌结束，{winner_player.nickname} 获胜"
        
        # 如果有摊牌信息，添加详细信息
        if showdown_info.get('is_showdown') and showdown_info.get('showdown_players'):
            print(f"🃏 处理摊牌信息，参与玩家数: {len(showdown_info['showdown_players'])}")
            showdown_players = []
            for i, player_info in enumerate(showdown_info['showdown_players']):
                print(f"  摊牌玩家{i+1}: {player_info['nickname']} - {player_info['hand_description']}")
                showdown_players.append({
                    'nickname': player_info['nickname'],
                    'is_bot': player_info['is_bot'],
                    'hole_cards': player_info['hole_cards'],
                    'hole_cards_str': player_info['hole_cards_str'],
                    'hand_description': player_info['hand_description'],
                    'rank': player_info['rank'],
                    'result': player_info['result'],
                    'winnings': player_info['winnings']
                })
        else:
            print(f"🃏 没有摊牌信息或不是摊牌: is_showdown={showdown_info.get('is_showdown')}, players={len(showdown_info.get('showdown_players', []))}")
        
        # 广播手牌结束信息和更新后的游戏状态
        updated_game_state = table.get_table_state()
        hand_ended_data = {
            'winners': winner_list,
            'message': winner_message,
            'table_state': updated_game_state,  # 包含更新后的筹码信息
            'showdown_info': {
                'is_showdown': showdown_info.get('is_showdown', False),
                'community_cards': showdown_info.get('community_cards', []),
                'showdown_players': showdown_players
            }
        }
        
        # 调试：打印摊牌数据
        print(f"🎯 发送hand_ended事件:")
        print(f"  - is_showdown: {hand_ended_data['showdown_info']['is_showdown']}")
        print(f"  - showdown_players数量: {len(hand_ended_data['showdown_info']['showdown_players'])}")
        if hand_ended_data['showdown_info']['showdown_players']:
            for i, player in enumerate(hand_ended_data['showdown_info']['showdown_players']):
                print(f"    玩家{i+1}: {player['nickname']} - {player['hand_description']}")
        
        socketio.emit('hand_ended', hand_ended_data, room=table_id)
        
        # 检查是否还有足够玩家继续游戏
        active_players = [p for p in table.players if p.chips > 0]
        if len(active_players) < 2:
            socketio.emit('game_over', {
                'message': '游戏结束，玩家筹码不足'
            }, room=table_id)
            return
        
        # 提示开始下一轮投票
        human_players = [p for p in table.players if not p.is_bot]
        if len(human_players) > 0:
            socketio.emit('show_next_round_vote', {
                'message': '准备开始下一轮？',
                'required_votes': len(human_players)
            }, room=table_id)
        else:
            # 如果只有机器人，自动开始下一轮
            socketio.start_background_task(start_next_round, table_id)
        
    except Exception as e:
        print(f"处理手牌结束错误: {e}")


@app.route('/api/table_players')
def api_table_players():
    """返回指定房间所有玩家及其座位信息，供前端选座"""
    table_id = request.args.get('table_id')
    if not table_id:
        return jsonify({'success': False, 'message': '缺少table_id'}), 400
    try:
        players = db.get_table_players(table_id)
        db_table = db.get_table(table_id)
        max_players = db_table['max_players'] if db_table else 6
        return jsonify({'success': True, 'players': players, 'max_players': max_players})
    except Exception as e:
        print(f"/api/table_players error: {e}")
        return jsonify({'success': False, 'message': '服务器错误'}), 500


@app.route('/api/game_history')
def api_game_history():
    """获取游戏历史记录"""
    table_id = request.args.get('table_id')
    limit = request.args.get('limit', 10, type=int)
    
    if not table_id:
        return jsonify({'success': False, 'message': '缺少table_id参数'}), 400
    
    try:
        from game_logger import game_logger
        
        with game_logger.get_connection() as conn:
            cursor = conn.cursor()
            
            # 获取游戏会话信息
            cursor.execute('''
                SELECT * FROM game_sessions 
                WHERE table_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            ''', (table_id,))
            session = cursor.fetchone()
            
            # 获取手牌记录
            cursor.execute('''
                SELECT id, hand_number, started_at, ended_at, status, stage,
                       pot, winner_id, winner_nickname, winning_amount, community_cards
                FROM hands 
                WHERE table_id = ?
                ORDER BY hand_number DESC
                LIMIT ?
            ''', (table_id, limit))
            hands = cursor.fetchall()
            
            # 获取玩家动作记录
            cursor.execute('''
                SELECT pa.hand_id, pa.player_nickname, pa.action_type, 
                       pa.amount, pa.stage, pa.timestamp
                FROM player_actions pa
                JOIN hands h ON pa.hand_id = h.id
                WHERE h.table_id = ?
                ORDER BY pa.timestamp DESC
                LIMIT ?
            ''', (table_id, limit * 5))  # 获取更多动作记录
            actions = cursor.fetchall()
            
            # 格式化数据
            session_data = None
            if session:
                session_data = {
                    'id': session[0],
                    'table_id': session[1],
                    'table_title': session[2],
                    'created_at': session[3],
                    'ended_at': session[4],
                    'status': session[5],
                    'player_count': session[6],
                    'bot_count': session[7],
                    'total_hands': session[8]
                }
            
            hands_data = []
            for hand in hands:
                community_cards = json.loads(hand[10]) if hand[10] else []
                hands_data.append({
                    'id': hand[0],
                    'hand_number': hand[1],
                    'started_at': hand[2],
                    'ended_at': hand[3],
                    'status': hand[4],
                    'stage': hand[5],
                    'pot': hand[6],
                    'winner_id': hand[7],
                    'winner_nickname': hand[8],
                    'winning_amount': hand[9],
                    'community_cards': community_cards
                })
            
            actions_data = []
            for action in actions:
                actions_data.append({
                    'hand_id': action[0],
                    'player_nickname': action[1],
                    'action_type': action[2],
                    'amount': action[3],
                    'stage': action[4],
                    'timestamp': action[5]
                })
            
            return jsonify({
                'success': True,
                'session': session_data,
                'games': hands_data,  # 使用 'games' 键名与测试兼容
                'actions': actions_data,
                'total_records': len(hands_data)
            })
            
    except Exception as e:
        print(f"获取游戏历史失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'获取游戏历史失败: {str(e)}'
        }), 500


if __name__ == '__main__':
    import os
    # 只在主进程中执行初始化（避免debug模式重复加载）
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        print("🃏 德州扑克游戏服务器启动中...")
        print("📊 数据库初始化完成")
        
        # 启动时进行数据库修复和清理
        print("🔧 执行启动修复...")
        try:
            import subprocess
            result = subprocess.run(['python', 'fix_database_issues.py'], 
                                  capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                print("✅ 数据库修复完成")
            else:
                print(f"⚠️ 数据库修复警告: {result.stderr}")
        except Exception as e:
            print(f"⚠️ 数据库修复失败: {e}")
        
        # 启动时清理空房间
        print("🧹 初始清理...")
        cleanup_empty_tables()
        
        # 启动定期维护任务
        import threading
        def periodic_maintenance():
            import time
            while True:
                time.sleep(180)  # 每3分钟维护一次（更频繁）
                try:
                    cleanup_empty_tables()
                except Exception as e:
                    print(f"❌ 定期维护出错: {e}")
        
        # 启动长期清理任务  
        def long_term_cleanup():
            import time
            while True:
                time.sleep(3600)  # 每小时执行一次深度清理
                try:
                    print("🔧 执行每小时深度维护...")
                    import subprocess
                    result = subprocess.run(['python', 'fix_database_issues.py'], 
                                          capture_output=True, text=True, timeout=60)
                    if result.returncode == 0:
                        print("✅ 深度维护完成")
                    else:
                        print(f"⚠️ 深度维护警告")
                except Exception as e:
                    print(f"❌ 深度维护失败: {e}")
        
        # 启动维护线程
        maintenance_thread = threading.Thread(target=periodic_maintenance, daemon=True)
        maintenance_thread.start()
        
        cleanup_thread = threading.Thread(target=long_term_cleanup, daemon=True)
        cleanup_thread.start()
        
        print("🌐 服务器地址: http://192.168.178.39:5000")
        print("🎮 游戏已准备就绪！")
        print("⚙️ 自动维护已启动 (每3分钟快速维护，每小时深度维护)")
    
    socketio.run(app, host='0.0.0.0', port=8888, debug=True) 