# RPG Engine (Django Tech Stack Baseline)

This directory contains a clean Django baseline for the text-driven RPG project.

## 1) Setup

```bash
cd rpg_engine
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 2) Configure

Edit `.env`:
- `OPENAI_API_KEY`
- `DATABASE_URL` (RDS Postgres in production)
- `MONGODB_URI` (MongoDB Atlas)

## 3) Run

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py runserver 0.0.0.0:8010
```

## 4) Verify

Open:
- `http://127.0.0.1:8010/api/health/`

It checks:
- Django DB connection
- OpenAI model connectivity
- MongoDB connectivity

If `OPENAI_API_KEY` or `MONGODB_URI` is missing, health returns `degraded` with details.

## 5) MVP Endpoints (Step 2)

Upload a book:

```bash
curl -X POST http://127.0.0.1:8010/api/books/upload/ \
  -H "Content-Type: application/json" \
  -d '{"title":"demo-book","content":"Your source text here"}'
```

Generate world from book:

```bash
curl -X POST http://127.0.0.1:8010/api/worlds/generate/ \
  -H "Content-Type: application/json" \
  -d '{"book_id":1}'
```

Create character:

```bash
curl -X POST http://127.0.0.1:8010/api/characters/create/ \
  -H "Content-Type: application/json" \
  -d '{"world":1,"name":"Kai","role":"Ranger"}'
```

Start session:

```bash
curl -X POST http://127.0.0.1:8010/api/sessions/start/ \
  -H "Content-Type: application/json" \
  -d '{"world_id":1,"character_id":1,"title":"Demo Adventure"}'
```

Interact with session:

```bash
curl -X POST http://127.0.0.1:8010/api/sessions/1/interact/ \
  -H "Content-Type: application/json" \
  -d '{"user_input":"I enter the ruin hall and inspect the walls.","expected_version":1}'
```

If concurrent requests conflict, API returns `409` with `current_version`.
Client should refresh latest session state and retry with the new `expected_version`.

## 6) Economy / Trading MVP (Singleton + Strategy)

Quote with strategy:

```bash
curl -X POST http://127.0.0.1:8010/api/trades/quote/ \
  -H "Content-Type: application/json" \
  -d '{"character_id":1,"item_name":"Moon Shard","quantity":2,"base_price":"12.50","strategy":"negotiation"}'
```

Execute trade:

```bash
curl -X POST http://127.0.0.1:8010/api/trades/execute/ \
  -H "Content-Type: application/json" \
  -d '{"session_id":1,"character_id":1,"item_name":"Moon Shard","quantity":2,"base_price":"12.50","strategy":"negotiation"}'
```

Strategies:
- `fixed`
- `negotiation`
- `barter`

## 7) Rule Layer + AI Trading

Bootstrap market from world/book:

```bash
curl -X POST http://127.0.0.1:8010/api/market/bootstrap/ \
  -H "Content-Type: application/json" \
  -d '{"world_id":2,"book_id":4,"reset_existing":true}'
```

AI trade action (natural language buy/sell):

```bash
curl -X POST http://127.0.0.1:8010/api/trades/ai-act/ \
  -H "Content-Type: application/json" \
  -d '{"session_id":1,"merchant_id":1,"user_input":"buy 1 traveler ration with negotiation"}'
```

If AI parsing is unavailable, a rule fallback parser will still execute trading.
