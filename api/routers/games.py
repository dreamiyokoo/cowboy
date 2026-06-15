from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, status, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from deps import get_current_user

router = APIRouter(prefix="/api/v1/games", tags=["games"])

VALID_RESULTS = {"cowboy", "draw", "bull", "error"}
VALID_HAND_TYPES = {1, 2, 3}
DUPLICATE_GUARD_SECONDS = 60
MAX_LIMIT = 1000


class GamePostRequest(BaseModel):
    open_card: str | None = None
    result: Literal["cowboy", "draw", "bull", "error"]
    cowboy_hand: int | None = None
    bull_hand: int | None = None
    round_number: int | None = None

    jackpot_stock: int | None = None

    # 上段3つ（メイン結果）
    bet_cowboy:   int | None = None
    bet_draw:     int | None = None
    bet_bull:     int | None = None

    # 任意のハンド（左列）3種
    bet_any_flash: int | None = None   # フラッシュ/コネクト/フラッシュコネクト
    bet_any_pair:  int | None = None   # ワンペア
    bet_any_ace:   int | None = None   # Aのペア

    # 勝利ハンド（右列）5種
    bet_win_high:  int | None = None   # ハイカード/ワンペア
    bet_win_two:   int | None = None   # ツーペア
    bet_win_sf:    int | None = None   # スリーカード/ストレート/フラッシュ
    bet_win_fh:    int | None = None   # フルハウス
    bet_win_four:  int | None = None   # フォーオブアカインド/SF/RSF

    # WIN フラグ（任意のハンド）
    win_any_flash: bool | None = None
    win_any_pair:  bool | None = None
    win_any_ace:   bool | None = None

    # WIN フラグ（勝利ハンド）
    win_high:  bool | None = None
    win_two:   bool | None = None
    win_sf:    bool | None = None
    win_fh:    bool | None = None
    win_four:  bool | None = None

    # オープンカードのクロップ画像（base64 JPEG, data URL形式）
    card_image: str | None = None

    # OCRデバッグ情報（Tesseract/Shape Matchなどのテキスト）
    ocr_debug: str | None = None

    # ラウンドログのファイル名
    log_file_name: str | None = None

    @field_validator("cowboy_hand", "bull_hand")
    @classmethod
    def validate_hand_type(cls, v: int | None) -> int | None:
        if v is not None and v not in VALID_HAND_TYPES:
            raise ValueError(f"hand type must be one of {VALID_HAND_TYPES}")
        return v

    @field_validator("open_card")
    @classmethod
    def validate_open_card(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 10:
            raise ValueError("open_card must be 10 characters or less")
        return v


def _row_to_dict(row) -> dict:
    d = {
        "id": row.id,
        "open_card": row.open_card,
        "result": row.result,
        "cowboy_hand": row.cowboy_hand,
        "bull_hand": row.bull_hand,
        "round_number": row.round_number,
        "recorded_at": row.recorded_at.isoformat(),
        "jackpot_stock": row.jackpot_stock,
        "bet_cowboy":    row.bet_cowboy,
        "bet_draw":      row.bet_draw,
        "bet_bull":      row.bet_bull,
        "bet_any_flash": row.bet_any_flash,
        "bet_any_pair":  row.bet_any_pair,
        "bet_any_ace":   row.bet_any_ace,
        "bet_win_high":  row.bet_win_high,
        "bet_win_two":   row.bet_win_two,
        "bet_win_sf":    row.bet_win_sf,
        "bet_win_fh":    row.bet_win_fh,
        "bet_win_four":  row.bet_win_four,
        "win_any_flash": row.win_any_flash,
        "win_any_pair":  row.win_any_pair,
        "win_any_ace":   row.win_any_ace,
        "win_high":      row.win_high,
        "win_two":       row.win_two,
        "win_sf":        row.win_sf,
        "win_fh":        row.win_fh,
        "win_four":      row.win_four,
    }
    all_bets = [
        row.bet_cowboy, row.bet_draw, row.bet_bull,
        row.bet_any_flash, row.bet_any_pair, row.bet_any_ace,
        row.bet_win_high, row.bet_win_two, row.bet_win_sf, row.bet_win_fh, row.bet_win_four,
    ]
    non_null = [b for b in all_bets if b is not None]
    d["total_bet"] = sum(non_null) if non_null else None
    d["card_image"] = row.card_image
    d["ocr_debug"] = row.ocr_debug
    d["log_file_name"] = row.log_file_name
    d["has_capture"] = Path(f"/app/logs/result_captures/{row.id}.jpg").exists()
    return d


@router.post("", status_code=status.HTTP_201_CREATED)
async def post_game(
    body: GamePostRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    latest_row = await db.execute(
        text("SELECT result, open_card, recorded_at FROM games ORDER BY recorded_at DESC, id DESC LIMIT 1")
    )
    latest = latest_row.fetchone()
    if (
        latest is not None
        and latest.result == body.result
        and latest.open_card == body.open_card
        and (datetime.now(UTC) - latest.recorded_at) <= timedelta(seconds=DUPLICATE_GUARD_SECONDS)
    ):
        return {"skipped": True, "reason": "duplicate"}

    inserted = await db.execute(
        text(
            "INSERT INTO games ("
            "  open_card, result, cowboy_hand, bull_hand, round_number, jackpot_stock,"
            "  bet_cowboy, bet_draw, bet_bull,"
            "  bet_any_flash, bet_any_pair, bet_any_ace,"
            "  bet_win_high, bet_win_two, bet_win_sf, bet_win_fh, bet_win_four,"
            "  win_any_flash, win_any_pair, win_any_ace,"
            "  win_high, win_two, win_sf, win_fh, win_four,"
            "  card_image, ocr_debug, log_file_name"
            ") VALUES ("
            "  :open_card, :result, :cowboy_hand, :bull_hand, :round_number, :jackpot_stock,"
            "  :bet_cowboy, :bet_draw, :bet_bull,"
            "  :bet_any_flash, :bet_any_pair, :bet_any_ace,"
            "  :bet_win_high, :bet_win_two, :bet_win_sf, :bet_win_fh, :bet_win_four,"
            "  :win_any_flash, :win_any_pair, :win_any_ace,"
            "  :win_high, :win_two, :win_sf, :win_fh, :win_four,"
            "  :card_image, :ocr_debug, :log_file_name"
            ") RETURNING "
            "  id, open_card, result, cowboy_hand, bull_hand, round_number, recorded_at,"
            "  jackpot_stock,"
            "  bet_cowboy, bet_draw, bet_bull,"
            "  bet_any_flash, bet_any_pair, bet_any_ace,"
            "  bet_win_high, bet_win_two, bet_win_sf, bet_win_fh, bet_win_four,"
            "  win_any_flash, win_any_pair, win_any_ace,"
            "  win_high, win_two, win_sf, win_fh, win_four,"
            "  card_image, ocr_debug, log_file_name"
        ),
        {
            "open_card": body.open_card, "result": body.result,
            "cowboy_hand": body.cowboy_hand, "bull_hand": body.bull_hand,
            "round_number": body.round_number, "jackpot_stock": body.jackpot_stock,
            "bet_cowboy": body.bet_cowboy, "bet_draw": body.bet_draw, "bet_bull": body.bet_bull,
            "bet_any_flash": body.bet_any_flash, "bet_any_pair": body.bet_any_pair, "bet_any_ace": body.bet_any_ace,
            "bet_win_high": body.bet_win_high, "bet_win_two": body.bet_win_two, "bet_win_sf": body.bet_win_sf,
            "bet_win_fh": body.bet_win_fh, "bet_win_four": body.bet_win_four,
            "win_any_flash": body.win_any_flash, "win_any_pair": body.win_any_pair, "win_any_ace": body.win_any_ace,
            "win_high": body.win_high, "win_two": body.win_two, "win_sf": body.win_sf,
            "win_fh": body.win_fh, "win_four": body.win_four,
            "card_image": body.card_image, "ocr_debug": body.ocr_debug, "log_file_name": body.log_file_name,
        },
    )
    row = inserted.fetchone()
    await db.commit()
    return _row_to_dict(row)


@router.get("")
async def get_games(
    limit: int = Query(default=100, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    rows = await db.execute(
        text(
            "SELECT id, open_card, result, cowboy_hand, bull_hand, round_number, recorded_at,"
            "       jackpot_stock,"
            "       bet_cowboy, bet_draw, bet_bull,"
            "       bet_any_flash, bet_any_pair, bet_any_ace,"
            "       bet_win_high, bet_win_two, bet_win_sf, bet_win_fh, bet_win_four,"
            "       win_any_flash, win_any_pair, win_any_ace,"
            "       win_high, win_two, win_sf, win_fh, win_four,"
            "       card_image, ocr_debug, log_file_name "
            "FROM games ORDER BY recorded_at DESC, id DESC "
            "LIMIT :limit OFFSET :offset"
        ),
        {"limit": limit, "offset": offset},
    )
    games = [_row_to_dict(row) for row in rows]
    count_row = await db.execute(text("SELECT COUNT(*) FROM games"))
    total = count_row.scalar()
    return {"games": games, "total": total, "limit": limit, "offset": offset}


@router.get("/debug-db")
async def debug_db(
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        text("SELECT id, round_number, result, open_card, recorded_at FROM games WHERE round_number >= 231100 AND round_number <= 231120 ORDER BY round_number ASC")
    )
    res = []
    for r in rows:
        res.append({
            "id": r.id,
            "round_number": r.round_number,
            "result": r.result,
            "open_card": r.open_card,
            "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None
        })
    return res


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """全体の集計統計を返す"""
    total_row = await db.execute(text("SELECT COUNT(*) FROM games"))
    total = total_row.scalar() or 0

    if total == 0:
        return {
            "total": 0,
            "result_counts": {"cowboy": 0, "draw": 0, "bull": 0},
            "result_rates": {"cowboy": 0.0, "draw": 0.0, "bull": 0.0},
        }

    result_rows = await db.execute(text("SELECT result, COUNT(*) AS cnt FROM games GROUP BY result"))
    result_counts = {"cowboy": 0, "draw": 0, "bull": 0, "error": 0}
    for row in result_rows:
        if row.result in result_counts:
            result_counts[row.result] = row.cnt
    result_rates = {k: round(v / total, 4) for k, v in result_counts.items()}

    full_bets_row = await db.execute(
        text(
            "SELECT COUNT(*) AS records_with_bets "
            "FROM games "
            "WHERE bet_cowboy IS NOT NULL AND bet_draw IS NOT NULL AND bet_bull IS NOT NULL "
            "  AND bet_any_flash IS NOT NULL AND bet_any_pair IS NOT NULL AND bet_any_ace IS NOT NULL "
            "  AND bet_win_high IS NOT NULL AND bet_win_two IS NOT NULL "
            "  AND bet_win_sf IS NOT NULL AND bet_win_fh IS NOT NULL AND bet_win_four IS NOT NULL"
        )
    )
    full_bets = full_bets_row.fetchone()

    fin_row = await db.execute(
        text(
            "SELECT "
            "  SUM(COALESCE(bet_cowboy,0) + COALESCE(bet_draw,0) + COALESCE(bet_bull,0) + "
            "      COALESCE(bet_any_flash,0) + COALESCE(bet_any_pair,0) + COALESCE(bet_any_ace,0) + "
            "      COALESCE(bet_win_high,0) + COALESCE(bet_win_two,0) + COALESCE(bet_win_sf,0) + "
            "      COALESCE(bet_win_fh,0) + COALESCE(bet_win_four,0)) AS total_bet_sum, "
            "  SUM("
            "    CASE WHEN result='cowboy' THEN COALESCE(bet_cowboy,0)*2.02 "
            "         WHEN result='draw'   THEN COALESCE(bet_draw,0)*22.0 "
            "         WHEN result='bull'   THEN COALESCE(bet_bull,0)*2.02 "
            "         ELSE 0.0 END "
            "    + CASE WHEN win_any_flash=TRUE THEN COALESCE(bet_any_flash,0)*1.67 ELSE 0.0 END "
            "    + CASE WHEN win_any_pair=TRUE  THEN COALESCE(bet_any_pair,0)*8.5   ELSE 0.0 END "
            "    + CASE WHEN win_any_ace=TRUE   THEN COALESCE(bet_any_ace,0)*100.0  ELSE 0.0 END "
            "    + CASE WHEN win_high=TRUE      THEN COALESCE(bet_win_high,0)*2.2   ELSE 0.0 END "
            "    + CASE WHEN win_two=TRUE       THEN COALESCE(bet_win_two,0)*3.1    ELSE 0.0 END "
            "    + CASE WHEN win_sf=TRUE        THEN COALESCE(bet_win_sf,0)*4.7     ELSE 0.0 END "
            "    + CASE WHEN win_fh=TRUE        THEN COALESCE(bet_win_fh,0)*20.5   ELSE 0.0 END "
            "    + CASE WHEN win_four=TRUE      THEN COALESCE(bet_win_four,0)*250.0 ELSE 0.0 END "
            "  ) AS total_payout_raw "
            "FROM games"
        )
    )
    fin = fin_row.fetchone()
    total_bet_sum = int(fin.total_bet_sum or 0) if fin else 0
    total_payout = int(fin.total_payout_raw or 0) if fin else 0

    return {
        "total": total,
        "result_counts": result_counts,
        "result_rates": result_rates,
        "records_with_full_bets": int(full_bets.records_with_bets) if full_bets else 0,
        "total_bet_all_positions": total_bet_sum or None,
        "total_bet_sum": total_bet_sum,
        "total_payout": total_payout,
        "user_pnl": total_payout - total_bet_sum,
    }


@router.get("/card-stats")
async def get_card_stats(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """カード別のWIN確率・統計データを集計して返す"""
    query = text("""
        SELECT
            open_card,
            COUNT(*) AS total_count,
            COUNT(CASE WHEN result = 'cowboy' THEN 1 END) AS count_cowboy,
            COUNT(CASE WHEN result = 'draw' THEN 1 END) AS count_draw,
            COUNT(CASE WHEN result = 'bull' THEN 1 END) AS count_bull,
            COUNT(CASE WHEN win_any_flash = TRUE THEN 1 END) AS count_any_flash,
            COUNT(CASE WHEN win_any_pair = TRUE THEN 1 END) AS count_any_pair,
            COUNT(CASE WHEN win_any_ace = TRUE THEN 1 END) AS count_any_ace,
            COUNT(CASE WHEN win_high = TRUE THEN 1 END) AS count_win_high,
            COUNT(CASE WHEN win_two = TRUE THEN 1 END) AS count_win_two,
            COUNT(CASE WHEN win_sf = TRUE THEN 1 END) AS count_win_sf,
            COUNT(CASE WHEN win_fh = TRUE THEN 1 END) AS count_win_fh,
            COUNT(CASE WHEN win_four = TRUE THEN 1 END) AS count_win_four
        FROM games
        WHERE open_card IS NOT NULL AND open_card != ''
        GROUP BY open_card
        ORDER BY open_card ASC
    """)
    rows = await db.execute(query)
    
    stats_list = []
    for r in rows:
        total = r.total_count
        if total == 0:
            continue
        stats_list.append({
            "card": r.open_card,
            "total": total,
            "rates": {
                "cowboy": round(r.count_cowboy / total, 4),
                "draw": round(r.count_draw / total, 4),
                "bull": round(r.count_bull / total, 4),
                "any_flash": round(r.count_any_flash / total, 4),
                "any_pair": round(r.count_any_pair / total, 4),
                "any_ace": round(r.count_any_ace / total, 4),
                "win_high": round(r.count_win_high / total, 4),
                "win_two": round(r.count_win_two / total, 4),
                "win_sf": round(r.count_win_sf / total, 4),
                "win_fh": round(r.count_win_fh / total, 4),
                "win_four": round(r.count_win_four / total, 4),
            }
        })
    return {"card_stats": stats_list}


@router.get("/card-stats/{card}")
async def get_card_stat_single(
    card: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """指定カード1枚の WIN 確率統計を返す（ライブキャプチャ用）"""
    query = text("""
        SELECT
            COUNT(*) AS total_count,
            COUNT(CASE WHEN result = 'cowboy' THEN 1 END) AS count_cowboy,
            COUNT(CASE WHEN result = 'draw' THEN 1 END) AS count_draw,
            COUNT(CASE WHEN result = 'bull' THEN 1 END) AS count_bull,
            COUNT(CASE WHEN win_any_flash = TRUE THEN 1 END) AS count_any_flash,
            COUNT(CASE WHEN win_any_pair = TRUE THEN 1 END) AS count_any_pair,
            COUNT(CASE WHEN win_any_ace = TRUE THEN 1 END) AS count_any_ace,
            COUNT(CASE WHEN win_high = TRUE THEN 1 END) AS count_win_high,
            COUNT(CASE WHEN win_two = TRUE THEN 1 END) AS count_win_two,
            COUNT(CASE WHEN win_sf = TRUE THEN 1 END) AS count_win_sf,
            COUNT(CASE WHEN win_fh = TRUE THEN 1 END) AS count_win_fh,
            COUNT(CASE WHEN win_four = TRUE THEN 1 END) AS count_win_four
        FROM games
        WHERE open_card = :card
    """)
    row = (await db.execute(query, {"card": card})).fetchone()
    if row is None or row.total_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No data for this card")
    total = row.total_count
    return {
        "card": card,
        "total": total,
        "rates": {
            "cowboy":    round(row.count_cowboy / total, 4),
            "draw":      round(row.count_draw / total, 4),
            "bull":      round(row.count_bull / total, 4),
            "any_flash": round(row.count_any_flash / total, 4),
            "any_pair":  round(row.count_any_pair / total, 4),
            "any_ace":   round(row.count_any_ace / total, 4),
            "win_high":  round(row.count_win_high / total, 4),
            "win_two":   round(row.count_win_two / total, 4),
            "win_sf":    round(row.count_win_sf / total, 4),
            "win_fh":    round(row.count_win_fh / total, 4),
            "win_four":  round(row.count_win_four / total, 4),
        }
    }


@router.get("/logs/{filename}")
async def get_round_log(
    filename: str,
    _: dict = Depends(get_current_user),
):
    """特定のラウンドログファイルの内容を配信する"""
    # ディレクトリトラバーサル防止
    safe_name = Path(filename).name
    log_path = Path("/app/logs") / safe_name
    if not log_path.exists() or not log_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Log file not found"
        )
    return FileResponse(log_path, media_type="text/plain")


@router.get("/captures/{game_id}")
async def get_game_capture(
    game_id: int,
    _: dict = Depends(get_current_user),
):
    """ゲームの結果表示キャプチャ画像ファイルを配信する"""
    capture_path = Path("/app/logs/result_captures") / f"{game_id}.jpg"
    if not capture_path.exists() or not capture_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Result capture not found"
        )
    return FileResponse(capture_path, media_type="image/jpeg")
