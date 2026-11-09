# AI RPG Immersive World

Turn any novel into a playable text adventure. Drop a `.txt` book in, the engine reads it
chapter by chapter, builds a story bible (characters, plot beats, world facts), and then lets
you step into the book as a new character while Claude narrates in the author's voice.

Built with Django + Django REST Framework, Postgres (game state), MongoDB Atlas (chapter
summaries, story bible, dialogue history) and the Claude API. Deployed on Google Cloud Run.

## 怎么玩 / How to play

**线上版本**：打开部署好的网址（见下方 Deploy），不用安装任何东西。

1. **选一本书**，填角色名和职业，点 **读取章节**。第一次读一本书要几分钟（逐章摘要、整理人物志），之后所有人共享结果，秒开。
2. **选从哪一章开始**。每章下面有摘要帮你定位，从第一章开始体验最完整。
3. **开始冒险**。旁白会把你放进这一章的场景里。在输入框里用自然语言说你要做什么：说话、行动、观察、离开都行。Enter 发送，Shift+Enter 换行。
4. 输入框下方的 **当前：…** 是剧情引导，告诉你大家正在尝试做什么，不剧透结局，会随剧情变化。
5. 书里的角色会按原著的性格和说话方式回应你。你可以顺着剧情走，也可以做原著里没发生的事，旁白会接住。生命值归零游戏结束，点 **新游戏** 重来。

每个人开始游戏都会得到独立的存档，对话互不干扰；同一本书的世界、NPC 和市场是共享的。

**English:** pick a book, name your character, click **读取章节** (read chapters) and wait
for the first-time scan. Choose a starting chapter, then type what you want to do in plain
language. The hint under the input box (当前：…) tells you what the group is currently trying
to do without spoiling the ending. Characters answer in their own voice from the book.

## Run locally

Requirements: Python 3.12, an Anthropic API key. MongoDB is optional (falls back to memory).

```bash
cd rpg_engine
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill in ANTHROPIC_API_KEY (and MONGODB_URI if you have Atlas)
python manage.py migrate
python manage.py runserver
```

Open http://127.0.0.1:8000/ for the web game, or http://127.0.0.1:8000/api/health/ to check
that the database, LLM and MongoDB connections are fine.

Books are read from `rpg_engine/samples/` (override with `BOOKS_DIR`). The repo ships
public-domain samples (*King Solomon's Mines*, a short original story). Put your own `.txt`
there; Chinese (`第N章`) and English (`CHAPTER N`) headings are both detected.

Key settings in `.env`:

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | Narrator and summariser (default `claude-sonnet-5-5`) |
| `MONGODB_URI`, `MONGODB_DB_NAME` | Chapter summaries, story bible, dialogue history. Empty = in-memory |
| `DATABASE_URL` | Game state. Default SQLite; Postgres in production |
| `RPG_OUTPUT_LANGUAGE` | Language the narrator writes in, e.g. `Chinese` |
| `CHAPTER_GROUP_CHARS` | Merge short chapters into ~N-character units before summarising |
| `NARRATOR_STYLE_FILE` | Prose rules the narrator follows; defaults to `prompts/narrator_style.md` |

### Tuning the narrator's prose

`rpg_engine/prompts/narrator_style.md` is injected into every turn's prompt and re-read
whenever the file changes, so you can edit the writing rules while the server runs.

### Terminal play (no browser)

```bash
python manage.py play --book samples/the_lantern_of_saltmere.txt --name Kai --role Ranger
```

Add `--offline` (automatic without an API key) for a deterministic narrator that understands
`look`, `go to <place>`, `rest`, `talk`, `fight`, `finish`.

## How a book becomes a world

1. **Split** (`game/services/chapters.py`): the text is cut on chapter headings, or into
   fixed-size chunks, and stored in MongoDB as `pending` chapters.
2. **Summarise** (`POST /api/play/prepare/`): pending chapters are summarised in concurrent
   batches into a fixed JSON schema: summary, characters with verbatim quotes and reactions,
   locations, items, typed events, world facts, hooks. The web UI polls until `ready`, so no
   request outlives Cloud Run's timeout. Failed chapters retry up to 3 times.
3. **Story bible** (`game/services/bible.py`): per-chapter evidence is merged in code (alias
   union, dedup, ordering) into one record per character, a plot timeline and a fact list.
   Major characters then get a single overall profile (personality, speech style, closed-vocabulary
   style tags, behaviour rules) generated once from the evidence, not per chapter.
4. **World** (`game/services/world_builder.py`): locations, NPCs seeded from the bible's major
   characters, and a market.
5. **Play** (`game/services/story_service.py`): each turn's prompt = digest of the current
   chapter and its neighbours + bible sheets for the characters present + last 8 turns + state
   snapshot + current objective. The narrator returns `{narrative, events, objective}`;
   events are whitelisted and applied to game state inside a transaction.

Storage split: relational game state (worlds, NPCs, characters, inventory, sessions, trades)
in Postgres; semi-structured AI output (chapters, bible, history) in MongoDB keyed by
`source:title` so local and cloud environments share the same scans.

## Architecture

| Pattern | Where | Role |
|---|---|---|
| Template Method / Strategy | `game/services/llm_service.py` | `LLMService` owns prompts and parsing; `ClaudeService` / `OpenAIService` implement `_complete()` |
| Factory Method | `game/services/factories.py` | `LocationFactory`, `NPCFactory`, `ItemFactory`, `EncounterFactory` via `ComponentFactoryRegistry` |
| Observer | `game/services/events.py` | `GameStateBus` publishes `GameEvent`s to character, inventory, quest, spawn and Mongo observers |
| Singleton + Strategy | `game/services/trade_service.py` | `CurrencyManager`; `FixedPrice` / `Negotiation` / `Barter` pricing |

Tests:

```bash
cd rpg_engine && python -m pytest -q
```

Tests never touch real services: MongoDB falls back to memory and the LLM is replaced by a
deterministic `OfflineNarrator`.

## Management commands

```bash
python manage.py chapters_export "<book title>" --out backups/book.json   # back up summaries + bible
python manage.py chapters_import backups/book.json                        # restore without paying again
python manage.py chapters_reset "<book title>"                            # re-scan from scratch
python manage.py bible_show "<book title>" [--character 名字 | --plot | --facts]
python manage.py world_reset "<book title>"                               # rebuild world/NPCs next start
```

## Deploy (Google Cloud Run)

The `rpg_engine/Dockerfile` runs migrations then gunicorn. Secrets live in Secret Manager,
never in the image or the repo (`.env` is git-ignored and excluded by `.gcloudignore`).

```bash
cd rpg_engine
gcloud run deploy rpg-engine --source . --region us-east1 \
  --update-secrets DJANGO_SECRET_KEY=django-secret-key:latest,ANTHROPIC_API_KEY=anthropic-api-key:latest,DATABASE_URL=database-url:latest,MONGODB_URI=mongodb-uri:latest \
  --update-env-vars RPG_OUTPUT_LANGUAGE=Chinese,CHAPTER_GROUP_CHARS=12000 \
  --add-cloudsql-instances <project>:us-east1:rpg-db \
  --allow-unauthenticated
```

Run a management command in the cloud with a Cloud Run job that uses the same image, e.g.
`gcloud run jobs execute rpg-manage --args world_reset,"<book title>"`.

Local full stack with Docker: `cd rpg_engine && docker compose up --build`.

## API

All endpoints are under `/api/`. The web UI uses `books/local/`, `play/prepare/`,
`play/chapters/`, `play/start/`, `sessions/<id>/` and `sessions/<id>/interact/`.
Programmatic use also has `books/upload/`, `books/<id>/process/`, `worlds/generate/`,
`worlds/<id>/components/generate/`, `characters/create/`, `sessions/start/`,
`market/bootstrap/`, `trades/quote/`, `trades/execute/`, `trades/ai-act/`.

```bash
curl -X POST http://127.0.0.1:8000/api/sessions/1/interact/ \
  -H "Content-Type: application/json" \
  -d '{"user_input":"我走到齐夏旁边坐下。","expected_version":1}'
```

The response carries `ai_output`, applied `events`, `notes`, `objective`, a full `state`
snapshot and `session_status`. A version conflict returns `409` with `current_version`.
