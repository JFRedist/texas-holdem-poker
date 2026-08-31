/**
 * 国际化支持 (i18n)
 * 用法：
 *   静态文本: <span data-i18n="跟注">跟注</span>  （init 时自动替换）
 *   动态文本: I18N.t('跟注')  或  I18N.t('赢家: {0}', name)
 *   切换语言: I18N.setLang('en') / I18N.setLang('zh')（持久化到 localStorage 并刷新页面）
 */
(function () {
    // 英文翻译字典（key = 中文原文，zh 时直接返回原文）
    const EN = {
        // ===== 通用 / 导航 =====
        '德州扑克': 'Poker',
        '退出游戏': 'Exit',
        '玩家: {0}': 'Player: {0}',
        '确定要退出游戏吗？': 'Are you sure you want to exit?',
        '与服务器断开连接': 'Disconnected from server',
        '重连成功！': 'Reconnected!',
        '重连失败，请刷新页面': 'Reconnect failed, please refresh',
        '连接错误': 'Connection error',

        // ===== 主页 index =====
        '德州扑克游戏': 'Texas Hold\'em Poker',
        '德州扑克游戏 - 主页': 'Texas Hold\'em Poker - Home',
        '德州扑克游戏 - 大厅': 'Texas Hold\'em Poker - Lobby',
        '德州扑克游戏 - 牌桌': 'Texas Hold\'em Poker - Table',
        '输入昵称开始游戏': 'Enter nickname to start',
        '进入游戏': 'Play',
        '请输入昵称': 'Please enter a nickname',

        // ===== 大厅 lobby =====
        '房间列表': 'Rooms',
        '个房间': 'room(s)',
        '暂无房间': 'No rooms yet',
        '成为第一个创建房间的玩家吧！': 'Be the first to create a room!',
        '创建第一个房间': 'Create the first room',
        '选择一个房间开始游戏，或创建新房间': 'Pick a room to play, or create a new one',
        '创建房间': 'Create Room',
        '创建新房间': 'Create New Room',
        '房间名称': 'Room Name',
        '输入房间名称': 'Enter room name',
        '最大玩家数': 'Max Players',
        '初始筹码': 'Starting Chips',
        '游戏模式': 'Game Mode',
        '盲注模式': 'Blinds',
        '按比例下注': 'Ante (percentage)',
        '小盲': 'Small Blind',
        '大盲': 'Big Blind',
        '机器人配置': 'Bot Setup',
        '初级': 'Beginner',
        '中级': 'Intermediate',
        '高级': 'Advanced',
        '创建者: {0}': 'Created by: {0}',
        '创建者': 'Creator',
        '(我)': '(me)',
        '加入房间': 'Join',
        '进入房间': 'Enter Room',
        '房间已满': 'Full',
        '等待中': 'Waiting',
        '翻牌前': 'Pre-Flop',
        '翻牌': 'Flop',
        '转牌': 'Turn',
        '河牌': 'River',
        '摊牌': 'Showdown',
        '已结束': 'Finished',
        '玩家:': 'Players:',
        '模式:': 'Mode:',
        '盲注:': 'Blinds:',
        '按比例({0}%)': 'Ante ({0}%)',
        '在线玩家': 'Online Players',
        '活跃房间': 'Active Rooms',
        '玩家': 'Players',
        '选择座位': 'Choose a seat',
        '请选择座位：': 'Please choose a seat:',
        '座位{0}': 'Seat {0}',
        '成功加入房间！': 'Joined the room!',
        '加入房间失败': 'Failed to join room',
        '房间创建成功！': 'Room created!',
        '创建房间失败': 'Failed to create room',
        '房间 "{0}" 创建成功！添加了 {1}/{2} 个机器人': 'Room "{0}" created! Added {1}/{2} bots',
        '新房间 "{0}" 已创建！': 'New room "{0}" created!',
        '加载房间列表失败': 'Failed to load rooms',
        '网络错误': 'Network error',
        '确定要解散这个房间吗？\n房间内所有玩家将被移出，此操作不可恢复！': 'Dissolve this room?\nAll players will be removed. This cannot be undone!',
        '解散请求已发送...': 'Dissolve request sent...',
        '房间已解散': 'Room dissolved',
        '房间 "{0}" 已被创建者解散': 'Room "{0}" was dissolved by its creator',
        '获取房间信息失败': 'Failed to get room info',
        '获取房间信息失败，请重试': 'Failed to get room info, please retry',
        '进入房间失败': 'Failed to enter room',
        '请先登录': 'Please log in first',

        // ===== 牌桌 table =====
        '底池': 'Pot',
        '当前下注': 'Current Bet',
        '手牌': 'Hand',
        '公共牌': 'Community Cards',
        '您的手牌': 'Your Cards',
        '弃牌': 'Fold',
        '过牌': 'Check',
        '跟注': 'Call',
        '下注': 'Bet',
        '加注': 'Raise',
        '全下': 'All-in',
        '确认': 'Confirm',
        '取消': 'Cancel',
        '输入金额': 'Enter amount',
        '输入下注金额': 'Enter bet amount',
        '输入加注金额': 'Enter raise amount',
        '最小加注: ${0}': 'Min raise: ${0}',
        '开始游戏': 'Start Game',
        '添加机器人': 'Add Bot',
        '离开牌桌': 'Leave Table',
        '开始下一轮': 'Next Round',
        '已投票': 'Voted',
        '准备开始下一轮？': 'Ready for the next round?',
        '等待玩家投票...': 'Waiting for players to vote...',
        '投票进度: {0}/{1}': 'Votes: {0}/{1}',
        '已投票: {0}': 'Voted: {0}',
        '游戏中': 'In Game',
        '弃牌': 'Folded',
        '全下': 'All-in',
        '观察者 (无筹码)': 'Observer (broke)',
        '断线': 'Disconnected',
        '庄家': 'Dealer',
        '小盲': 'Small Blind',
        '大盲': 'Big Blind',
        '筹码': 'Chips',
        '下注': 'Bet',
        '投入': 'Contributed',
        '还需跟注 ${0}': 'Call ${0} more',
        '你的回合': 'Your Turn',
        '行动中': 'Thinking',
        '机器人行动中': 'Bot acting',
        '牌型分析': 'Hand Analysis',
        '公共牌最佳': 'Best board hand',
        '我的牌型': 'My hand',
        '对单对手胜率': 'Win rate vs 1 opponent',
        '对手可能牌型分布 ({0} 种组合):': 'Opponent hand distribution ({0} combos):',
        '计算耗时 {0}ms': 'Computed in {0}ms',
        '高牌': 'High Card',
        '一对': 'Pair',
        '两对': 'Two Pair',
        '三条': 'Three of a Kind',
        '顺子': 'Straight',
        '同花': 'Flush',
        '葫芦': 'Full House',
        '四条': 'Four of a Kind',
        '同花顺': 'Straight Flush',
        '皇家同花顺': 'Royal Flush',
        '{0}高牌': '{0} High',
        '一对{0}': 'Pair of {0}s',
        '{0}和{1}两对': '{0} and {1} Two Pair',
        '三条{0}': 'Three {0}s',
        '{0}高顺子': '{0}-high Straight',
        '{0}高同花': '{0}-high Flush',
        '{0}满{1}': '{0}s full of {1}s',
        '四条{0}': 'Four {0}s',
        '{0}高同花顺': '{0}-high Straight Flush',
        '游戏状态': 'Game State',
        '刷新': 'Refresh',
        '操作记录': 'Action Log',
        '暂无操作记录': 'No actions yet',
        '个人记录': 'My Stats',
        '查看历史': 'History',
        '点击查看历史记录加载个人统计': 'Click to view history',
        '新手牌开始！': 'New hand started!',
        '等待发牌...': 'Waiting for cards...',
        '手牌已发放！': 'Cards dealt!',
        '您没有筹码了，只能观察游戏': 'You are broke and can only observe',
        '轮到您行动': 'Your turn',
        '等待 {0} 行动': 'Waiting for {0}',
        '跟注 ${0}': 'Call ${0}',
        '下注 ${0}': 'Bet ${0}',
        '加注到 ${0}': 'Raise to ${0}',
        '全下 ${0}': 'All-in ${0}',
        '获胜！赢得 ${0}': 'wins ${0}!',
        '恭喜！您现在有 ${0} 筹码': 'Congrats! You now have ${0} chips',
        '摊牌结果': 'Showdown Result',
        '获胜结果（其他玩家弃牌）': 'Result (everyone folded)',
        '玩家排名': 'Ranking',
        '赢得 ${0}': 'won ${0}',
        '败北': 'lost',
        '公共牌': 'Board',
        '确定': 'OK',
        '点击确定或背景关闭': 'Click OK or outside to close',
        '房间已被创建者解散': 'Room was dissolved by its creator',
        '房间已被解散': 'Room has been dissolved',
        '手牌结束': 'Hand ended',
        '机器人 {0} ({1}) 正在思考... ({2}秒)': 'Bot {0} ({1}) is thinking... ({2}s)',
        '正在思考 ({0})': 'thinking ({0})',
        '游戏已结束，玩家筹码不足': 'Game over, not enough chips',
        '开始下一局': 'Next hand',
        '牌桌': 'Table',
        '游戏模式': 'Game Mode',
        '模式': 'Mode',
        '第{0}手开始': 'Hand #{0} started',
        '离开牌桌': 'Leave',
        '断线重连': 'Reconnecting...',
        '连接断开，正在重连...': 'Connection lost, reconnecting...',
        '重新连接成功！': 'Reconnected!',
        '成功加入牌桌！': 'Joined the table!',
        '您有 {0} 筹码': 'You have {0} chips',
        '添加机器人成功': 'Bot added',
        '机器人 {0} ({1}) 已加入房间': 'Bot {0} ({1}) joined the room',
        '房间已满': 'Room is full',
        '获取牌桌状态失败': 'Failed to get table state',
        '服务器错误': 'Server error',
        '暂无活跃房间': 'No active rooms',
        '创建一个新房间开始游戏吧！': 'Create a new room to start playing!',
        '解散': 'Dissolve',
        '解散房间（仅创建者）': 'Dissolve room (creator only)',
        '模式:': 'Mode:',
        '盲注:': 'Blinds:',
        '玩家:': 'Players:',
        '未知': 'Unknown',
        '游戏大厅': 'Game Lobby',
        '刷新列表': 'Refresh',
        '在线玩家': 'Online',
        '下注比例': 'Ante %',
        '初级机器人': 'Beginner Bot',
        '中级机器人': 'Intermediate Bot',
        '高级机器人': 'Advanced Bot',
        '本地局域网多人游戏': 'Local multiplayer game',
        '输入您的昵称': 'Enter your nickname',
        '请输入昵称（1-20个字符）': 'Nickname (1-20 characters)',
        '支持中文、英文、数字和常用符号': 'Supports Chinese, English, digits and common symbols',
        '进入大厅': 'Enter Lobby',
        '游戏特色': 'Features',
        '支持多人在线对战': 'Multiplayer online battles',
        '智能AI机器人陪练': 'Smart AI bot opponents',
        '实时胜率计算工具': 'Real-time win rate calculator',
        '记牌助手功能': 'Card tracking assistant',
        '标准德州扑克规则': 'Standard Texas Hold\'em rules',
        '局域网专用版本': 'Version 1.0 | LAN Edition',
        '支持现代浏览器，推荐Chrome/Edge/Firefox': 'Modern browsers recommended: Chrome/Edge/Firefox',
        '请输入昵称': 'Please enter a nickname',
        '昵称长度不能超过20个字符': 'Nickname must be at most 20 characters',
        '加入中...': 'Joining...',
        '欢迎，{0}！': 'Welcome, {0}!',
        '加入失败': 'Failed to join',
        '网络错误，请重试': 'Network error, please retry',
        '(你)': '(you)',
        '等待中': 'Waiting',
        '游戏中': 'In Game',
        '观察者 (无筹码)': 'Observer (broke)',
        '按比例:': 'Ante:',
        '盲注:': 'Blinds:',
        '我的牌型:': 'My hand:',
        '对单对手胜率:': 'Win rate:',
        '公共牌最佳:': 'Best board hand:',
        '翻牌后显示牌型分析': 'Analysis appears after the flop',
        '获胜！赢得 ${0}': 'wins ${0}!',
        '获胜结果（其他玩家弃牌）': 'Result (everyone folded)',
        '摊牌结果': 'Showdown Result',
        '赢得 ${0}': 'won ${0}',
        '败北': 'lost',
        '点击确定或背景关闭': 'Click OK or outside to close',
        '等待发牌...': 'Waiting for cards...',
        '新手牌开始！': 'New hand started!',
        '成功加入牌桌！': 'Joined the table!',
        '重新连接成功！': 'Reconnected!',
        '您没有筹码了，只能观察游戏': 'You are broke and can only observe',
        '投票进度: {0}/{1}': 'Votes: {0}/{1}',
        '已投票: {0}': 'Voted: {0}',
        '对手可能牌型分布 ({0} 种组合):': 'Opponent hand distribution ({0} combos):',
        '计算耗时 {0}ms': 'Computed in {0}ms',
        '还需跟注 ${0}': 'Call ${0} more',
        '底池:': 'Pot:',
        '当前下注:': 'Current Bet:',
        '手牌:': 'Hand:',
        '拖动调整下注金额': 'Drag to adjust bet amount',
        '点击刷新查看状态': 'Click refresh to view state',
    };

    const I18N = {
        lang: localStorage.getItem('lang') || 'zh',

        t(text, ...args) {
            if (!text) return text;
            let out = text;
            if (this.lang === 'en') {
                out = EN[text] || text;
            }
            // 替换 {0} {1} 占位符
            if (args.length > 0) {
                args.forEach((a, i) => { out = out.replace(new RegExp('\\{' + i + '\\}', 'g'), a); });
            }
            return out;
        },

        // 初始化：替换所有 data-i18n 标记的静态文本
        init() {
            document.documentElement.lang = this.lang === 'en' ? 'en' : 'zh-CN';
            document.querySelectorAll('[data-i18n]').forEach(el => {
                const key = el.getAttribute('data-i18n');
                el.textContent = this.t(key);
            });
            document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
                const key = el.getAttribute('data-i18n-placeholder');
                el.placeholder = this.t(key);
            });
            document.querySelectorAll('[data-i18n-title]').forEach(el => {
                const key = el.getAttribute('data-i18n-title');
                el.title = this.t(key);
            });
        },

        setLang(lang) {
            localStorage.setItem('lang', lang);
            location.reload();
        },

        toggle() {
            this.setLang(this.lang === 'en' ? 'zh' : 'en');
        }
    };

    window.I18N = I18N;

    // 页面加载时初始化
    document.addEventListener('DOMContentLoaded', () => {
        I18N.init();
    });
})();
