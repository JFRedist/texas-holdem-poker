# 更新日志 / Changelog

本文件记录 Fork 仓库 [JFRedist/texas-holdem-poker](https://github.com/JFRedist/texas-holdem-poker) 相对上游 [stars1210JasonHe/texas-holdem-poker](https://github.com/stars1210JasonHe/texas-holdem-poker) 的改动。

This file records the changes made in this fork relative to the upstream repository.

---

## 2026-10-01

### 修复 / Fixed
- **手牌进行中投票“下一轮”会清空底池**：只有本手牌结束后才接受下一轮投票，`start_next_round` 也会拒绝在手牌进行中重开。此前人机桌上唯一的真人随时投票就能让底池里的筹码消失。
- **再加注后的行动顺序**：下一位行动者改为从上一位行动者的下一位开始找。此前 4 人桌 UTG 加注、庄家跟注、小盲再加注后会轮到 UTG，大盲被跳过；翻牌后“下注、加注、再加注”同样乱序。
- **断线玩家仍被发牌**：`start_next_round` 不再把玩家状态写成字符串 `'playing'`，改由 `start_new_hand` 重置状态，断线玩家保持断线、不发牌。断线的真人也不再计入下一轮所需票数，避免整桌一直等他投票。
- 新增 `tests/test_next_round.py`，`tests/test_table_rules.py` 增加再加注行动顺序用例。

## 2026-09-30

### 修复 / Fixed
- **按真实德州扑克规则结算**：
  - 筹码输光的玩家转为观战，不再发牌、不交盲注，也不能再赢得底池（此前 0 筹码玩家照常参与并可能赢下整个底池）。
  - 新增主池 / 边池：每名玩家只能赢取自己投入所对应的部分，短码全下不再赢走深码的全部投入；超出所有对手承受范围、无人跟注的筹码退还本人。
  - 牌力相同时平分底池，零头按庄家左手第一位开始分配（此前由一人独得）。
  - 其他人全下后，剩下的玩家仍需对欠注做出跟注或弃牌（此前会被直接跳过）；无人能再下注时自动发完公共牌摊牌。
  - 最小下注为一个大盲，最小加注为「当前下注 + 上一次加注幅度」；不足额的全下加注不重新开放加注。
  - 单挑局翻牌后改为大盲先行动；庄家按座位轮换到下一位有筹码的玩家。
  - 机器人的加注金额不再可能把全桌当前下注改小。
- **机器人重复行动**：同一牌桌同时只允许一个机器人处理流程，避免两个任务替同一个机器人行动（曾导致已全下的机器人被判弃牌）；手牌结束消息不再重复发送。
- 结算提示显示每位赢家的实际赢得金额。

  **Real Texas Hold'em settlement**: busted players sit out; side pots, split pots with odd-chip rule and uncalled-bet returns; the last active player must still respond to an all-in; minimum bet/raise rules; heads-up post-flop order. Bot processing is now serialized per table.

### AI / Bots
- **比牌与胜率**：新增快速 7 张牌评估器（`poker_engine/equity.py`），完整比较点数与踢脚（此前只比牌型大类，一对 2 与一对 A 算平局）；高级机器人一次决策由约 2 秒降到约 0.05 秒。胜率计算接口改为真实模拟。
- **加注金额**：机器人统一按「加注到」的总额下注，不低于最小加注；机器人拿到真实位置、需跟注额、含全下者的对手数等信息（此前位置恒为 middle）。
- **德州扑克之神**：用看到的全部底牌（含已全下的对手，弃牌者的牌作死牌）精确计算胜率后决策，不再在同牌型时误判领先、不再扔掉胜率足够的听牌；日志不再打印他人底牌。
- **翻牌前评分**：改用真实胜率（此前 AKs 高于 AA、QJs 与 KK 同分）；中级改为「胜率比底池赔率决定跟注，牌力决定加注」。
- **高级机器人**：接通对手建模（入池率、翻牌前加注率、激进程度），面对下注按对手风格修正胜率；按位置开池；诈唬频率按下注尺度与对手弃牌倾向计算，不再把跟注全下当诈唬；筹码越深边缘跟注越谨慎。

  **Bots**: fast and correct hand evaluation, raise-to amounts and real position info, a Poker God that uses exact equity against the hands it sees, equity-based pre-flop ranking, and an advanced bot with working opponent modelling and sensible bluffing.

### 其他 / Chore
- 移除启动时和每小时对 `fix_database_issues.py` 的调用：该脚本已在上游删除，调用每次都失败并输出警告。

### 测试 / Tests
- 新增 `tests/test_table_rules.py`（规则场景 + 两千多手随机牌局的筹码守恒测试）、`tests/test_bot_games.py`（纯机器人对局）、`tests/test_equity.py`（评估器与胜率）、`tests/test_bot_strategy.py`（固定牌面决策），以及强度基准 `tests/bench_bot_strength.py`。

## 2026-09-29

### 新增 / Added
- **大厅可添加「德州扑克之神」**：创建房间时可直接添加能看到所有手牌的神级机器人（此前只能在牌桌内通过数字选择添加）。
  **Poker God bots in the lobby**: the create-room dialog can now add God-level bots.
- **内置合成音乐**：`static/audio/` 没有 mp3 时用 Web Audio API 实时生成大厅 / 牌桌 / 紧张三种背景音乐；自动播放被拦截时，首次点击页面即开始播放。
  **Built-in synthesized music**: plays when no mp3 files are present; starts on first click if autoplay is blocked.
- **运行模式可配置**：通过 `POKER_HOST` / `POKER_PORT` / `POKER_DEBUG` / `POKER_ASYNC_MODE` 环境变量设置监听地址、端口、debug 与异步模式；`threading` 模式不依赖 eventlet。
  **Configurable runtime**: host, port, debug and async mode via environment variables; `threading` mode works without eventlet.

### 变更 / Changed
- **牌型分析仅限人机练习**：牌桌上有 2 名及以上真人时，牌型分析面板关闭并显示提示；服务端胜率计算与记牌接口同样拒绝请求（此前胜率接口无任何权限校验）。
  **Hand analysis in bot practice only**: disabled with 2+ humans at the table, enforced server-side for the win-probability and card-tracking APIs as well.

### 修复 / Fixed
- **启动时打印的地址错误**：此前写死为上游作者的 `http://192.168.178.39:5000`；现在打印本机访问地址和自动检测到的局域网地址（排除 VPN 网段），并说明日志中的 `0.0.0.0` 不是访问地址。
  **Wrong startup address**: the hard-coded upstream address is replaced by the real localhost and detected LAN URLs.
- **音乐无法切换曲目**：`window.musicPlayer` 在播放器实例创建前就被赋值为 undefined，导致牌桌页所有切歌逻辑（轮到你行动、手牌结束、离开牌桌）从未生效。
  **Music never switched tracks**: `window.musicPlayer` was exported before the player existed.

### 文档 / Docs
- 重写 README（中英文对齐、补充项目结构与配置说明、修正与代码不符的内容），新增本 CHANGELOG。
  Rewrote the README and added this changelog.

## 2026-09-01

### 新增 / Added
- **中英文界面**：大厅右上角 🌐 按钮一键切换，主页 / 大厅 / 牌桌全局生效，语言偏好保存在 localStorage。
  **Bilingual UI**: one-click Chinese/English switch in the lobby, applied to home/lobby/table, preference saved in localStorage.

### 修复 / Fixed
- **游戏卡死**：补充处理阶段的机器人不再改变下注额（仅跟注补齐），避免已行动玩家突然欠注导致对局永久卡住；欠注时禁止过牌。
  **Game deadlock**: supplementary bot actions now only call to match instead of changing the bet; checking while owing chips is rejected.
- **机器人等级**：从数据库重建机器人时优先使用已保存的等级，昵称推断补全「至尊 / 无敌」等高级名字。
  **Bot level**: rebuilt bots use the stored level first; nickname fallback now recognises all advanced names.

## 2026-08-31

### 新增 / Added
- **牌型分析面板**：公共牌最佳牌型、我的当前牌型与单挑胜率、对手可能牌型分布（枚举全部组合）。
  **Hand analysis panel**: best board hand, your hand and heads-up equity, opponent hand distribution (full enumeration).
- **玩家信息增强**：每名玩家显示当前下注、本手累计投入，以及庄家 / 小盲 / 大盲徽章。
  **Player info**: current bet, total contribution this hand, and D / SB / BB badges.
- **房间解散**：创建者可在大厅一键解散房间，房间内玩家自动返回大厅。
  **Room dissolution**: the creator can dissolve a room; everyone is returned to the lobby.
- **投票状态恢复**：一局结束后刷新页面可恢复「开始下一轮」投票及自己的投票状态。
  **Vote recovery**: the "next round" vote survives a page refresh.
- **机器人思考节奏**：每个机器人决策间隔 1 秒并逐步广播行动。
  **Bot pacing**: each bot waits 1 s before acting, with per-step table updates.
- **下注金额滑块**：下注 / 加注输入框旁新增滑块，范围自动适配，与输入框双向联动。
  **Bet slider**: auto-ranged slider next to the bet/raise input, synced both ways.

### 修复 / Fixed
- **盲注轮换**：小盲 / 大盲随庄家轮换（单挑局庄家即小盲），行动顺序同步；修复第一局庄家与小盲重叠。
  **Blind rotation**: SB/BB follow the button (heads-up: dealer is SB) with matching action order.
- **徽章不显示**：修复庄家 / 小盲 / 大盲标记被重置或从未设置的问题。
  **Badges**: D / SB / BB flags are now set correctly.
- **断线重连**：断线后保留座位 30 秒；刷新 / 跳转页面不再被移出房间；满员房间的成员可直接重新进入。
  **Reconnect**: seats are kept for 30 s after a disconnect; members can re-enter full rooms.
- **服务器阻塞**：在启动时正确执行 `eventlet.monkey_patch()`，避免 `time.sleep` 阻塞所有连接。
  **Server blocking**: `eventlet.monkey_patch()` now runs before other imports.
- **音乐提示**：音乐文件缺失时静默运行，提示弹窗去重并支持「不再提示」。
  **Music prompt**: silent when audio files are missing; deduplicated prompt with "don't ask again".

### 其他 / Chore
- 将 `poker_env/` 虚拟环境、`node_modules/`、`test-results/` 移出版本控制。
  Removed the virtualenv, `node_modules/` and test artifacts from version control.
