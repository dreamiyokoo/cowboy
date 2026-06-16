from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from deps import get_current_user

router = APIRouter(prefix="/api/v1/predictions", tags=["predictions"])

RESULT_CLASSES = ["cowboy", "draw", "bull"]


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
