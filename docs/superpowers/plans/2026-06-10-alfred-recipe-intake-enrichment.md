# Alfred Recipe Intake Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When 小當家 saves an external recipe, present it in his teaching voice — inline tips beside each step, servings scaled to 2, preference-aware suggestions, and on-demand rich sections — while preserving the exact source recipe as a verbatim `📌 原始食譜` block.

**Architecture:** Prompt-only change. The mechanism already exists (base recipe-intake feature shipped earlier today): `save_recipe.py` takes the recipe body markdown on stdin and wraps it; chat mode already has `Read` access to `preferences.md`/`staples.md`/`lessons.md`. So the entire change is rewriting the "擷取到之後" portion of the 「料理擷取」 section in `prompts/chat.md` to specify the inline-hybrid card structure, the faithfulness invariant, scaling, suggestion sourcing, and the on-demand depth ladder. A small regression-guard test ensures the provenance block instruction can't be silently dropped by a future edit.

**Tech Stack:** Markdown prompt (`prompts/chat.md`), read fresh per chat invocation by `scripts/brain.py:build_prompt`. `pytest` for the guard test. Verification via real Discord use.

**Reference spec:** `docs/superpowers/specs/2026-06-10-alfred-recipe-intake-enrichment-design.md`

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `prompts/chat.md` | Replace the "擷取到之後" block of the 料理擷取 section with the enriched card spec (inline-hybrid, faithfulness, scaling, suggestions, on-demand sections). | Modify (lines 35–42) |
| `tests/test_brain.py` | Add a guard test asserting the enrichment + provenance instructions render into the chat prompt. | Modify (add one test) |

**No code files change.** `save_recipe.py` and `recipe_intake.py` are untouched — the card is just richer body markdown the brain composes.

**Note on taking effect:** `build_prompt` re-reads `prompts/chat.md` on every chat turn, so this change is live the moment it's committed — **no daemon restart needed** (unlike a `brain.py` change).

---

## Task 1: Rewrite the recipe-card instructions in `chat.md`

**Files:**
- Modify: `prompts/chat.md` (the "擷取到之後:" block, currently lines 35–42)
- Test: `tests/test_brain.py` (add one guard test)

- [ ] **Step 1: Write the failing guard test**

Append to `tests/test_brain.py`:

```python
def test_chat_prompt_has_recipe_enrichment():
    # The recipe-intake card must instruct: keep the verbatim source (📌 原始食譜),
    # scale servings, and offer 小當家's teaching sections. Guard against a future
    # chat.md edit silently dropping the enrichment + faithfulness block.
    p = brain.build_prompt("chat", history=[], messages=[])
    assert "原始食譜" in p          # the verbatim provenance block
    assert "2 人份" in p            # scale-to-household instruction
    assert "主廚秘訣" in p          # on-demand teaching section
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_brain.py::test_chat_prompt_has_recipe_enrichment -v`
Expected: FAIL — `assert "原始食譜" in p` (the current prompt has none of these strings).

- [ ] **Step 3: Replace the "擷取到之後:" block in `prompts/chat.md`**

Replace this exact block (the extraction-door list above it, points 1–6, stays unchanged):

```
擷取到之後:
- 整理成**忠於原作**的繁體中文食譜卡:標題、份量、食材(含份量)、步驟、時間。非中文來源就翻成繁中。
- 先讀 `state/preferences.md`;若食譜牴觸偏好(例如有豬肉但他們不吃),**點出來問他要不要換**,不要自己偷偷改掉。
- 用 write-seam 存檔(這是你唯一能寫食譜的方式):把食譜卡「標題以下」的內容(份量那行、**Ingredients:**、**Steps:**)從 stdin 餵進去:
  `... | uv run scripts/save_recipe.py --title "<繁中標題>" --slug "<英文-kebab-slug>" --source "<原始連結或來源>" --by "<是誰丟的>" --kind "<IG reel|YouTube|webpage|image|text>"`
  `--slug` 一定要給一個英文小寫連字號的代稱(例如 milk-mochi-dessert-soup),因為中文標題無法當檔名。
- 存完後熱情回覆:貼出食譜卡,並加一句像「存好了,排進下週候選 ✅ 不要就跟我說一聲」。若腳本回「already in cookbook」,就說這道之前存過了。
- 這條鏈不要動本週已鎖定的菜單 — 一律走「下週候選」(儀式會處理)。
```

with this enriched block (paste verbatim — note the `────────────` separator line and the emoji are intentional):

````
擷取到之後 — 用小當家的方式整理成食譜卡,但**原始食譜一字不改**:
- **鐵則**:重新編排、加心得可以,但食材與做法的實質內容不能動。卡片分上下兩區。
- **上半=你的版本**:原始做法當骨架,份量換算到 **2 人份**(並標明原本幾人份);你的提示用 🔥(秘訣)/⚠️(雷點)/💡(建議)標出來,**縮排在它對應的那一步底下**。提示要精準 — 只在「看到/聽到什麼才算對」「新手會在哪翻車」處加一兩句,別每行都評論。
- **下半=📌 原始食譜**:放在一條 `────────────` 分隔線之後,標題寫 `📌 原始食譜(來源原文,未改動 · 原N人份)`,接著來源的食材+步驟,**一字不改**(非中文就忠實翻成繁中,但食材/份量/步驟不變)。**永遠附上**。
- **份量**:換到 2 人份;換不乾淨的(1 顆蛋、一撮鹽、烘焙比例)就註明、別寫「0.5 顆蛋」。批量/常備菜維持原份量並註明。
- **進階區塊只在「夠複雜 + 屬於整道菜(非單一步驟)」時才開**,簡單兩三步的菜不要硬加空標題。可選:`【備料(開火前完成)】`、`⚠️ 新手最容易翻車`(挑 1-2 個最致命的)、`🔥 主廚秘訣`(跨步驟的訣竅)、`✅ 怎麼知道完成了`(熟度不明顯時)。同一個提示 inline 與區塊**擇一**,別重複。
- **建議來源**:給 💡 建議前先讀 `state/preferences.md`(口味/不吃的)、`state/staples.md`(他們已有什麼 → 替代)、`state/lessons.md`(這個廚房的特性);牴觸偏好(例:有香菜但女友不吃)就在 💡 點出來問要不要換 — 但 📌 原始食譜不動。建議只在真的有用時給,別硬湊。
- 用 write-seam 存檔(你唯一能寫食譜的方式):把「份量那行以下、一路到 📌 區塊」整段從 stdin 餵進去:
  `... | uv run scripts/save_recipe.py --title "<繁中標題>" --slug "<英文-kebab-slug>" --source "<原始連結或來源>" --by "<是誰丟的>" --kind "<IG reel|YouTube|webpage|image|text>"`
  `--slug` 給英文小寫連字號代稱(例 milk-mochi-dessert-soup),中文標題不能當檔名。`**Ingredients:**`、`**Steps:**` 標籤保留(與既有食譜檔一致)。
- 存完後熱情回覆:貼出食譜卡 +「存好了,排進下週候選 ✅ 不要就跟我說一聲」。腳本回「already in cookbook」就說這道之前存過了。本週鎖定的菜單不要動 — 一律走「下週候選」(儀式會處理)。
````

Leave everything else in `chat.md` unchanged (the heading, the doors 1–6, and the `## 規則` section below).

- [ ] **Step 4: Run the guard test + the full suite to verify they pass**

Run: `uv run pytest tests/test_brain.py -v`
Expected: PASS, including `test_chat_prompt_has_recipe_enrichment`.

Run: `uv run pytest -q`
Expected: all green (62 passed — the 61 prior + this one).

- [ ] **Step 5: Sanity-check the rendered prompt by eye**

Run:
```bash
uv run python -c "import sys; sys.path.insert(0,'scripts'); import brain; p=brain.build_prompt('chat',[],[]); i=p.index('擷取到之後'); print(p[i:i+1400])"
```
Expected: the enriched block prints, showing the 鐵則 / 上半 / 下半=📌 原始食譜 / 進階區塊 / 建議來源 / 存檔 bullets, with no leftover text from the old block.

- [ ] **Step 6: Commit**

```bash
git add prompts/chat.md tests/test_brain.py
git commit -m "feat(intake): enrich recipe cards — inline tips, scaled servings, on-demand teaching sections, verbatim 📌 original preserved"
```

---

## Task 2: Verify the enriched card through real Discord use

**Files:** none (manual verification, per the project's verify-via-real-use rule). No daemon restart required — `chat.md` is read fresh per chat turn.

Each step drops a recipe in #小當家的廚房 and inspects the reply + the saved `state/cookbook/<slug>.md`.

- [ ] **Step 1: Simple recipe → inline tips only, no padded sections**

Post a NEW simple recipe link/text (NOT the milk-mochi reel — it's already in the cookbook and `save_recipe.py` dedupes, so it won't re-save). A 2–3 step dish is ideal.
Expected: the card has `**Ingredients:**` + `**Steps:**` with 1–2 inline `🔥`/`⚠️` tips and maybe one `💡 建議`; **no** empty `【備料】`/`主廚秘訣`/`怎麼知道完成了` headers; a `📌 原始食譜` block at the bottom; servings scaled to 2 with the original count shown.

- [ ] **Step 2: Complex recipe → rich sections appear**

Post a complex recipe (a steak / braise / deep-fry / multi-component dish).
Expected: the card promotes whole-dish teaching into sections (some of `【備料】`, `⚠️ 新手最容易翻車`, `🔥 主廚秘訣`, `✅ 怎麼知道完成了`) on top of inline step cues — with no tip duplicated both inline and in a section. The `📌 原始食譜` block is still present and untouched.

- [ ] **Step 3: Recipe whose original servings ≠ 2 → scaling is correct**

Post a recipe that explicitly serves 4 (or 6).
Expected: the upper card's quantities are scaled to 2; the meta line shows the original count (e.g. `原4人份`); the `📌` block keeps the source's original quantities/servings unchanged. Awkward-to-halve items (e.g. 1 egg) are flagged, not written as "0.5".

- [ ] **Step 4: Recipe touching a known dislike → flagged, source unchanged**

Post a recipe featuring a known dislike (e.g. coriander/香菜, or celery — see `state/preferences.md`).
Expected: 小當家 raises it in `💡 建議` and offers a swap/ask, while the `📌 原始食譜` block still lists the original (e.g. coriander) unchanged.

- [ ] **Step 5: Confirm the faithfulness invariant held every time**

For each card saved above, open `state/cookbook/<slug>.md` and confirm the `📌 原始食譜` block matches the source's ingredients and method (quantities at original servings), and that all of 小當家's additions are clearly marked (`🔥`/`⚠️`/`💡`/section headers) — i.e. nothing in the source was silently altered.

- [ ] **Step 6: Commit the real-use cookbook entries**

```bash
git add state/cookbook/
git commit -m "ritual: recipe-intake enrichment real-use verification — enriched cards from real recipes"
```

(Reminder from prior ops lesson: smoke-tests of `save_recipe.py` append to the gitignored `state/inbox.md`; if you ran any CLI smoke-tests, hand-clean stray test cravings from `inbox.md` — `git checkout` can't, it's untracked.)

---

## Self-Review (completed during planning)

**Spec coverage:**
- Inline-hybrid layout (tips indented under each step) → Task 1 new block "上半=你的版本". ✅
- Verbatim original preserved as `📌 原始食譜` at original servings → Task 1 "下半=📌 原始食譜" + Task 2 step 5. ✅
- Scale to 2, show original servings → Task 1 "份量" bullet + Task 2 step 3. ✅
- Suggestions from preferences/staples/lessons, only when useful → Task 1 "建議來源" bullet. ✅
- On-demand rich sections, depth ladder, no duplication → Task 1 "進階區塊" bullet + Task 2 steps 1–2. ✅
- Faithfulness invariant (additions marked, method unchanged) → Task 1 "鐵則" + Task 2 step 5. ✅
- Non-Chinese source → translate body, keep 📌 faithful → Task 1 "下半" bullet. ✅
- Awkward scaling / batch recipes → Task 1 "份量" bullet + Task 2 step 3. ✅
- Prompt-only, no code change → File Structure table; no code tasks. ✅
- Structural labels `**Ingredients:**`/`**Steps:**` kept → Task 1 存檔 bullet. ✅

**Placeholder scan:** No TBD/TODO. The chat.md `<...>` are the existing CLI arg placeholders (unchanged from the shipped prompt); the `{N}` is literal prompt text instructing 小當家 to fill the original serving count. Every step has concrete content + expected output. ✅

**Type/name consistency:** The guard test asserts three substrings (`原始食譜`, `2 人份`, `主廚秘訣`) that all appear verbatim in the Task 1 new block. The replaced/old block text matches `prompts/chat.md:35–42` exactly. ✅
