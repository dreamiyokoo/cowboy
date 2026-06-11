import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError

from core.redis import get_redis
from deps import get_current_user

router = APIRouter(prefix="/api/v1/capture", tags=["capture"])

PREVIEW_KEY = "cowboy:capture:latest_preview"
PREVIEW_TTL_SECONDS = 60 * 10


class CapturePreviewPayload(BaseModel):
    state: str | None = None               # ゲームの状態（preparing, betting, result, cooldown）
    open_detected_at: str | None = None    # オープンカード検出時刻
    result_detected_at: str | None = None  # 結果検出時刻
    result: str | None = None         # cowboy / draw / bull
    open_card: str | None = None      # 最初に開かれたカード
    round_number: int | None = None   # ラウンド番号
    cowboy_hand: int | None = None    # カウボーイ側ハンドタイプ
    bull_hand: int | None = None      # ブル側ハンドタイプ
    screen_image: str | None = None           # メインスクリーンショット
    round_image: str | None = None            # ラウンド番号クロップ
    open_card_image: str | None = None        # オープンカードクロップ
    result_image: str | None = None           # 結果ボタン行クロップ
    bet_images: dict[str, str | None] | None = None          # ベット領域 11ポジション
    win_images: dict[str, str | None] | None = None          # WIN判定領域 8個
    winning_hand_images: list[str | None] | None = None      # 勝利ハンド 3行
    bet_values: dict[str, int | None] | None = None          # ベット額（OCR結果）
    win_scores: dict[str, float] | None = None               # WIN輝度スコア（リアルタイム）
    result_scores: dict[str, float] | None = None            # 結果領域輝度スコア
    winning_hand_scores: list[float] | None = None           # 勝利ハンド行輝度スコア
    jackpot_stock: int | None = None                         # ジャックポットストックコイン
    jackpot_stock_image: str | None = None                   # ジャックポットクロップ画像
    timer_value: int | None = None                           # タイマーOCR検出値（カウントダウン秒数）
    timer_image: str | None = None                           # タイマークロップ画像



@router.post("/preview", status_code=status.HTTP_204_NO_CONTENT)
async def upsert_capture_preview(
    body: CapturePreviewPayload,
    redis: Redis = Depends(get_redis),
    _: dict = Depends(get_current_user),
):
    try:
        await redis.setex(PREVIEW_KEY, PREVIEW_TTL_SECONDS, body.model_dump_json())
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Preview cache unavailable",
        ) from exc


@router.get("/preview")
async def get_capture_preview(
    redis: Redis = Depends(get_redis),
    _: dict = Depends(get_current_user),
):
    try:
        payload = await redis.get(PREVIEW_KEY)
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Preview cache unavailable",
        ) from exc

    if not payload:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preview not found")

    data = json.loads(payload)

    # ゲーム状態を決定:
    #   キャプチャから明示的な state が送られている場合はそれを最優先で採用
    #   送られていない場合は従来通り result の有無で推定
    remaining_seconds: float | None = None

    if data.get("state"):
        state = data["state"]
    elif data.get("result"):
        # 結果（WINバッジ）が検出されている → 結果表示状態
        state = "result"
    else:
        # WIN がどこにも無い → 投票中
        state = "betting"

    if state == "betting":
        if data.get("open_detected_at"):
            # オープン検出からの経過時間で残り秒数を推定
            open_time = datetime.fromisoformat(data["open_detected_at"])
            now = datetime.now(UTC)
            elapsed = (now - open_time).total_seconds()
            # 推定: オープン表示 10秒 + カウントダウン 15秒 = 25秒 で結果
            GAME_TOTAL_SECONDS = 25
            remaining_seconds = max(0, GAME_TOTAL_SECONDS - elapsed)
    elif state == "cooldown":
        if data.get("result_detected_at"):
            result_time = datetime.fromisoformat(data["result_detected_at"])
            now = datetime.now(UTC)
            elapsed = (now - result_time).total_seconds()
            COOLDOWN_TOTAL_SECONDS = 18
            remaining_seconds = max(0, COOLDOWN_TOTAL_SECONDS - elapsed)

    data["game_state"] = state
    data["remaining_seconds"] = remaining_seconds

    return data
