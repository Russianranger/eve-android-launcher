# EVE fullscreen controls — 0.1.11

The top-right orbital gear opens an overlay. **Back to client** closes it;
**Launcher** returns to the launcher while the foreground service continues owning
the game. Android Back toggles the gear menu. System bars appear transiently when
swiped from the edge. The framebuffer remains aspect-fit, with no stretched image
or permanent toolbar. Text entry and Tab/Enter/Esc/right-click remain in the gear.

## Default controller scheme

Adapted from TRASC commit `b3bb19532eb53830af936d5e4ce95e848a46bce4`.
These are keyboard/mouse outputs, so their gameplay effect depends on EVE shortcuts.

| Control | Main layer output |
| --- | --- |
| Left stick | W / A / S / D |
| Right stick | Mouse cursor |
| A | F |
| X / Y / B | 1 / 2 / 3 |
| RB / LB | Left / right mouse button |
| LT | Next layer |
| RT | Tab |
| D-pad Up / Right / Down / Left | 4 / 5 / 6 / 7 |
| Select / Start | Escape / I |
| Left stick press / Right stick press | Home / C |

LT cycles **Main → Alt 1 → Alt 2 → Alt 3 → Main**. A short top-center
banner identifies the layer. Other layers inherit Main except these bindings:

| Layer | Overrides |
| --- | --- |
| Alt 1 | X/Y/B → 8/9/0; D-pad Up/Right → minus/equal |
| Alt 2 | X/Y/B/D-pad Up/Right/Down/Left → Alt + 1/2/3/4/5/6/7 |
| Alt 3 | X → Shift+B; Y → I; B → Escape; D-pad Up/Down → wheel up/down |

Existing profiles load the new names for the previously shipped default layers.
Custom names and all saved bindings remain intact; Save persists the displayed names.

Holding a mapped button holds its key or mouse button. Layer changes release old
outputs before applying held controls in the new layer. Menu, editor, text dialog,
focus loss, app pause and controller removal release held game inputs.

## Customize

Open **gear → Controller mappings**. Edit one to six named layers, every button
and stick direction, mouse clicks/wheel/cursor actions, keyboard keys and chords.
Layer actions include Next/Previous, direct selection and Hold. **Hold** temporarily
overrides the selected layer until released. **Inherit** uses Main's binding.

Adjust stick deadzone (0.05–0.80) and pointer speed (50–2500 framebuffer pixels/sec).
**Save** validates and persists the profile; **Cancel** keeps the previous profile.
**Restore Thor defaults in editor** changes only the draft until Save. Main cannot
be removed because it supplies inherited bindings. Removing a layer clears bindings
targeting it and renumbers later layer targets. Reopening the display starts on Main;
closing the gear preserves the current layer. A saved profile error is shown in the
editor and safe defaults remain available.

## Device qualification

1. Update in place with client/server stopped. Start the accepted server/client
   path with Adreno checked; open the display and use the current local account.
2. Confirm the toolbar/status bar no longer occupies game space and the gear is
   accessible. Open/close it, use Text and return to Launcher/reopen the display.
3. Move the right-stick cursor, click with RB/LB, and cycle LT through all four
   named layers. Confirm the banner, hotkey changes and return to Main.
4. Save one easily observed custom binding, reopen the display and confirm it
   persists. Edit it again and Cancel; confirm the saved binding is retained.
5. While holding a mouse button or mapped key, open the gear or switch apps.
   Return and confirm it is released. Check controller disconnect/reconnect if
   using an external pad. Check physical keyboard/touch alongside pad input.
6. Stop the client through Launcher, save/stop the server and export support.
   Report controls that fail, fullscreen/menu behavior and any stuck inputs.

Host tests cover layer/chord/hold transitions, invalid profile rejection, pointer
bounds and shared controller/keyboard/touch RFB input/release ordering. Android
33/35 tests cover decor initialization, packaged gear inflation, menu releases,
pause/recreation and saved profile migration; build/lint checks API integration.
They cannot accept physical Thor
controller event routing or visible gameplay; those require the test above.
