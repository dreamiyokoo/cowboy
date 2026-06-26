from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from deps import get_current_user

router = APIRouter(prefix="/api/v1/predictions", tags=["predictions"])

RESULT_CLASSES = ["cowboy", "draw", "bull"]
WIN_ODDS = {"cowboy": 2.02, "draw": 22.0, "bull": 2.02}


@router.get("/accuracy")
async def get_prediction_accuracy(
    model_version: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """予測精度の集計を返す"""
    where_clauses = ["result != 'error'", "pred_result IS NOT NULL"]
    params: dict = {}
    if model_version:
        where_clauses.append("model_version = :model_version")
        params["model_version"] = model_version

    where = " AND ".join(where_clauses)

    rows = await db.execute(
        text(f"SELECT pred_result, result FROM games WHERE {where}"),
        params,
    )
    records = rows.fetchall()

    if not records:
        return {
            "total_predicted": 0,
            "accuracy": None,
            "by_predicted": {c: {"total": 0, "correct": 0, "accuracy": None} for c in RESULT_CLASSES},
            "confusion": {},
        }

    total = len(records)
    correct_total = sum(1 for r in records if r.pred_result == r.result)
    accuracy = round(correct_total / total, 4) if total > 0 else None

    by_predicted: dict = {c: {"total": 0, "correct": 0, "accuracy": None} for c in RESULT_CLASSES}
    confusion: dict = {}

    for r in records:
        pred = r.pred_result
        actual = r.result
        if pred in by_predicted:
            by_predicted[pred]["total"] += 1
            if pred == actual:
                by_predicted[pred]["correct"] += 1
        key = f"{pred}_pred_{actual}_actual"
        confusion[key] = confusion.get(key, 0) + 1

    for cls, data in by_predicted.items():
        if data["total"] > 0:
            data["accuracy"] = round(data["correct"] / data["total"], 4)

    return {
        "total_predicted": total,
        "accuracy": accuracy,
        "by_predicted": by_predicted,
        "confusion": confusion,
    }


@router.get("/roi")
async def get_prediction_roi(
    model_version: str | None = Query(default=None),
    confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """予測ROI・累計損益を返す（pred_result と result と bet が揃っているゲームのみ）"""
    where_clauses = [
        "result != 'error'",
        "pred_result IS NOT NULL",
        "(bet_cowboy IS NOT NULL OR bet_draw IS NOT NULL OR bet_bull IS NOT NULL)",
    ]
    params: dict = {}
    if model_version:
        where_clauses.append("model_version = :model_version")
        params["model_version"] = model_version

    where = " AND ".join(where_clauses)

    rows = await db.execute(
        text(f"""
            SELECT pred_result, result,
                   pred_cowboy, pred_draw, pred_bull,
                   bet_cowboy, bet_draw, bet_bull,
                   recorded_at
            FROM games WHERE {where}
            ORDER BY recorded_at ASC
        """),
        params,
    )
    records = rows.fetchall()

    if not records:
        return {
            "total": 0,
            "total_with_bets": 0,
            "overall_roi": None,
            "cumulative_pnl": [],
            "by_predicted": {c: {"total": 0, "correct": 0, "bet_total": 0, "payout": 0, "roi": None} for c in RESULT_CLASSES},
        }

    by_predicted: dict = {
        c: {"total": 0, "correct": 0, "bet_total": 0, "payout": 0, "roi": None}
        for c in RESULT_CLASSES
    }
    cumulative_pnl = []
    cum = 0
    total_bet = 0
    total_payout = 0

    for r in records:
        pred = r.pred_result
        actual = r.result

        # 信頼度フィルター
        if confidence > 0:
            prob = {"cowboy": r.pred_cowboy, "draw": r.pred_draw, "bull": r.pred_bull}.get(pred) or 0
            if prob < confidence:
                continue

        # ベット額（予測クラスに対応するベット）
        bet_map = {"cowboy": r.bet_cowboy, "draw": r.bet_draw, "bull": r.bet_bull}
        bet = bet_map.get(pred) or 0
        if bet <= 0:
            continue

        odds = WIN_ODDS.get(pred, 2.0)
        if actual == pred:
            payout = int(bet * odds)
            pnl = payout - bet
        else:
            payout = 0
            pnl = -bet

        cum += pnl
        total_bet += bet
        total_payout += payout

        if pred in by_predicted:
            by_predicted[pred]["total"] += 1
            by_predicted[pred]["bet_total"] += bet
            by_predicted[pred]["payout"] += payout
            if actual == pred:
                by_predicted[pred]["correct"] += 1

        cumulative_pnl.append({
            "recorded_at": r.recorded_at.isoformat() if hasattr(r.recorded_at, "isoformat") else str(r.recorded_at),
            "pnl": pnl,
            "cumulative": cum,
        })

    for cls, data in by_predicted.items():
        if data["bet_total"] > 0:
            data["roi"] = round((data["payout"] - data["bet_total"]) / data["bet_total"], 4)

    overall_roi = round((total_payout - total_bet) / total_bet, 4) if total_bet > 0 else None

    return {
        "total": len(records),
        "total_with_bets": len(cumulative_pnl),
        "overall_roi": overall_roi,
        "cumulative_pnl": cumulative_pnl,
        "by_predicted": by_predicted,
    }


@router.get("/streaks")
async def get_prediction_streaks(
    from_date: str | None = Query(default=None),
    to_date: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """連続予測ミストリークを返す（期間指定可）"""
    where_clauses = ["result != 'error'", "pred_result IS NOT NULL"]
    params: dict = {}
    JST = timezone(timedelta(hours=9))
    if from_date:
        dt_from = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=JST)
        where_clauses.append("recorded_at >= :from_date")
        params["from_date"] = dt_from
    if to_date:
        dt_to = datetime.strptime(to_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=JST)
        where_clauses.append("recorded_at <= :to_date")
        params["to_date"] = dt_to

    where = " AND ".join(where_clauses)

    rows = await db.execute(
        text(f"""
            SELECT pred_result, result, recorded_at
            FROM games WHERE {where}
            ORDER BY recorded_at ASC
        """),
        params,
    )
    records = rows.fetchall()

    if not records:
        return {
            "total": 0,
            "current_miss_streak": 0,
            "max_miss_streak": 0,
            "streak_history": [],
        }

    current_miss = 0
    max_miss = 0
    running = 0

    streak_history = []
    streak_start = None
    streak_len = 0

    for r in records:
        is_miss = (r.pred_result != r.result)

        if is_miss:
            running += 1
            max_miss = max(max_miss, running)
            if streak_len == 0:
                streak_start = r.recorded_at
            streak_len += 1
        else:
            if streak_len >= 5:
                streak_history.append({
                    "streak": streak_len,
                    "from": streak_start.isoformat() if hasattr(streak_start, "isoformat") else str(streak_start),
                    "to": r.recorded_at.isoformat() if hasattr(r.recorded_at, "isoformat") else str(r.recorded_at),
                })
            running = 0
            streak_len = 0
            streak_start = None

    # 最後まで続いている場合
    if streak_len >= 1:
        current_miss = running
        if streak_len >= 5:
            last = records[-1]
            streak_history.append({
                "streak": streak_len,
                "from": streak_start.isoformat() if hasattr(streak_start, "isoformat") else str(streak_start),
                "to": last.recorded_at.isoformat() if hasattr(last.recorded_at, "isoformat") else str(last.recorded_at),
            })
    else:
        current_miss = 0

    return {
        "total": len(records),
        "current_miss_streak": current_miss,
        "max_miss_streak": max_miss,
        "streak_history": streak_history[-20:],
    }
