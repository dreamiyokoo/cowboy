from statistics import mean, median, quantiles

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from deps import get_current_user

router = APIRouter(prefix="/api/v1/games", tags=["games"])

# ラベル・オッズ・バケット幅の定義
_BASE = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

CATEGORY_META = {
    "cowboy":    {"label": "カウボーイ",   "odds": 2.02,  "breaks": _BASE + [12, 15, 20]},
    "bull":      {"label": "ブル",         "odds": 2.02,  "breaks": _BASE + [12, 15, 20]},
    "draw":      {"label": "抽選",         "odds": 22.0,  "breaks": _BASE + [15, 20, 30, 40, 60, 80]},
    "any_flash": {"label": "FL/CN W",      "odds": 1.67,  "breaks": _BASE + [12, 15, 20]},
    "any_pair":  {"label": "1ペア W",      "odds": 8.5,   "breaks": _BASE + [15, 20, 30, 50]},
    "any_ace":   {"label": "Aペア W",      "odds": 100.0, "breaks": _BASE + [20, 50, 100, 200, 300]},
    "win_high":  {"label": "ハイ/1P W",    "odds": 2.2,   "breaks": _BASE + [12, 15, 20]},
    "win_two":   {"label": "2ペア W",      "odds": 3.1,   "breaks": _BASE + [15, 20, 30]},
    "win_sf":    {"label": "3K/ST/FL W",   "odds": 4.7,   "breaks": _BASE + [15, 20, 30, 50]},
    "win_fh":    {"label": "FH W",         "odds": 20.5,  "breaks": _BASE + [20, 35, 50, 80, 120]},
    "win_four":  {"label": "4K+ W",        "odds": 250.0, "breaks": _BASE + [50, 150, 300, 500]},
}


def _make_histogram(intervals: list[int], breaks: list[int]) -> list[dict]:
    """breaks の各値を上限とするバケットにインターバルを集計する"""
    buckets = []
    prev = 0
    for b in breaks:
        label = str(b) if prev + 1 == b else f"{prev+1}-{b}"
        count = sum(1 for v in intervals if prev < v <= b)
        buckets.append({"label": label, "from": prev + 1, "to": b, "count": count})
        prev = b
    # 最終バケット（breaks[-1]+以上）
    rest = sum(1 for v in intervals if v > breaks[-1])
    if rest > 0 or True:
        buckets.append({"label": f"{breaks[-1]+1}+", "from": breaks[-1] + 1, "to": None, "count": rest})
    return buckets


def _compute_stats(positions: list[int], total: int, breaks: list[int]) -> dict:
    count = len(positions)
    if count == 0:
        return {
            "count": 0, "mean_interval": None, "median_interval": None,
            "p75_interval": None, "max_interval": None, "current_gap": total,
            "histogram": _make_histogram([], breaks),
        }

    intervals = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]
    current_gap = total - positions[-1]  # 直近出現から現在までのゲーム数

    return {
        "count": count,
        "mean_interval": round(mean(intervals), 1) if intervals else None,
        "median_interval": int(median(intervals)) if intervals else None,
        "p75_interval": int(quantiles(intervals, n=4)[2]) if len(intervals) >= 4 else None,
        "max_interval": max(intervals) if intervals else None,
        "current_gap": current_gap,
        "histogram": _make_histogram(intervals, breaks),
    }


@router.get("/intervals")
async def get_game_intervals(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """各結果・WIN種別の出現インターバル統計を返す"""
    rows = await db.execute(text("""
        SELECT result,
               win_any_flash, win_any_pair, win_any_ace,
               win_high, win_two, win_sf, win_fh, win_four
        FROM games
        WHERE result != 'error'
        ORDER BY recorded_at ASC
    """))
    games = rows.fetchall()
    total = len(games)

    # カテゴリごとに出現インデックス（1始まり）を収集
    positions: dict[str, list[int]] = {k: [] for k in CATEGORY_META}
    for i, g in enumerate(games, start=1):
        if g.result == "cowboy":
            positions["cowboy"].append(i)
        elif g.result == "bull":
            positions["bull"].append(i)
        elif g.result == "draw":
            positions["draw"].append(i)
        if g.win_any_flash:
            positions["any_flash"].append(i)
        if g.win_any_pair:
            positions["any_pair"].append(i)
        if g.win_any_ace:
            positions["any_ace"].append(i)
        if g.win_high:
            positions["win_high"].append(i)
        if g.win_two:
            positions["win_two"].append(i)
        if g.win_sf:
            positions["win_sf"].append(i)
        if g.win_fh:
            positions["win_fh"].append(i)
        if g.win_four:
            positions["win_four"].append(i)

    categories = {}
    for key, meta in CATEGORY_META.items():
        stats = _compute_stats(positions[key], total, meta["breaks"])
        categories[key] = {
            "label": meta["label"],
            "odds": meta["odds"],
            **stats,
        }

    return {"total_games": total, "categories": categories}
