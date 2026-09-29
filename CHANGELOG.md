# 更新日志 / Changelog

本文件记录 Fork 仓库 [ZiFeng666/texas-holdem-poker](https://github.com/ZiFeng666/texas-holdem-poker) 相对上游 [stars1210JasonHe/texas-holdem-poker](https://github.com/stars1210JasonHe/texas-holdem-poker) 的改动。

This file records the changes made in this fork relative to the upstream repository.

---

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
