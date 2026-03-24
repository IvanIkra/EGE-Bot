import json
import secrets
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import ADMIN_LOGIN, ADMIN_PASSWORD, DATABASE_URL
from db.models import Answer, Base, Progress, User, Word
from db.models import QuestionType

app = FastAPI(title="EGE Bot Admin")

security = HTTPBasic()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# ── DB setup ──────────────────────────────────────────────────────────────────

engine = create_async_engine(DATABASE_URL, echo=False)
session_factory: async_sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@app.on_event("startup")
async def startup() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    async with session_factory() as session:
        yield session


# ── Auth ──────────────────────────────────────────────────────────────────────

def require_auth(credentials: Annotated[HTTPBasicCredentials, Depends(security)]) -> str:
    ok_user = secrets.compare_digest(credentials.username.encode(), ADMIN_LOGIN.encode())
    ok_pass = secrets.compare_digest(credentials.password.encode(), ADMIN_PASSWORD.encode())
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
async def admin_index(
    request: Request,
    _: str = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    today = date.today()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    total_users = await session.scalar(select(func.count(User.id))) or 0
    active_7 = await session.scalar(
        select(func.count(func.distinct(Answer.user_id))).where(Answer.ts >= datetime.combine(week_ago, datetime.min.time()))
    ) or 0
    active_30 = await session.scalar(
        select(func.count(func.distinct(Answer.user_id))).where(Answer.ts >= datetime.combine(month_ago, datetime.min.time()))
    ) or 0

    today_start = datetime.combine(today, datetime.min.time())
    answers_today = await session.scalar(
        select(func.count(Answer.id)).where(Answer.ts >= today_start)
    ) or 0

    # Words with most errors
    from sqlalchemy import cast, Integer as SAInt, case
    rows = await session.execute(
        select(
            Word.id, Word.display, Word.task_number,
            func.count(Answer.id).label("total"),
            func.sum(case((Answer.is_correct == False, 1), else_=0)).label("errors"),
        )
        .join(Answer, Answer.word_id == Word.id)
        .group_by(Word.id, Word.display, Word.task_number)
        .order_by(func.sum(case((Answer.is_correct == False, 1), else_=0)).desc())
        .limit(10)
    )
    hard_words = [
        {
            "id": r.id,
            "display": r.display,
            "task_number": r.task_number,
            "total": r.total,
            "errors": int(r.errors or 0),
            "error_pct": round(int(r.errors or 0) / r.total * 100, 1) if r.total else 0,
        }
        for r in rows.all()
    ]

    # Accuracy by task number
    task_rows = await session.execute(
        select(
            Word.task_number,
            func.count(Answer.id).label("total"),
            func.sum(case((Answer.is_correct == True, 1), else_=0)).label("correct"),
        )
        .join(Answer, Answer.word_id == Word.id)
        .group_by(Word.task_number)
        .order_by(Word.task_number)
    )
    task_stats = [
        {
            "task_number": r.task_number,
            "total": r.total,
            "correct": int(r.correct or 0),
            "pct": round(int(r.correct or 0) / r.total * 100, 1) if r.total else 0,
        }
        for r in task_rows.all()
    ]

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "total_users": total_users,
            "active_7": active_7,
            "active_30": active_30,
            "answers_today": answers_today,
            "hard_words": hard_words,
            "task_stats": task_stats,
        },
    )


# ── Words list ────────────────────────────────────────────────────────────────

@app.get("/admin/words", response_class=HTMLResponse)
async def admin_words(
    request: Request,
    task: Optional[int] = None,
    _: str = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    q = select(Word).order_by(Word.task_number, Word.id)
    if task is not None:
        q = q.where(Word.task_number == task)
    result = await session.execute(q)
    words = result.scalars().all()

    task_numbers_result = await session.execute(
        select(Word.task_number).distinct().order_by(Word.task_number)
    )
    task_numbers = [r[0] for r in task_numbers_result.all()]

    return templates.TemplateResponse(
        "words.html",
        {"request": request, "words": words, "task_numbers": task_numbers, "selected_task": task},
    )


# ── Add word ──────────────────────────────────────────────────────────────────

@app.post("/admin/words/add")
async def admin_add_word(
    display: str = Form(...),
    answer: str = Form(...),
    options: str = Form(""),
    question_type: str = Form(...),
    rule: str = Form(...),
    task_number: int = Form(...),
    _: str = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    opts = [o.strip() for o in options.split(",") if o.strip()] if options else None
    word = Word(
        display=display,
        answer=answer,
        options=opts or None,
        question_type=QuestionType(question_type),
        rule=rule,
        task_number=task_number,
    )
    session.add(word)
    await session.commit()
    return RedirectResponse("/admin/words", status_code=303)


# ── Edit word ─────────────────────────────────────────────────────────────────

@app.get("/admin/words/{word_id}/edit", response_class=HTMLResponse)
async def admin_edit_word_form(
    request: Request,
    word_id: int,
    _: str = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Word).where(Word.id == word_id))
    word = result.scalar_one_or_none()
    if not word:
        raise HTTPException(404, "Word not found")
    return templates.TemplateResponse("word_edit.html", {"request": request, "word": word})


@app.post("/admin/words/{word_id}/edit")
async def admin_edit_word(
    word_id: int,
    display: str = Form(...),
    answer: str = Form(...),
    options: str = Form(""),
    question_type: str = Form(...),
    rule: str = Form(...),
    task_number: int = Form(...),
    _: str = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Word).where(Word.id == word_id))
    word = result.scalar_one_or_none()
    if not word:
        raise HTTPException(404, "Word not found")

    opts = [o.strip() for o in options.split(",") if o.strip()] if options else None
    word.display = display
    word.answer = answer
    word.options = opts or None
    word.question_type = QuestionType(question_type)
    word.rule = rule
    word.task_number = task_number
    await session.commit()
    return RedirectResponse("/admin/words", status_code=303)


# ── Deactivate word ───────────────────────────────────────────────────────────

@app.post("/admin/words/{word_id}/toggle")
async def admin_toggle_word(
    word_id: int,
    _: str = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Word).where(Word.id == word_id))
    word = result.scalar_one_or_none()
    if not word:
        raise HTTPException(404, "Word not found")
    word.is_active = not word.is_active
    await session.commit()
    return RedirectResponse("/admin/words", status_code=303)


# ── Upload JSON ───────────────────────────────────────────────────────────────

@app.post("/admin/words/upload", response_class=HTMLResponse)
async def admin_upload_words(
    request: Request,
    file: UploadFile,
    _: str = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
):
    errors: list[str] = []
    added = 0

    try:
        content = await file.read()
        data = json.loads(content)
    except Exception as exc:
        errors.append(f"Ошибка чтения файла: {exc}")
        return templates.TemplateResponse("upload_result.html", {"request": request, "errors": errors, "added": 0})

    if not isinstance(data, list):
        errors.append("JSON должен быть массивом объектов.")
        return templates.TemplateResponse("upload_result.html", {"request": request, "errors": errors, "added": 0})

    required_fields = {"display", "answer", "question_type", "rule", "task_number"}
    for idx, item in enumerate(data):
        missing = required_fields - set(item.keys())
        if missing:
            errors.append(f"Запись {idx}: отсутствуют поля {missing}")
            continue
        try:
            qt = QuestionType(item["question_type"])
        except ValueError:
            errors.append(f"Запись {idx}: недопустимый question_type '{item['question_type']}'")
            continue

        word = Word(
            display=item["display"],
            answer=item["answer"],
            options=item.get("options"),
            question_type=qt,
            rule=item["rule"],
            task_number=int(item["task_number"]),
        )
        session.add(word)
        added += 1

    if added:
        await session.commit()

    return templates.TemplateResponse(
        "upload_result.html", {"request": request, "errors": errors, "added": added}
    )
