# 🃏 德州扑克 / Texas Hold'em Poker

基于 Flask + Socket.IO 的网页版多人德州扑克，支持真人与 AI 机器人同桌对战、实时牌型分析、摊牌记录与背景音乐。

A web-based multiplayer Texas Hold'em game built with Flask + Socket.IO — play against humans and AI bots, with live hand analysis, showdown history and background music.

![GitHub stars](https://img.shields.io/github/stars/JFRedist/texas-holdem-poker?style=social)
![GitHub forks](https://img.shields.io/github/forks/JFRedist/texas-holdem-poker?style=social)
![GitHub license](https://img.shields.io/github/license/JFRedist/texas-holdem-poker)
![Python version](https://img.shields.io/badge/python-3.8%2B-blue)
[![Upstream](https://img.shields.io/badge/Upstream-Jason%20He-blue)](https://github.com/stars1210JasonHe/texas-holdem-poker)

> 🔱 本仓库 Fork 自 [Jason He](https://github.com/stars1210JasonHe) 的 [原项目](https://github.com/stars1210JasonHe/texas-holdem-poker)，由 [JFRedist](https://github.com/JFRedist) 维护，新增了牌型分析、中英文界面、房间解散等功能并修复了若干问题，详见 [CHANGELOG](CHANGELOG.md)。
>
> 🔱 Forked from the [original project](https://github.com/stars1210JasonHe/texas-holdem-poker) by [Jason He](https://github.com/stars1210JasonHe) and maintained by [JFRedist](https://github.com/JFRedist). See the [CHANGELOG](CHANGELOG.md) for what's new in this fork.

[中文](#中文) | [English](#english)

---

## 中文

### ✨ 功能特性

**游戏**
- 标准德州扑克规则，2–9 人同桌，盲注随庄家轮换（单挑局庄家即小盲）
- 盲注模式 / 按比例下注两种房间模式，可自定义盲注、初始筹码和人数
- 四个等级的 AI 机器人，逐个决策、节奏自然
- 无需注册，输入昵称即可开始；断线后 30 秒内可重连回原座位
- 房间创建者可一键解散房间
- 中英文界面一键切换

**辅助**（仅纯人机练习时启用；牌桌上有 2 名及以上真人时自动关闭，保证公平）
- 牌型分析面板：公共牌最佳牌型、我的当前牌型与单挑胜率、对手可能牌型分布
- 记牌助手：已出现的牌与剩余牌组
- 玩家卡片显示当前下注、本手累计投入及庄家 / 小盲 / 大盲徽章
- 下注金额滑块，与输入框双向联动
- 零筹码玩家可继续观战

**数据与音乐**
- SQLite 持久化玩家、房间与牌局状态，服务重启后可恢复
- 摊牌记录与个人统计（胜率、奖金、手牌历史）
- 根据场景自动切换的背景音乐（大厅 / 牌桌 / 紧张时刻），无需音乐文件即可播放

### 🚀 快速开始

环境要求：Python 3.8+（Python 3.13 需要 `pip install "eventlet>=0.37"`）和一个现代浏览器。

```bash
git clone https://github.com/JFRedist/texas-holdem-poker.git
cd texas-holdem-poker

python -m venv poker_env
# Windows
poker_env\Scripts\activate
# macOS / Linux
source poker_env/bin/activate

pip install -r requirements.txt
python app.py
```

浏览器打开 <http://localhost:8888>，输入昵称即可进入大厅。启动时会打印「📱 局域网访问」地址，同一 Wi-Fi 下的手机、电脑打开它即可同桌。

> 其他设备连不上时依次检查：① 设备是否连在同一个 Wi-Fi（访客网络、校园网通常会隔离设备）；② Windows 防火墙是否允许 Python 接收连接（首次启动弹窗时要勾选「公用网络」，或把网络设为「专用」）；③ 如果开着 NordVPN 等 VPN，需要在 VPN 设置中允许局域网访问（NordVPN：关闭「局域网隐身 / Invisibility on LAN」）。

**环境变量（可选）**

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `POKER_HOST` | `0.0.0.0` | 监听地址 |
| `POKER_PORT` | `8888` | 监听端口 |
| `POKER_DEBUG` | `true` | 是否开启 Flask debug 模式 |
| `POKER_ASYNC_MODE` | `eventlet` | Socket.IO 异步模式；无法安装 eventlet 的环境（如 Android 内置服务器）可设为 `threading` |

### 🎮 游戏指南

**操作**：过牌（Check）、跟注（Call）、下注 / 加注（Bet / Raise，可拖动滑块）、弃牌（Fold）、全下（All-in）。

**创建房间**：在大厅设置房间名称、游戏模式（盲注 / 按比例下注）、小盲与大盲、初始筹码（500–10,000）和最大人数（2 / 4 / 6 / 9），并可直接添加机器人。

**机器人等级**

| 等级 | 风格 |
| --- | --- |
| 初级 Beginner | 保守，适合新手练习 |
| 中级 Intermediate | 攻守平衡 |
| 高级 Advanced | 激进，善于诈唬 |
| 德州之神 God | 能看到所有玩家手牌 |

**背景音乐**：开箱即用——没有音乐文件时会用浏览器实时合成的内置音乐（大厅爵士、牌桌行走贝斯、轮到你行动时切换为紧张节奏）。想换成自己的曲子，把 `lobby-music.mp3`、`table-music.mp3`、`action-music.mp3` 放入 `static/audio/` 即可（见该目录下的 README）。浏览器拦截自动播放时，点击页面任意位置即开始播放。快捷键：`M` 播放 / 暂停，`Ctrl+H` 显示 / 隐藏音乐面板。

### 📁 项目结构

```
├── app.py                  # Flask 应用、HTTP 接口与 Socket.IO 事件
├── poker_engine/           # 游戏引擎：牌、玩家、机器人、牌型评估、牌桌流程
├── database.py             # 房间与玩家数据
├── db_adapter.py
├── player_persistence.py   # 玩家筹码持久化
├── table_state_manager.py  # 牌桌状态保存与恢复
├── game_logger.py          # 牌局与摊牌记录
├── templates/              # 页面：主页、大厅、牌桌
└── static/                 # 前端脚本（i18n、音乐播放器）、样式与音频
```

### 🌐 部署

```bash
pip install gunicorn
gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:8888 app:app
```

只能使用单个 worker（`-w 1`），因为游戏状态保存在进程内存中。反向代理需要支持 WebSocket，Nginx 配置示例见 [English 部分](#-deployment)。

### 🤝 参与贡献

欢迎提交 Issue 和 Pull Request。提交信息请使用 [Conventional Commits](https://www.conventionalcommits.org/) 格式（`feat:` / `fix:` / `docs:` …），Python 代码遵循 PEP 8。

### 📄 许可证与联系方式

- 许可证：[MIT](LICENSE)
- 问题反馈：[GitHub Issues](https://github.com/JFRedist/texas-holdem-poker/issues)
- 维护者：[JFRedist](https://github.com/JFRedist) · Zi_Feng666@126.com
- 原作者：[Jason He](https://github.com/stars1210JasonHe) · [上游仓库](https://github.com/stars1210JasonHe/texas-holdem-poker)

---

## English

### ✨ Features

**Gameplay**
- Standard Hold'em rules for 2–9 players, with blinds rotating with the button (heads-up: dealer posts the small blind)
- Two room modes — blinds or proportional betting — with configurable blinds, starting stack and seats
- AI bots at four levels, acting one at a time at a natural pace
- No sign-up: enter a nickname and play; reconnect to your seat within 30 seconds after a disconnect
- Room creators can dissolve a room with one click
- One-click Chinese / English UI switch

**Assistance** (bot practice only — turned off automatically when 2 or more humans are at the table)
- Hand analysis panel: best board hand, your current hand and heads-up equity, opponent hand distribution
- Card tracker showing revealed cards and the remaining deck
- Player cards show current bet, total put in this hand, and Dealer / SB / BB badges
- Bet slider synced with the amount input
- Players with zero chips can keep watching

**Data & music**
- SQLite persistence for players, rooms and table state, restored after a server restart
- Showdown history and personal stats (win rate, winnings, hand history)
- Background music that follows the scene (lobby / table / tense moments), no audio files required

### 🚀 Quick Start

Requirements: Python 3.8+ (on Python 3.13, run `pip install "eventlet>=0.37"`) and a modern browser.

```bash
git clone https://github.com/JFRedist/texas-holdem-poker.git
cd texas-holdem-poker

python -m venv poker_env
# Windows
poker_env\Scripts\activate
# macOS / Linux
source poker_env/bin/activate

pip install -r requirements.txt
python app.py
```

Open <http://localhost:8888> and enter a nickname. The server prints a "📱 局域网访问" (LAN) address on startup — open it on any phone or computer on the same Wi-Fi.

> If other devices can't connect, check: (1) they are on the same Wi-Fi (guest / campus networks often isolate clients); (2) Windows Firewall allows Python inbound (tick "Public networks" on the first-run prompt, or set the network to Private); (3) if a VPN such as NordVPN is on, allow LAN access in its settings (NordVPN: turn off "Invisibility on LAN").

**Environment variables (optional)**

| Variable | Default | Description |
| --- | --- | --- |
| `POKER_HOST` | `0.0.0.0` | Bind address |
| `POKER_PORT` | `8888` | Port |
| `POKER_DEBUG` | `true` | Enable Flask debug mode |
| `POKER_ASYNC_MODE` | `eventlet` | Socket.IO async mode; use `threading` where eventlet can't be installed (e.g. an embedded Android server) |

### 🎮 Game Guide

**Actions**: Check, Call, Bet / Raise (drag the slider for quick sizing), Fold, All-in.

**Creating a room**: in the lobby, set the room name, mode (blinds / proportional betting), small and big blind, starting chips (500–10,000) and max players (2 / 4 / 6 / 9), and add bots right away.

**Bot levels**

| Level | Style |
| --- | --- |
| Beginner | Conservative, good for practice |
| Intermediate | Balanced |
| Advanced | Aggressive, bluffs often |
| God | Can see every player's hole cards |

**Music**: works out of the box — without audio files the game plays built-in music synthesized in the browser (lounge jazz in the lobby, walking bass at the table, a tense groove on your turn). To use your own tracks, put `lobby-music.mp3`, `table-music.mp3` and `action-music.mp3` in `static/audio/` (see the README there). If the browser blocks autoplay, music starts on your first click. Shortcuts: `M` play / pause, `Ctrl+H` show / hide the music panel.

### 📁 Project Structure

```
├── app.py                  # Flask app, HTTP API and Socket.IO events
├── poker_engine/           # Engine: cards, players, bots, hand evaluator, table flow
├── database.py             # Room and player data
├── db_adapter.py
├── player_persistence.py   # Player chip persistence
├── table_state_manager.py  # Table state save / restore
├── game_logger.py          # Hand and showdown logging
├── templates/              # Pages: home, lobby, table
└── static/                 # Frontend scripts (i18n, music player), styles and audio
```

### 🌐 Deployment

```bash
pip install gunicorn
gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:8888 app:app
```

Use a single worker (`-w 1`): game state lives in process memory. Example Nginx config with WebSocket support:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8888;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /socket.io/ {
        proxy_pass http://127.0.0.1:8888;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 🤝 Contributing

Issues and pull requests are welcome. Please use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:` / `fix:` / `docs:` …) and follow PEP 8 for Python code.

### 📄 License & Contact

- License: [MIT](LICENSE)
- Issues: [GitHub Issues](https://github.com/JFRedist/texas-holdem-poker/issues)
- Maintainer: [JFRedist](https://github.com/JFRedist) · Zi_Feng666@126.com
- Original author: [Jason He](https://github.com/stars1210JasonHe) · [upstream repository](https://github.com/stars1210JasonHe/texas-holdem-poker)

---

<div align="center">

如果这个项目对你有帮助，欢迎点个 ⭐ Star！ · If you find this project useful, a ⭐ is appreciated!

Made with ❤️ by [Jason He](https://github.com/stars1210JasonHe) · Maintained by [JFRedist](https://github.com/JFRedist)

</div>
