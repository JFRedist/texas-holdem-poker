# 方案 2：深色竞技牌桌

Result: passed for the checked local flows and responsive layouts.

## Reference and implementation
- [Selected direction](reference.png)
- [Actual desktop, 1440 × 1024](desktop.png)
- [Actual mobile, 390px viewport](mobile.png)

The reference supplies the dark navy palette, blue oval table, navigation rail, analysis sidebar, and separate action dock. The implementation retains the existing product's controls, statistics, game events, and terminology. It adapts the concept to 2–9 seats and stacks cards/actions before seats on narrow screens.

## Review and fixes
- Unified login, lobby, dialogs and table styling without replacing Flask or the existing client event handlers.
- Removed a delayed demo-player rendering callback that overwrote real seats.
- Kept the current player's seat at the bottom without changing the game array order. Names are escaped before interpolation.
- Moved the hero cards upward after screenshot review to avoid covering the player name.
- Music defaults to the bottom-right; saved positions remain respected. Explicit opposite-edge auto values prevent a bottom panel stretching from the original CSS top anchor. Responsive selectors now match active edges.
- Desktop screenshot review: hand, six seats, pot, current-turn outline, sidebar and action dock are visible and separated.
- Mobile review: cards and actions come first; seats use a two-column list. No horizontal overflow at checked 320, 390, 768 and 1024 widths.

## Checks
- Browser flow: login → lobby → create six-player room → start → call → flop → input/slider synchronization → bet → settlement → next-hand vote → next hand.
- Final desktop flow: a new six-player room starts and reaches the human's turn with all four legal action controls visible.
- Music panel final browser bounds: 346 × 53px at the bottom-right, rather than a stretched overlay.
- Browser console check during the earlier full flow: no errors.
- Template rendering, preserved original IDs, balanced markup and inline JavaScript syntax checks passed.
- Node regression checks: 2–9 seat placement, hero highlight, nickname escaping, immutable player order; both music controls at all four positions.
- Existing poker rule tests passed, including 2173 randomized hands, side pots, ties and chip conservation. The game engine is unchanged.

## Limits
No physical mobile device, Safari or simultaneous multi-human session was tested. Nine-seat placement has an automated check; the final nine-seat screenshot was not used as acceptance evidence. No new game features or dependencies were added.
