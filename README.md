# EGE Bot - Telegram Bot for Russian EGE Exam Practice

A Telegram bot for adaptive spelling practice based on Russian EGE tasks (9-15).  
The SM-2 algorithm decides which word to show next: the more mistakes you make, the more often the word appears.

## Tech Stack

- **aiogram 3** - Telegram bot framework (async, FSM)
- **PostgreSQL** - primary database
- **Redis** - FSM state storage
- **SQLAlchemy** - ORM
- **FastAPI + Jinja2** - admin panel
- **APScheduler** - daily reminders

## Project Structure

```
├── main.py              # bot entry point
├── config.py            # environment variables
├── db/
│   ├── models.py        # tables: users, words, progress, answers, explanations
│   └── queries.py       # database queries
├── services/
│   └── sm2.py           # SM-2 algorithm
├── handlers/
│   ├── practice.py      # practice FSM
│   └── stats.py         # progress and leaderboard
├── admin/
│   ├── main.py          # FastAPI admin panel
│   └── templates/       # Jinja2 templates
├── data/
│   └── words.json       # initial words dataset
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## Run

### 1. Clone the repository

```bash
git clone https://github.com/ivanikra/ege-bot
```

### 2. Create `.env`

```bash
cp .env.example .env
```

Fill in:

```env
BOT_TOKEN=your_botfather_token
DATABASE_URL=postgresql+asyncpg://user:supersecret123pass@db:5432/ege_bot
REDIS_URL=redis://redis:6379/0
ADMIN_LOGIN=admin
ADMIN_PASSWORD=your_password
ADMIN_PORT=5001
```

> `user` and `supersecret123pass` must match `POSTGRES_USER` and `POSTGRES_PASSWORD` in `docker-compose.yml`.

### 3. Start services

```bash
docker compose up -d
```

On first startup, tables are created automatically and words are loaded from `data/words.json`.

### Useful commands

```bash
docker compose logs -f bot       # bot logs
docker compose restart bot       # restart bot
docker compose up -d --build bot # rebuild and restart bot
docker compose down              # stop (data is preserved)
docker compose down -v           # stop and remove database volumes
```

## Admin Panel

Open: `http://<ip>:<ADMIN_PORT>/admin`  
Example with default settings: `http://localhost:5001/admin`

Use credentials from `.env` (`ADMIN_LOGIN` / `ADMIN_PASSWORD`).

**Features:**
- Add, edit, and hide words
- Upload words from a JSON file
- User statistics (total, active in last 7/30 days, answers today)
- Most difficult words and accuracy by task number

## `words.json` Format

```json
[
  {
    "task_number": 9,
    "question_type": "input",
    "display": "пр_стой",
    "answer": "о",
    "rule": "Prefix PRO- (meaning: through, past)"
  },
  {
    "task_number": 15,
    "question_type": "choice",
    "display": "некоше_ый луг",
    "answer": "Н",
    "options": ["Н", "НН"],
    "rule": "Verbal adjective without a prefix uses one Н"
  }
]
```

| Field | Required | Description |
|---|---|---|
| `task_number` | yes | Task number (9-15) |
| `question_type` | yes | `input` for typed answers, `choice` for buttons |
| `display` | yes | Word with a missing part (`_`) |
| `answer` | yes | Correct answer |
| `options` | only for `choice` | Answer options |
| `rule` | yes | Rule shown after a wrong answer |
