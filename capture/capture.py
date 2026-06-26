#!/usr/bin/env python3
"""
capture.py — ADB スクリーンショット → 画像解析 → /api/v1/games 送信

【ゲームの流れ】
  1. オープンカード（1枚）が表示される（~10秒）
  2. カウントダウン 15秒 → 0 になると結果表示
  3. 結果（カウボーイ / 抽選 / ブル）が数秒表示される
  4. 次のラウンドへ（合計約25秒/ラウンド）

【ステートマシン】
  WATCHING  : 結果が現れるのを待ちながらオープンカードを随時取得
              → 結果を result_stable_count 回連続検出したら POST
  COOLDOWN  : POST 後、post_round_cooldown 秒待機
              → 終わったら WATCHING に戻る

使い方:
    python3 capture/capture.py                 # 継続監視モード
    python3 capture/capture.py --once          # 1回スキャンして終了
    python3 capture/capture.py --debug         # デバッグ画像を /tmp に保存
"""

import argparse
import atexit
import base64
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np
import pytesseract
import yaml

from predict import load_model, predict as ml_predict, load_side_bet_models, predict_side_bets

# EasyOCR はオプション: 未インストールの場合は None
try:
    import easyocr as _easyocr
    _easyocr_available = True
except ImportError:
    _easyocr_available = False

# EasyOCR Reader は初回使用時に遅延初期化（モデルロードに数秒かかる）
_ocr_reader: Any = None


def _get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        if not _easyocr_available:
            return None
        print("[INFO] EasyOCR モデルをロード中...")
        _ocr_reader = _easyocr.Reader(["en"], gpu=False, verbose=False)
        print("[INFO] EasyOCR ロード完了")
    return _ocr_reader

class LogCapturer:
    def __init__(self):
        self.buffer = []
        self.original_stdout = sys.stdout

    def write(self, message):
        self.original_stdout.write(message)
        stripped = message.strip()
        if stripped:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            self.buffer.append(f"[{timestamp}] {stripped}")

    def flush(self):
        self.original_stdout.flush()

    def reset(self):
        self.buffer = []

    def get_logs(self) -> str:
        return "\n".join(self.buffer)


def save_round_log(capturer: LogCapturer, round_number: int | None) -> str:
    log_dir = Path("/app/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if round_number is not None:
        filename = f"{round_number}.log"
    else:
        filename = f"error_{timestamp}.log"
        
    filepath = log_dir / filename
    
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(capturer.get_logs())
    except Exception as e:
        # original_stdout を使って直接コンソールに出力する（ループ無限再帰を避けるため）
        capturer.original_stdout.write(f"[WARN] ログファイル書き込み失敗: {e}\n")
        
    # ローテーション（最大100件）
    try:
        log_files = sorted(
            log_dir.glob("*.log"),
            key=lambda x: x.stat().st_mtime
        )
        if len(log_files) > 100:
            for f in log_files[:-100]:
                f.unlink(missing_ok=True)
    except Exception as e:
        capturer.original_stdout.write(f"[WARN] ログローテーションでエラー発生: {e}\n")
        
    return filename


CONFIG_PATH = Path(__file__).parent / "config.yml"

_prediction_model = load_model(Path(__file__).parent / "model.pkl")
if _prediction_model is not None:
    print(f"[INFO] 予測モデルをロード: {getattr(_prediction_model, '_model_version', 'unknown')}")
else:
    print("[INFO] 予測モデルなし（予測機能無効）")

_side_bet_models = load_side_bet_models(Path(__file__).parent / "side_bet_models.pkl")
if _side_bet_models is not None:
    loaded = [k for k, v in _side_bet_models.items() if v is not None]
    print(f"[INFO] サイドベットモデルをロード: {loaded}")
else:
    print("[INFO] サイドベットモデルなし")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    if os.getenv("CAPTURE_USERNAME"):
        cfg["api"]["username"] = os.getenv("CAPTURE_USERNAME")
    if os.getenv("CAPTURE_PASSWORD"):
        cfg["api"]["password"] = os.getenv("CAPTURE_PASSWORD")
    if os.getenv("API_BASE_URL"):
        cfg["api"]["base_url"] = os.getenv("API_BASE_URL")
    return cfg


def is_card_back_green(img: np.ndarray, crop: list[int]) -> bool:
    """カード裏面（緑色）かどうかを判定する"""
    y0, y1, x0, x1 = crop
    region = img[y0:y1, x0:x1]
    if region.size == 0:
        return False
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    # 緑色のHSV範囲をより厳格に設定（高彩度・高明度のみ）
    # H: 35〜85, S: 80〜255, V: 70〜255
    green_mask = cv2.inRange(hsv, np.array([35, 80, 70]), np.array([85, 255, 255]))
    total = region.size // 3
    if total == 0:
        return False
    ratio = np.count_nonzero(green_mask) / total
    return ratio > 0.55


# ────────────────────────────────────────────────
# ステート定義
# ────────────────────────────────────────────────

class State(Enum):
    PREPARING = "preparing"  # 準備中（カードが裏面）
    BETTING   = "betting"    # ベット受付中・結果待ち（カードが表面）
    RESULT    = "result"     # 結果表示中（WIN検出）
    COOLDOWN  = "cooldown"   # 結果POST後のクールダウン中


# ────────────────────────────────────────────────
# ADB ユーティリティ
# ────────────────────────────────────────────────

def adb_cmd(device: str, *args: str) -> list[str]:
    base = ["adb"]
    if device != "usb":
        base += ["-s", device]
    return base + list(args)


def recover_adb_connection(device: str) -> None:
    try:
        subprocess.run(adb_cmd(device, "reconnect"), capture_output=True, timeout=8)
        subprocess.run(adb_cmd(device, "wait-for-device"), capture_output=True, timeout=15)
        print("[INFO] ADB 接続をリカバリしました")
    except subprocess.TimeoutExpired:
        print("[WARN] ADB リカバリがタイムアウトしました", file=sys.stderr)


def take_screenshot(device: str) -> np.ndarray | None:
    """adb screencap で画像を取得して numpy 配列で返す"""
    try:
        result = subprocess.run(
            adb_cmd(device, "exec-out", "screencap", "-p"),
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="ignore")
            print(f"[WARN] screencap failed: {stderr}", file=sys.stderr)
            if any(msg in stderr for msg in [
                "no devices/emulators found",
                "cannot connect to daemon",
                "Connection refused",
            ]):
                recover_adb_connection(device)
            return None
        arr = np.frombuffer(result.stdout, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return img
    except subprocess.TimeoutExpired:
        print("[WARN] screencap timed out", file=sys.stderr)
        return None


# ────────────────────────────────────────────────
# フレーム差分チェック（ハング検出）
# ────────────────────────────────────────────────

def compute_frame_hash(img: np.ndarray) -> str:
    """フレーム画像の簡易ハッシュを計算（高速）。リサイズして縮小ハッシュを生成。"""
    if img is None or img.size == 0:
        return "none"
    try:
        # 小さくリサイズしてからハッシュ計算（高速化）
        small = cv2.resize(img, (64, 64), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        # numpy array をバイナリ化してハッシュ
        import hashlib
        return hashlib.md5(gray.tobytes()).hexdigest()
    except Exception as e:
        print(f"[WARN] compute_frame_hash failed: {e}", file=sys.stderr)
        return "error"


class FrameHangDetector:
    """連続フレーム間で差分がない場合をハング判定する"""
    def __init__(self, threshold: int = 5, timeout_seconds: int = 10):
        """
        threshold: 同じフレームが何回連続したらハング判定するか
        timeout_seconds: ハング判定の時間ウィンドウ
        """
        self.threshold = threshold
        self.timeout_seconds = timeout_seconds
        self.frame_history: list[tuple[str, float]] = []  # (hash, timestamp) のリスト
        self.hang_detected_at: float | None = None
        self.last_frame_hash: str | None = None

    def check(self, img: np.ndarray, current_time: float) -> bool:
        """
        フレーム差分をチェック。同じフレームが threshold 回以上続いたら True を返す。
        ハングが検出済みの場合は、timeout_seconds を超えるまで True を返し続ける（リセット待機）
        """
        # クリーンアップ：古い履歴を削除
        self.frame_history = [
            (h, t) for h, t in self.frame_history
            if current_time - t < self.timeout_seconds
        ]

        frame_hash = compute_frame_hash(img)
        self.frame_history.append((frame_hash, current_time))

        # ハング検出中：timeout_seconds を超えるまで True を返す
        if self.hang_detected_at is not None:
            if current_time - self.hang_detected_at > self.timeout_seconds:
                # タイムアウト経過 → リセット
                self.hang_detected_at = None
                self.frame_history.clear()
                self.last_frame_hash = None
                return False
            else:
                return True

        # ハング判定：同じハッシュが threshold 回以上連続
        if len(self.frame_history) >= self.threshold:
            recent_hashes = [h for h, _ in self.frame_history[-self.threshold:]]
            if len(set(recent_hashes)) == 1 and recent_hashes[0] != "none":
                # 全て同じハッシュ（かつ valid）
                self.hang_detected_at = current_time
                print(f"[WARN] フレームハング検出: {self.threshold}フレーム同一 (hash={recent_hashes[0][:8]}...)")
                return True

        self.last_frame_hash = frame_hash
        return False

    def reset(self):
        """ハング検出状態をリセット"""
        self.frame_history.clear()
        self.hang_detected_at = None
        self.last_frame_hash = None


# ────────────────────────────────────────────────
# 画像エンコード
# ────────────────────────────────────────────────

def encode_jpeg(img: np.ndarray, quality: int = 70) -> str:
    ok, encoded = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("failed to encode image as JPEG")
    return f"data:image/jpeg;base64,{base64.b64encode(encoded.tobytes()).decode('ascii')}"


def encode_crop(img: np.ndarray, crop: list[int], scale: int = 3) -> str | None:
    """クロップ領域を拡大して JPEG data URL にエンコードする（OCR判定範囲の確認用）。"""
    y0, y1, x0, x1 = crop
    region = img[y0:y1, x0:x1]
    if region.size == 0:
        return None
    large = cv2.resize(region, None, fx=scale, fy=scale, interpolation=cv2.INTER_LANCZOS4)
    return encode_jpeg(large, quality=85)


# カード画像の保存先（ローテーション用）
_CARD_SHOTS_DIR = Path(__file__).parent / "card_shots"
_CARD_SHOTS_MAX = 100


def _save_card_shot(game_id: int, card: str, img: np.ndarray, crop: list[int] | None = None) -> None:
    """
    オープンカードのクロップ画像を card_shots/{id}_{card}.jpg に保存する。
    最新 _CARD_SHOTS_MAX 件を超えた分は古い順に削除してローテーションする。
    """
    try:
        _CARD_SHOTS_DIR.mkdir(exist_ok=True)
        if crop is not None:
            y0, y1, x0, x1 = crop
            region = img[y0:y1, x0:x1]
        else:
            region = img
        if region.size == 0:
            return
        # 4倍拡大してJPEG保存（OCR精度確認用）
        large = cv2.resize(region, None, fx=4, fy=4, interpolation=cv2.INTER_LANCZOS4)
        filename = _CARD_SHOTS_DIR / f"{game_id}_{card}.jpg"
        cv2.imwrite(str(filename), large, [int(cv2.IMWRITE_JPEG_QUALITY), 85])

        # ローテーション: 古いファイルを削除
        shots = sorted(_CARD_SHOTS_DIR.glob("*.jpg"), key=lambda p: p.stat().st_mtime)
        while len(shots) > _CARD_SHOTS_MAX:
            shots[0].unlink(missing_ok=True)
            shots = shots[1:]
    except Exception as e:
        print(f"[WARN] card_shot 保存失敗: {e}", file=sys.stderr)


_RESULT_CAPTURES_DIR = Path("/app/logs/result_captures")
_RESULT_CAPTURES_MAX = 100


def _save_result_capture(game_id: int, img: np.ndarray) -> None:
    """
    結果表示のスクリーンショットを /app/logs/result_captures/{id}.jpg に保存する。
    最新 _RESULT_CAPTURES_MAX 件を超えた分は古い順に削除してローテーションする。
    """
    try:
        _RESULT_CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        if img.size == 0:
            return
        # 1/2サイズに縮小してJPEG保存
        h, w = img.shape[:2]
        small = cv2.resize(img, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
        filename = _RESULT_CAPTURES_DIR / f"{game_id}.jpg"
        cv2.imwrite(str(filename), small, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        print(f"[INFO] result_capture 保存成功: {filename}")

        # ローテーション: 古いファイルを削除
        captures = sorted(_RESULT_CAPTURES_DIR.glob("*.jpg"), key=lambda p: p.stat().st_mtime)
        while len(captures) > _RESULT_CAPTURES_MAX:
            captures[0].unlink(missing_ok=True)
            captures = captures[1:]
    except Exception as e:
        print(f"[WARN] result_capture 保存失敗: {e}", file=sys.stderr)



# ────────────────────────────────────────────────
# 結果判定（カウボーイ / 抽選 / ブル）
# ────────────────────────────────────────────────

def detect_result(img: np.ndarray, crop: list[int], debug: bool = False) -> str | None:
    """
    結果ボタン行を3分割し、WIN バッジ（V > 220 が最も集中する）が
    どのセクションにあるかで勝者を判定する。

    ボタン配置（左→右）:
      左1/3 → カウボーイ勝利 (cowboy)
      中1/3 → 抽選         (draw)
      右1/3 → ノルの勝利   (bull)

    detect_winning_hand と同じ判定方式を採用:
      - V > 220 のピクセル比率でスコアリング（彩度条件なし）
      - max >= 0.28 かつ 2位の 1.5 倍以上 → 確定
    """
    y0, y1, x0, x1 = crop
    region = img[y0:y1, x0:x1]
    if region.size == 0:
        return None

    w = region.shape[1]
    third = w // 3

    sections: dict[str, np.ndarray] = {
        "cowboy": region[:, :third],
        "draw":   region[:, third:2 * third],
        "bull":   region[:, 2 * third:],
    }

    scores: dict[str, float] = {}
    for name, sec in sections.items():
        hsv = cv2.cvtColor(sec, cv2.COLOR_BGR2HSV)
        bright = float(np.count_nonzero(hsv[:, :, 2] > 220)) / (sec.shape[0] * sec.shape[1])
        scores[name] = bright

    if debug:
        print(f"[DEBUG] result brightness: {scores}")
        cv2.imwrite("/tmp/cowboy_result_region.png", region)

    sorted_scores = sorted(scores.values(), reverse=True)
    max_score = sorted_scores[0]
    second_score = sorted_scores[1] if len(sorted_scores) > 1 else 0.0

    if max_score < 0.28:
        return None

    # 2位の 1.5 倍以上なければ曖昧として棄却（detect_winning_hand と同じ基準）
    if second_score > 0 and max_score < second_score * 1.5:
        if debug:
            print(f"[DEBUG] result ambiguous: max={max_score:.3f}, 2nd={second_score:.3f} -> reject")
        return None

    return max(scores, key=scores.get)


# ────────────────────────────────────────────────
# 勝利ハンド判定（手1 / 手2 / 手3）
# ────────────────────────────────────────────────

def detect_winning_hand(img: np.ndarray, crop: list[int], debug: bool = False) -> int | None:
    """
    「勝利ハンド」セクション（3行）を輝度スキャンし、
    WIN バッジ（V > 220 が最も集中する行）を 1 / 2 / 3 で返す。

    scan データ実測値（bull 勝利時）:
      手1 bright ≈ 0.07〜0.18  (非当選)
      手2 bright ≈ 0.35        (当選)  ← WIN バッジ行
      手3 bright ≈ 0.08〜0.12  (非当選)

    閾値: max bright > 0.28 かつ 2位の1.5倍以上 → 確定
    どちらも満たさない場合は None（まだ表示されていない）
    """
    row_crops: list[list[int]] = crop  # [[y0,y1,x0,x1], [y0,y1,x0,x1], [y0,y1,x0,x1]]
    scores: list[float] = []
    for rc in row_crops:
        y0, y1, x0, x1 = rc
        sec = img[y0:y1, x0:x1]
        if sec.size == 0:
            scores.append(0.0)
            continue
        hsv = cv2.cvtColor(sec, cv2.COLOR_BGR2HSV)
        bright = float(np.count_nonzero(hsv[:, :, 2] > 220)) / (sec.shape[0] * sec.shape[1])
        scores.append(bright)

    if debug:
        for i, s in enumerate(scores, 1):
            print(f"[DEBUG] winning_hand 手{i}: bright={s:.3f}")

    max_score = max(scores)
    if max_score < 0.28:
        return None

    max_idx = scores.index(max_score)
    # 2位の score と比較して明確に高ければ確定
    sorted_scores = sorted(scores, reverse=True)
    second = sorted_scores[1] if len(sorted_scores) > 1 else 0.0
    if second > 0 and max_score < second * 1.5:
        return None  # 差が不明瞭

    return max_idx + 1  # 1-indexed


# ────────────────────────────────────────────────
# オープンカード OCR
# ────────────────────────────────────────────────

def _parse_card_text(text: str, region: np.ndarray) -> str | None:
    """OCR テキストからカード文字列を解析する共通処理"""
    text = re.sub(r"\s+", "", text.upper())

    # ランク抽出（長いものを優先）
    rank = None
    for r in ["10", "A", "K", "Q", "J", "9", "8", "7", "6", "5", "4", "3", "2"]:
        if r in text:
            rank = r
            break

    if rank is None:
        return None

    # スート抽出
    suit = None
    for sym, abbr in [("♠", "S"), ("♥", "H"), ("♦", "D"), ("♣", "C")]:
        if sym in text:
            suit = abbr
            break
    if suit is None:
        for abbr in ["S", "H", "D", "C"]:
            if abbr in text:
                suit = abbr
                break
    if suit is None:
        suit = _estimate_suit_by_color(region)

    return f"{rank}{suit}" if suit else rank


def enhance_card_image(img: np.ndarray) -> np.ndarray:
    """
    画像を完全に「白 (255,255,255)」「赤 (0,0,255)」「黒 (0,0,0)」の3色のみに強制変換（減色）する。
    カードの背景の影や曖昧なグレーを完全に排除します。
    """
    if img is None or img.size == 0:
        return img
    try:
        # 1. チャンネル分割と型キャスト（オーバーフロー防止）
        b_ch, g_ch, r_ch = cv2.split(img)
        r_int = r_ch.astype(np.int16)
        g_int = g_ch.astype(np.int16)
        b_int = b_ch.astype(np.int16)
        
        # 2. 赤色領域の抽出（R - B > 35 かつ R - G > 30）
        # テーブル background や warm gray を赤と誤判定するのを防ぎます
        red_mask = ((r_int - b_int) > 35) & ((r_int - g_int) > 30)
        
        # 3. 赤以外の部分を白黒（二値化）判定する
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        min_v, max_v, _, _ = cv2.minMaxLoc(gray)
        
        # 適応的な閾値の決定（最小値と最大値の中間値）
        if max_v - min_v > 15:
            thresh_val = min_v + (max_v - min_v) * 0.45
        else:
            thresh_val = 127
            
        _, binary = cv2.threshold(gray, thresh_val, 255, cv2.THRESH_BINARY)
        
        # 4. 3色の出力画像を合成
        # デフォルトは白 (255, 255, 255)
        out = np.full_like(img, 255)
        
        # 二値化で閾値未満（黒）の部分を (0, 0, 0) に設定
        out[binary == 0] = [0, 0, 0]
        
        # 赤色マスクの部分を (0, 0, 255) に強制上書き
        out[red_mask] = [0, 0, 255]
        
        return out
    except Exception as e:
        print(f"[WARNING] enhance_card_image failed: {e}")
        return img


def detect_open_card(
    img: np.ndarray,
    crop: list[int] | None,
    rank_crop: list[int] | None = None,
    suit_crop: list[int] | None = None,
    scale: int = 4,
    debug: bool = False,
    debug_logs: list[str] | None = None
) -> str | None:
    """
    オープンカード領域から カード文字列 (例: "AH", "KS", "10D") を OCR で取得する。
    - 緑（裏面）検出時は None を返す
    - rank_crop / suit_crop が指定されている場合、それぞれ絶対座標として切り出して個別に解析する
    """
    # 1. 全体領域（裏面判定・キャッシュ保存の基準）
    if crop is not None:
        y0, y1, x0, x1 = crop
        region = img[y0:y1, x0:x1]
    else:
        region = img
    if region.size == 0:
        return None

    h, w = region.shape[:2]

    # ── 裏面（緑）チェック ──────────────────────
    hsv_full = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    # is_card_back_greenと同様に厳格な範囲を使用し、誤検知を防ぐ
    green_mask = cv2.inRange(hsv_full, np.array([35, 80, 70]), np.array([85, 255, 255]))
    green_ratio = np.count_nonzero(green_mask) / (h * w) if h * w > 0 else 0
    if green_ratio > 0.45:
        msg = f"[DEBUG] open_card: 緑裏面検出 (green_ratio={green_ratio:.2f}) → スキップ"
        if debug:
            print(msg)
        if debug_logs is not None:
            debug_logs.append(msg)
        return None

    # ── ランク認識 ──────────────────
    if rank_crop is not None:
        ry0, ry1, rx0, rx1 = rank_crop
        rank_region = img[ry0:ry1, rx0:rx1]
    else:
        # フォールバック: 比率で切り出す
        rank_end_ratio = 0.40
        try:
            cfg = load_config()
            ratios = cfg.get("capture", {}).get("open_card_ratios", {})
            if ratios:
                rank_end_ratio = ratios.get("rank_end", rank_end_ratio)
        except Exception:
            pass
        rank_region = region[0:int(h * rank_end_ratio), :]

    if rank_region.size == 0:
        return None

    large_rank = cv2.resize(rank_region, None, fx=scale, fy=scale, interpolation=cv2.INTER_LANCZOS4)
    gray_rank = cv2.cvtColor(large_rank, cv2.COLOR_BGR2GRAY)

    # 明るさの変化に対応するため、複数の入力バリエーションで OCR を試みる
    _, thresh_otsu = cv2.threshold(gray_rank, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, thresh_fixed = cv2.threshold(gray_rank, 127, 255, cv2.THRESH_BINARY)

    inputs_to_try = [thresh_otsu, thresh_fixed, gray_rank]
    config_rank = "--oem 1 --psm 8 -c tessedit_char_whitelist=AKQJ0123456789"
    rank = None

    for inp in inputs_to_try:
        tess_rank = re.sub(r"\s+", "", pytesseract.image_to_string(inp, config=config_rank).strip().upper())
        msg = f"[DEBUG] rank Tesseract try: {repr(tess_rank)}"
        if debug:
            print(msg)
        if debug_logs is not None:
            debug_logs.append(msg)
        for r in ["10", "A", "K", "Q", "J", "9", "8", "7", "6", "5", "4", "3", "2"]:
            if r in tess_rank:
                rank = r
                break
        if rank is not None:
            break

    # EasyOCR フォールバック（ランク）
    if rank is None:
        reader = _get_ocr_reader()
        if reader is not None:
            easy_rank = re.sub(r"\s+", "", " ".join(reader.readtext(large_rank, detail=0)).upper())
            msg = f"[DEBUG] rank EasyOCR raw: {repr(easy_rank)}"
            if debug:
                print(msg)
            if debug_logs is not None:
                debug_logs.append(msg)
            for r in ["10", "A", "K", "Q", "J", "9", "8", "7", "6", "5", "4", "3", "2"]:
                if r in easy_rank:
                    rank = r
                    break

    if rank is None:
        return None

    # ── スート認識 ────────
    if suit_crop is not None:
        sy0, sy1, sx0, sx1 = suit_crop
        suit_region = img[sy0:sy1, sx0:sx1]
    else:
        # フォールバック: 比率で切り出す
        suit_start_ratio = 0.45
        suit_end_ratio = 0.80
        try:
            cfg = load_config()
            ratios = cfg.get("capture", {}).get("open_card_ratios", {})
            if ratios:
                suit_start_ratio = ratios.get("suit_start", suit_start_ratio)
                suit_end_ratio = ratios.get("suit_end", suit_end_ratio)
        except Exception:
            pass
        suit_region = region[int(h * suit_start_ratio):int(h * suit_end_ratio), :]

    if suit_region.size == 0:
        suit_region = region

    if debug:
        cv2.imwrite("/tmp/cowboy_suit_region.png", suit_region)

    suit = _estimate_suit_by_color(suit_region, debug=debug, debug_logs=debug_logs)

    msg = f"[DEBUG] rank={rank}  suit={suit}"
    if debug:
        print(msg)
    if debug_logs is not None:
        debug_logs.append(msg)

    return f"{rank}{suit}"


def _generate_suit_templates() -> dict[str, np.ndarray]:
    """判定用の基準テンプレートマスク (32x32) を生成する"""
    templates = {}
    size = 32
    cx, cy = size // 2, size // 2
    
    # 1. ダイヤ (♦)
    img_d = np.zeros((size, size), dtype=np.uint8)
    pts = np.array([[cx, 3], [size-4, cy], [cx, size-4], [3, cy]], np.int32)
    cv2.fillPoly(img_d, [pts], 255)
    templates["D"] = img_d

    # 2. ハート (♥)
    img_h = np.zeros((size, size), dtype=np.uint8)
    # 簡易ハート: 2つの円と逆三角形
    cv2.circle(img_h, (cx - 5, cy - 4), 6, 255, -1)
    cv2.circle(img_h, (cx + 5, cy - 4), 6, 255, -1)
    pts = np.array([[2, cy - 1], [size-3, cy - 1], [cx, size-3]], np.int32)
    cv2.fillPoly(img_h, [pts], 255)
    templates["H"] = img_h

    # 3. スペード (♠)
    img_s = np.zeros((size, size), dtype=np.uint8)
    # 逆ハート + ステム
    cv2.circle(img_s, (cx - 5, cy + 4), 6, 255, -1)
    cv2.circle(img_s, (cx + 5, cy + 4), 6, 255, -1)
    pts = np.array([[2, cy + 1], [size-3, cy + 1], [cx, 4]], np.int32)
    cv2.fillPoly(img_s, [pts], 255)
    # ステム
    cv2.rectangle(img_s, (cx - 2, cy + 2), (cx + 2, size - 3), 255, -1)
    pts_stem = np.array([[cx - 5, size - 3], [cx + 5, size - 3], [cx, cy + 2]], np.int32)
    cv2.fillPoly(img_s, [pts_stem], 255)
    templates["S"] = img_s

    # 4. クラブ (♣)
    img_c = np.zeros((size, size), dtype=np.uint8)
    # 3つの円 + ステム
    cv2.circle(img_c, (cx, cy - 6), 6, 255, -1)
    cv2.circle(img_c, (cx - 6, cy + 1), 6, 255, -1)
    cv2.circle(img_c, (cx + 6, cy + 1), 6, 255, -1)
    # ステム
    cv2.rectangle(img_c, (cx - 2, cy + 1), (cx + 2, size - 3), 255, -1)
    pts_stem = np.array([[cx - 5, size - 3], [cx + 5, size - 3], [cx, cy + 1]], np.int32)
    cv2.fillPoly(img_c, [pts_stem], 255)
    templates["C"] = img_c

    return templates


def _calc_iou(mask1: np.ndarray, mask2: np.ndarray) -> float:
    intersection = np.count_nonzero(cv2.bitwise_and(mask1, mask2))
    union = np.count_nonzero(cv2.bitwise_or(mask1, mask2))
    return intersection / union if union > 0 else 0.0


def _estimate_suit_by_color(card_img: np.ndarray, debug: bool = False, debug_logs: list[str] | None = None) -> str:
    """
    スート記号領域の画像からスート (H/D/S/C) を推定する。
    入力はすでにランク文字を除いたスート記号のみの領域を想定。
    """
    if card_img.size == 0:
        return "S"
    h, w = card_img.shape[:2]

    # ── スート記号領域を二値化 ────────────────────────
    # 判定用に拡大
    min_dim = min(card_img.shape[:2])
    scale = max(2, 120 // min_dim)
    work = cv2.resize(card_img, None, fx=scale, fy=scale, interpolation=cv2.INTER_LANCZOS4)

    # ── 赤/黒を正確に判定 ────────────────────────
    b_ch, g_ch, r_ch = cv2.split(work)
    r_int = r_ch.astype(np.int16)
    g_int = g_ch.astype(np.int16)
    b_int = b_ch.astype(np.int16)
    
    # 拡大された高解像度画像で、赤色を示すピクセル (R - B > 35 かつ R - G > 30) の割合を算出
    red_pixels = ((r_int - b_int) > 35) & ((r_int - g_int) > 30)
    total_pixels = work.shape[0] * work.shape[1]
    is_red = (total_pixels > 0) and (np.count_nonzero(red_pixels) / total_pixels > 0.04)

    if is_red:
        # 赤系: R - B > 40 のピクセルをスート部分として抽出 (元設定)
        b_ch, _, r_ch = cv2.split(work)
        diff = cv2.subtract(r_ch, b_ch)
        _, suit_mask = cv2.threshold(diff, 40, 255, cv2.THRESH_BINARY)
    else:
        # 黒系: グレースケールに変換し、最小・最大輝度の中間値を閾値として動的に決定
        gray_w = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
        min_val, max_val, _, _ = cv2.minMaxLoc(gray_w)
        if max_val - min_val > 20:
            # 中間値 (45%) に設定。暗い状況でも背景の影を除外し、スートのエッジを鮮明に保ちます。
            thresh_val = min_val + (max_val - min_val) * 0.45
        else:
            thresh_val = 105
        _, suit_mask = cv2.threshold(gray_w, thresh_val, 255, cv2.THRESH_BINARY_INV)

    # ── 最大輪郭を取得 ────────────────────────────────
    contours, _ = cv2.findContours(suit_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return "H" if is_red else "S"

    # 面積でフィルタ（ノイズ除去: 全体の2%以上）
    min_area = suit_mask.shape[0] * suit_mask.shape[1] * 0.02
    contours = [c for c in contours if cv2.contourArea(c) >= min_area]
    if not contours:
        return "H" if is_red else "S"

    largest = max(contours, key=cv2.contourArea)

    # ── テンプレートとの輪郭形状マッチング (cv2.matchShapes) ──
    templates = _generate_suit_templates()
    temp_contours = {}
    for key, temp_img in templates.items():
        conts, _ = cv2.findContours(temp_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if conts:
            temp_contours[key] = max(conts, key=cv2.contourArea)
        else:
            temp_contours[key] = None

    # Extent の計算
    x, y, w, h = cv2.boundingRect(largest)
    rect_area = w * h
    contour_area = cv2.contourArea(largest)
    extent = contour_area / rect_area if rect_area > 0 else 0.0

    # 輪郭部分のマスクを切り出して 32x32 にリサイズ
    roi_mask = suit_mask[y:y+h, x:x+w]
    roi_resized = cv2.resize(roi_mask, (32, 32), interpolation=cv2.INTER_NEAREST)

    if is_red:
        score_d = cv2.matchShapes(largest, temp_contours["D"], cv2.CONTOURS_MATCH_I1, 0.0) if temp_contours["D"] is not None else 999.0
        score_h = cv2.matchShapes(largest, temp_contours["H"], cv2.CONTOURS_MATCH_I1, 0.0) if temp_contours["H"] is not None else 999.0
        iou_d = _calc_iou(roi_resized, templates["D"])
        iou_h = _calc_iou(roi_resized, templates["H"])
        
        msg = f"[DEBUG] suit shape match (Red): D={score_d:.4f}, H={score_h:.4f} (extent={extent:.3f}, iou_d={iou_d:.3f}, iou_h={iou_h:.3f})"
        if debug:
            print(msg)
        if debug_logs is not None:
            debug_logs.append(msg)
            
        # ダイヤは幾何学的にひし形（面積が外接矩形の約50%）になるため、占有率が 0.58 を超える場合はハートと判定します
        if extent > 0.58:
            return "H"
        # matchShapes の score_d が極めて低い (< 0.035) = ダイヤテンプレートと高信頼一致
        # → IoU より優先する (IoU は D/H で誤判定する場合がある)
        if score_d < 0.035:
            return "D"
        # score_h が極めて低い (< 0.035) = ハートテンプレートと高信頼一致
        if score_h < 0.035:
            return "H"
        # IoU の一致度が明らかに高い場合 (差が 0.04 以上)、IoU の判定を使用する
        if abs(iou_d - iou_h) >= 0.04:
            return "D" if iou_d > iou_h else "H"
        return "D" if score_d < (score_h - 0.018) else "H"
    else:
        score_s = cv2.matchShapes(largest, temp_contours["S"], cv2.CONTOURS_MATCH_I1, 0.0) if temp_contours["S"] is not None else 999.0
        score_c = cv2.matchShapes(largest, temp_contours["C"], cv2.CONTOURS_MATCH_I1, 0.0) if temp_contours["C"] is not None else 999.0
        iou_s = _calc_iou(roi_resized, templates["S"])
        iou_c = _calc_iou(roi_resized, templates["C"])

        msg = f"[DEBUG] suit shape match (Black): S={score_s:.4f}, C={score_c:.4f} (extent={extent:.3f}, iou_s={iou_s:.3f}, iou_c={iou_c:.3f})"
        if debug:
            print(msg)
        if debug_logs is not None:
            debug_logs.append(msg)

        # ── 判定ロジック ─────────────────────────────────────────
        # matchShapes の score_c が極めて低い (< 0.025) = クラブテンプレートと完全一致
        # → クラブ(♣) と確定。IoU より優先する。
        if score_c < 0.025:
            return "C"

        # score_s が十分低い (≤ 0.09) = スペードテンプレートと良く一致
        # → スペード(♠) と確定。
        if score_s <= 0.09:
            return "S"

        # 両スコアが中途半端な場合は IoU を使う (スペードの diff≈0.039 を拾うため閾値 0.03)
        if abs(iou_s - iou_c) >= 0.03:
            return "S" if iou_s > iou_c else "C"

        return "S" if score_s < score_c else "C"


# ────────────────────────────────────────────────
# EasyOCR ベースの検出関数
# ────────────────────────────────────────────────

def detect_round_number(img: np.ndarray, crop: list[int], debug: bool = False) -> int | None:
    """
    ラウンド番号を読み取る（白テキスト on 赤バー）。
    1. HSV V チャンネル閾値 → Tesseract (高速・主力)
    2. グレースケール閾値  → Tesseract (フォールバック)
    3. EasyOCR + CLAHE    → (最終フォールバック)
    """
    y0, y1, x0, x1 = crop
    region = img[y0:y1, x0:x1]
    if region.size == 0:
        return None

    if debug:
        cv2.imwrite("/tmp/cowboy_round_region.png", region)

    # ── 共通前処理: V チャンネル閾値で白テキストを抽出 ──────────
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    _, v_mask = cv2.threshold(hsv[:, :, 2], 170, 255, cv2.THRESH_BINARY)
    # 4 倍拡大（NEAREST で境界をシャープに保つ）
    large_v = cv2.resize(v_mask, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
    # Tesseract は「黒文字 on 白背景」を期待するため反転
    inv_v = cv2.bitwise_not(large_v)

    # ── 方法1: V マスク + Tesseract PSM 7/8 ─────────────────────
    tess_base = "--oem 3 --psm {psm} -c tessedit_char_whitelist=0123456789"
    for psm in [7, 8]:
        text = pytesseract.image_to_string(inv_v, config=tess_base.format(psm=psm)).strip()
        if debug:
            print(f"[DEBUG] round Tess(V) psm={psm}: {repr(text)}")
        nums = [n for n in re.findall(r"\d+", text) if len(n) == 6]
        if nums:
            return int(nums[0])

    # ── 方法2: グレースケール閾値 + Tesseract ────────────────────
    large_g = cv2.resize(region, None, fx=4, fy=4, interpolation=cv2.INTER_LANCZOS4)
    gray = cv2.cvtColor(large_g, cv2.COLOR_BGR2GRAY)
    _, bright = cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY)
    inv_g = cv2.bitwise_not(bright)
    if debug:
        cv2.imwrite("/tmp/cowboy_round_inv.png", inv_g)
    for psm in [7, 8]:
        text = pytesseract.image_to_string(inv_g, config=tess_base.format(psm=psm)).strip()
        if debug:
            print(f"[DEBUG] round Tess(gray) psm={psm}: {repr(text)}")
        nums = [n for n in re.findall(r"\d+", text) if len(n) == 6]
        if nums:
            return int(nums[0])

    # ── 方法3: EasyOCR + CLAHE (最終フォールバック) ─────────────
    reader = _get_ocr_reader()
    if reader is not None:
        lab = cv2.cvtColor(region, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
        l = clahe.apply(l)
        enhanced = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
        large_enh = cv2.resize(enhanced, None, fx=3, fy=3, interpolation=cv2.INTER_LANCZOS4)
        results = reader.readtext(large_enh, detail=0)
        full_text = " ".join(results)
        if debug:
            print(f"[DEBUG] round EasyOCR: {repr(full_text)}")
        nums = [n for n in re.findall(r"\d+", full_text) if len(n) == 6]
        if nums:
            return int(nums[0])

    return None


def detect_timer(img: np.ndarray, crop: list[int], debug: bool = False) -> int | None:
    """
    タイマー（カウントダウン残り秒数）を読み取る。
    1. HSV V/S チャンネル閾値などで二値化してTesseract
    2. EasyOCR
    """
    y0, y1, x0, x1 = crop
    region = img[y0:y1, x0:x1]
    if region.size == 0:
        return None

    if debug:
        cv2.imwrite("/tmp/cowboy_timer_region.png", region)

    # 前処理: 高解像度化とグレースケール変換
    large = cv2.resize(region, None, fx=4, fy=4, interpolation=cv2.INTER_LANCZOS4)
    gray = cv2.cvtColor(large, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
    inv = cv2.bitwise_not(thresh)
    if debug:
        cv2.imwrite("/tmp/cowboy_timer_inv.png", inv)

    tess_base = "--oem 3 --psm {psm} -c tessedit_char_whitelist=0123456789Ss"
    for psm in [7, 8, 13]:
        text = pytesseract.image_to_string(inv, config=tess_base.format(psm=psm)).strip()
        if debug:
            print(f"[DEBUG] timer Tess(inv) psm={psm}: {repr(text)}")
        m = re.search(r"(\d+)\s*[Ss]", text)
        if m:
            val = int(m.group(1))
            if 0 <= val <= 15:
                return val

    # フォールバック: EasyOCR
    reader = _get_ocr_reader()
    if reader is not None:
        results = reader.readtext(large, detail=0)
        full_text = "".join(results)
        if debug:
            print(f"[DEBUG] timer EasyOCR: {repr(full_text)}")
        m = re.search(r"(\d+)\s*[Ss]", full_text)
        if m:
            val = int(m.group(1))
            if 0 <= val <= 15:
                return val

    return None


# ────────────────────────────────────────────────
# 全11ポジション ベット額検出
# ────────────────────────────────────────────────

# 11ポジションのキー（config.yml の bet_crops と一致させる）
ALL_BET_KEYS = [
    "cowboy", "draw", "bull",
    "any_flash", "any_pair", "any_ace",
    "win_high", "win_two", "win_sf", "win_fh", "win_four",
]
# 8つのサブポジション WIN フラグのキー
ALL_WIN_KEYS = [
    "any_flash", "any_pair", "any_ace",
    "win_high", "win_two", "win_sf", "win_fh", "win_four",
]

WIN_BRIGHTNESS_THRESHOLD = 0.30


def detect_jackpot_stock(img: np.ndarray, crop: list[int], debug: bool = False) -> int | None:
    """ジャックポットストックコインの数値（例: 447744）を Tesseract で読み取る。"""
    y0, y1, x0, x1 = crop
    region = img[y0:y1, x0:x1]
    if region.size == 0:
        return None

    large = cv2.resize(region, None, fx=3, fy=3, interpolation=cv2.INTER_LANCZOS4)
    gray = cv2.cvtColor(large, cv2.COLOR_BGR2GRAY)
    # ゴールドテキストは明るい → 輝度閾値で抽出してから反転
    _, thresh = cv2.threshold(gray, 140, 255, cv2.THRESH_BINARY)
    inv = cv2.bitwise_not(thresh)

    config = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789,"
    text = pytesseract.image_to_string(inv, config=config).strip()
    if debug:
        print(f"[DEBUG] jackpot_stock tess: {repr(text)}")

    cleaned = re.sub(r"[^\d]", "", text)
    if len(cleaned) >= 3:
        return int(cleaned)
    return None


def _parse_amount(text: str) -> int | None:
    """'5.5K' → 5500, '1.3K' → 1300, '9.55K' → 9550 (OCR誤字も補正)"""
    # OCR誤読を部分補正: S→5, O→0, o→0, l→1, I→1
    cleaned = (text.strip()
               .replace("S", "5").replace("O", "0").replace("o", "0")
               .replace("l", "1").replace("I", "1"))
    m = re.search(r"(\d+\.?\d*)\s*([KkMm]?)", cleaned)
    if not m:
        return None
    val = float(m.group(1))
    suffix = m.group(2).upper()
    if suffix == "K":
        return int(val * 1_000)
    if suffix == "M":
        return int(val * 1_000_000)
    # Kサフィックスなしの場合: 100未満はOCRミス（"5K"の"K"を読み落とした等）とみなす
    # 上限チェック: ベット額は現実的に 10M 未満のはず（ジャックポット等の誤読を除外）
    raw = int(val)
    if raw < 100 or raw >= 10_000_000:
        return None
    return raw


def detect_all_bets(
    img: np.ndarray,
    bet_crops: dict[str, list[int]],
    debug: bool = False,
) -> dict[str, int | None]:
    """全11ポジションのベット額を EasyOCR で読み取る。
    ラベルは各ボックス左上の白い丸バッジ内に表示される。
    """
    reader = _get_ocr_reader()
    amounts: dict[str, int | None] = {k: None for k in ALL_BET_KEYS}
    if reader is None:
        return amounts

    for key, (y0, y1, x0, x1) in bet_crops.items():
        if key not in ALL_BET_KEYS:
            continue
        region = img[y0:y1, x0:x1]
        if region.size == 0:
            continue
        # 2倍拡大して OCR精度向上
        large = cv2.resize(region, None, fx=2, fy=2, interpolation=cv2.INTER_LANCZOS4)
        results = reader.readtext(large, detail=0)
        for text in results:
            val = _parse_amount(text)
            if val is not None and val > 0:
                amounts[key] = val
                break
        if debug:
            print(f"[DEBUG] bet[{key}]: {results} → {amounts[key]}")
    return amounts


def detect_sub_wins(
    img: np.ndarray,
    win_regions: dict[str, list[int]],
    debug: bool = False,
) -> dict[str, bool]:
    """8つのサブポジションの WIN フラグを輝度判定で検出する"""
    flags: dict[str, bool] = {k: False for k in ALL_WIN_KEYS}
    for key, (y0, y1, x0, x1) in win_regions.items():
        if key not in ALL_WIN_KEYS:
            continue
        sec = img[y0:y1, x0:x1]
        if sec.size == 0:
            continue
        hsv = cv2.cvtColor(sec, cv2.COLOR_BGR2HSV)
        ratio = float(np.count_nonzero(hsv[:, :, 2] > 220)) / (sec.shape[0] * sec.shape[1])
        flags[key] = ratio >= WIN_BRIGHTNESS_THRESHOLD
        if debug:
            print(f"[DEBUG] win_region[{key}]: bright={ratio:.3f} → {flags[key]}")
    return flags


# ────────────────────────────────────────────────
# API クライアント
# ────────────────────────────────────────────────

def login(client: httpx.Client, base_url: str, username: str, password: str) -> str:
    resp = client.post(
        f"{base_url}/api/v1/auth/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def post_game(client: httpx.Client, base_url: str, token: str, data: dict) -> dict:
    resp = client.post(
        f"{base_url}/api/v1/games",
        json=data,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_recent_games(client: httpx.Client, base_url: str, token: str, limit: int = 50) -> list[dict]:
    """直近ゲーム履歴を取得する。タイムアウト 2秒。失敗時は空リストを返す。"""
    try:
        resp = client.get(
            f"{base_url}/api/v1/games",
            params={"limit": limit, "offset": 0},
            headers={"Authorization": f"Bearer {token}"},
            timeout=2.0,
        )
        resp.raise_for_status()
        return resp.json().get("games", [])
    except Exception as e:
        print(f"[WARN] 直近ゲーム取得失敗: {e}", file=sys.stderr)
        return []


def post_capture_preview(client: httpx.Client, base_url: str, token: str, preview: dict) -> None:
    resp = client.post(
        f"{base_url}/api/v1/capture/preview",
        json=preview,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    resp.raise_for_status()


# ────────────────────────────────────────────────
# メインループ（タイマーベース ステートマシン）
# ────────────────────────────────────────────────

def run(cfg: dict, once: bool = False, debug: bool = False) -> None:
    device      = cfg["adb"]["device"]
    base_url    = cfg["api"]["base_url"]
    username    = cfg["api"]["username"]
    password    = cfg["api"]["password"]
    cap         = cfg["capture"]
    timing      = cfg["timing"]

    post_round_cooldown = float(timing["post_round_cooldown"])   # デフォルト 18s
    poll_fast           = float(timing["poll_fast"])             # デフォルト 1s
    poll_idle           = float(timing["poll_idle"])             # デフォルト 3s
    result_stable_count = int(timing["result_stable_count"])     # デフォルト 2
    result_timeout      = float(timing["result_timeout"])        # デフォルト 25s
    result_check_delay  = float(timing.get("result_check_delay", 12.0))  # デフォルト 12s

    # ハング検出設定
    hang_detect_cfg = cfg.get("hang_detect", {})
    hang_threshold  = int(hang_detect_cfg.get("threshold", 5))
    hang_timeout    = float(hang_detect_cfg.get("timeout_seconds", 10.0))

    if not username or not password:
        print(
            "[ERROR] username/password が設定されていません。"
            "config.yml か環境変数 CAPTURE_USERNAME / CAPTURE_PASSWORD を設定してください。",
            file=sys.stderr,
        )
        sys.exit(1)

    capturer = LogCapturer()
    sys.stdout = capturer
    atexit.register(lambda: setattr(sys, "stdout", capturer.original_stdout))

    # 起動時に既存 of error_*.log をクリーンアップ
    log_dir = Path("/app/logs")
    if log_dir.exists():
        for f in log_dir.glob("error_*.log"):
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass

    with httpx.Client() as client:
        # API 起動待ち
        for attempt in range(30):
            try:
                token = login(client, base_url, username, password)
                print(f"[INFO] ログイン成功: {base_url}")
                break
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                if attempt < 29:
                    print(f"[INFO] API 接続待ち ({attempt + 1}/30): {e}", file=sys.stderr)
                    time.sleep(5)
                else:
                    print(f"[ERROR] API に接続できませんでした: {e}", file=sys.stderr)
                    sys.exit(1)

        token_refreshed_at = time.time()

        # ── ステートマシン初期値 ──────────────────────────────
        state               = State.PREPARING
        watching_start      = time.time()   # タイムアウト計測用
        cooldown_start      = 0.0           # COOLDOWN に入った時刻
        result_streak       = 0             # 同一結果の連続検出回数
        last_streak_result  = None          # 連続検出中の結果値
        latest_open_card    = None          # 最後に読み取ったオープンカード
        latest_round_number: int | None = None   # 最後に読み取ったラウンド番号
        last_read_rn: int | None = None          # 直前に読み取った生ラウンド番号（ノイズ検証用）
        rn_streak           = 0             # 生ラウンド番号の一致連続回数
        last_confirmed_round: int | None = None  # 最後に正常終了/確定したラウンド番号
        last_confirmed_time: float = 0.0         # 最後に確定した時刻
        open_detected_at: str | None = None      # オープンカード初回検出時刻
        result_detected_at: str | None = None    # 結果確定時刻
        # ベット額キャッシュ: WATCHING 中に継続更新し、POST 時に使用
        # （WIN バッジのアニメーションでラベルが隠れる前に読み取る）
        cached_bets: dict[str, int | None] = {k: None for k in ALL_BET_KEYS}
        bet_last_updated    = 0.0           # EasyOCR 最終実行時刻（間引き用）
        BET_OCR_INTERVAL    = 3.0           # EasyOCR 実行間隔（秒）
        cached_jackpot_stock: int | None = None  # ジャックポットストックコイン
        cached_card_image: np.ndarray | None = None  # 初回/更新時に切り出したオープンカード画像
        cached_prediction: dict | None = None         # ML予測キャッシュ
        cached_side_bet_pred: dict | None = None      # サイドベット予測キャッシュ
        bet_scanned_this_round = False
        round_number_scanned_this_round = False
        preview_last_sent   = 0.0           # プレビュー最終送信時刻
        PREVIEW_INTERVAL    = 3.0           # プレビュー送信間隔（秒）—重いクロップ画像の間引き
        send_preview_now    = False         # 即時送信フラグ（カードオープン直後等）
        latest_timer_value: int | None = None  # 最新のタイマー検出値
        timer_active_last_seen = 0.0           # タイマーが有効だった最終時刻
        timer_active_value = 0                 # タイマーが有効だった時の値
        countdown_end_time = 0.0               # 結果チェック可能になる目標時刻
        result_phase_timer_streak = 0          # RESULT フェーズ中のタイマー連続検出回数
        last_result_phase_timer_value: int | None = None  # RESULT フェーズ中の連続タイマー値
        result_entered_at: float = 0.0        # RESULT フェーズに入った時刻（次ラウンド開始判定用）
        cached_result_image: np.ndarray | None = None  # 初回結果検出時のフレームキャッシュ

        ocr_debug_list: list[str] = []      # OCR詳細デバッグログ
        log_file_name: str | None = None    # ログファイル名
        capturer.reset()                    # ログバッファ初期化
        hang_detector = FrameHangDetector(threshold=hang_threshold, timeout_seconds=hang_timeout)  # フレームハング検出
 
        print(f"[INFO] ステートマシン開始: state={state.value}")
        print(f"[INFO] タイミング設定: cooldown={post_round_cooldown}s  "
              f"poll_fast={poll_fast}s  stable_count={result_stable_count}  "
              f"timeout={result_timeout}s")
        print(f"[INFO] ハング検出設定: threshold={hang_threshold}フレーム  "
              f"timeout_window={hang_timeout}s")
 
        while True:
            # ── JWT 24時間で再取得 ────────────────────────────
            if time.time() - token_refreshed_at > 23 * 3600:
                for retry in range(3):
                    try:
                        token = login(client, base_url, username, password)
                        token_refreshed_at = time.time()
                        print("[INFO] トークン再取得")
                        break
                    except (httpx.RequestError, httpx.HTTPStatusError) as e:
                        print(f"[WARN] トークン再取得失敗 ({retry + 1}/3): {e}", file=sys.stderr)
                        if retry < 2:
                            time.sleep(2 ** retry)
 
            now = time.time()
 
            # ════════════════════════════════════════════════
            # COOLDOWN: 次ラウンド開始まで待つ
            # ════════════════════════════════════════════════
            if state == State.COOLDOWN:
                elapsed = now - cooldown_start
                remaining = post_round_cooldown - elapsed
                if remaining > 0:
                    if debug:
                        print(f"[DEBUG] COOLDOWN 残り {remaining:.1f}s")
                    time.sleep(min(poll_idle, remaining))
                    if once:
                        break
                    continue
 
                # クールダウン終了 → PREPARING へ
                state = State.PREPARING
                watching_start = time.time()
                result_streak = 0
                last_streak_result = None
                latest_open_card = None
                latest_round_number = None
                open_detected_at = None
                result_detected_at = None
                cached_bets = {k: None for k in ALL_BET_KEYS}
                bet_last_updated = 0.0
                cached_card_image = None
                cached_prediction = None
                cached_side_bet_pred = None
                recent_games_cache = None
                bet_scanned_this_round = False
                round_number_scanned_this_round = False
                send_preview_now = True  # フロントの古いカード画像を即時クリアするため即時送信
                ocr_debug_list.clear()
                log_file_name = None
                capturer.reset()
                timer_active_last_seen = 0.0
                timer_active_value = 0
                countdown_end_time = 0.0
                result_phase_timer_streak = 0
                last_result_phase_timer_value = None
                result_entered_at = 0.0
                hang_detector.reset()  # フレームハング検出器をリセット
                print(f"[INFO] クールダウン終了 → PREPARING")
                if once:
                    break
                continue

            # ════════════════════════════════════════════════
            # PREPARING / BETTING / RESULT: スクリーンショットを取得して解析
            # ════════════════════════════════════════════════
            img = take_screenshot(device)
            if img is None:
                print("[WARN] スクリーンショット取得失敗。再試行します...")
                time.sleep(poll_fast)
                if once:
                    break
                continue

            # ── フレームハング検出（同じ画像が連続して返されていないか） ──
            if hang_detector.check(img, now):
                print(
                    f"[WARN] フレームハングを検出しました。"
                    "画面が固まっているか、ADB接続が不安定である可能性があります。"
                )
                log_file_name = save_round_log(capturer, latest_round_number)
                
                # ハング検出時はエラーPOST
                if latest_open_card is not None or latest_round_number is not None:
                    error_payload = {
                        "open_card": latest_open_card,
                        "result": "error",
                        "cowboy_hand": None,
                        "bull_hand": None,
                        "round_number": latest_round_number,
                        "jackpot_stock": cached_jackpot_stock,
                        "bet_cowboy":    cached_bets.get("cowboy"),
                        "bet_draw":      cached_bets.get("draw"),
                        "bet_bull":      cached_bets.get("bull"),
                        "bet_any_flash": cached_bets.get("any_flash"),
                        "bet_any_pair":  cached_bets.get("any_pair"),
                        "bet_any_ace":   cached_bets.get("any_ace"),
                        "bet_win_high":  cached_bets.get("win_high"),
                        "bet_win_two":   cached_bets.get("win_two"),
                        "bet_win_sf":    cached_bets.get("win_sf"),
                        "bet_win_fh":    cached_bets.get("win_fh"),
                        "bet_win_four":  cached_bets.get("win_four"),
                        "card_image":    encode_crop(img, cap["open_card_crop"], scale=4) if latest_open_card else None,
                        "ocr_debug":     "\n".join(ocr_debug_list) if ocr_debug_list else None,
                        "log_file_name": log_file_name,
                    }
                    try:
                        post_game(client, base_url, token, error_payload)
                        print(f"[INFO] フレームハング検出のエラー POST に成功しました。")
                    except Exception as e:
                        print(f"[ERROR] フレームハング検出のエラー POST に失敗: {e}", file=sys.stderr)
                    
                    if latest_round_number is not None:
                        last_confirmed_round = latest_round_number
                        last_confirmed_time = time.time()
                
                # COOLDOWN に入る
                state = State.COOLDOWN
                cooldown_start = now
                print(f"[INFO] クールダウンに入ります ({post_round_cooldown}秒)")
                if once:
                    break
                continue

            # ── カード裏面（緑）の判定と解析 ──
            is_green = is_card_back_green(img, cap["open_card_crop"])

            # ── タイマー検出 ──
            # RESULT 状態中はタイマー OCR をスキップ（EasyOCR が重くポーリングを阻害するため）
            # 次ラウンド開始の判定は result=None 後の経過時間で行う
            timer_value = None
            if "timer_crop" in cap and state != State.RESULT:
                timer_value = detect_timer(img, cap["timer_crop"], debug=debug)
                if timer_value is not None:
                    if timer_value != latest_timer_value:
                        print(f"[INFO] タイマー検出: {timer_value}s")
                    if 1 <= timer_value <= 15:
                        timer_active_last_seen = now
                        timer_active_value = timer_value
                latest_timer_value = timer_value

            card = None
            # BETTING 状態でカードが既に確定している場合は OCR スキップ（高速化）
            need_card_ocr = not is_green and (state == State.PREPARING or latest_open_card is None)
            if need_card_ocr:
                card = detect_open_card(
                    img,
                    cap.get("open_card_crop"),
                    cap.get("open_card_rank_crop"),
                    cap.get("open_card_suit_crop"),
                    cap.get("scale", 4),
                    debug=debug,
                    debug_logs=ocr_debug_list,
                )

            # ── 結果検出 ──
            can_check_result = False
            if state == State.BETTING or state == State.RESULT:
                if state == State.BETTING and timer_value is not None and timer_value > 0:
                    # タイマーが残り時間を明示している → 結果表示前
                    if debug:
                        print(f"[DEBUG] 結果チェックスキップ (タイマー残り {timer_value}s)")
                elif timer_value == 0:
                    if now >= countdown_end_time + 0.5:
                        can_check_result = True
                    else:
                        if debug:
                            print(f"[DEBUG] 結果チェックスキップ (timer=0, WIN表示待ち: 残り {countdown_end_time + 0.5 - now:.1f}s)")
                elif countdown_end_time > 0.0:
                    if now >= countdown_end_time + 0.5:
                        can_check_result = True
                    else:
                        if debug:
                            print(f"[DEBUG] 結果チェックスキップ (カウントダウン中: 残り {countdown_end_time + 0.5 - now:.1f}s)")
                else:
                    elapsed_in_betting = now - watching_start if state == State.BETTING else 999.0
                    if elapsed_in_betting >= result_check_delay:
                        can_check_result = True
                    else:
                        if debug:
                            print(f"[DEBUG] 結果チェックスキップ (経過時間不足: {elapsed_in_betting:.1f}s < {result_check_delay}s)")

            if can_check_result:
                result = detect_result(img, cap["result_crop"], debug=debug)
            else:
                result = None

            # ── ステート遷移ロジック ──
            if state == State.PREPARING:
                # 優先: タイマー検出による移行
                if timer_value is not None and 1 <= timer_value <= 15:
                    state = State.BETTING
                    open_detected_at = datetime.now(UTC).isoformat()
                    watching_start = now
                    countdown_end_time = now + timer_value
                    print(f"[INFO] タイマー検出によるBETTING移行: timer={timer_value}s (結果予定: +{timer_value:.1f}s) at={open_detected_at}")
                    
                    y0, y1, x0, x1 = cap["open_card_crop"]
                    region = img[y0:y1, x0:x1]
                    if region.size > 0:
                        large_reg = cv2.resize(region, None, fx=4, fy=4, interpolation=cv2.INTER_LANCZOS4)
                        cached_card_image = enhance_card_image(large_reg)
                    send_preview_now = True
                    if card:
                        latest_open_card = card
                        print(f"[INFO] オープンカード初回検出: {card}")
                        if _prediction_model is not None or _side_bet_models is not None:
                            try:
                                recent = fetch_recent_games(client, base_url, token, limit=50)
                                recent_games_cache = recent
                                if _prediction_model is not None:
                                    cached_prediction = ml_predict(_prediction_model, card, recent, cached_jackpot_stock)
                                    print(f"[INFO] 予測: {cached_prediction}")
                                if _side_bet_models is not None:
                                    cached_side_bet_pred = predict_side_bets(_side_bet_models, card, recent, cached_jackpot_stock)
                                    print(f"[INFO] サイドベット予測: {cached_side_bet_pred}")
                            except Exception as e:
                                print(f"[WARN] 予測失敗: {e}", file=sys.stderr)
                # フォールバック: カードオープン検知（タイマーOCRが失敗し、緑でなくなった場合）
                elif not is_green:
                    state = State.BETTING
                    open_detected_at = datetime.now(UTC).isoformat()
                    watching_start = now
                    countdown_end_time = now + 15.0
                    print(f"[INFO] カードオープン検知によるフォールバックBETTING移行 (結果予定: +15.0s) at={open_detected_at}")
                    
                    y0, y1, x0, x1 = cap["open_card_crop"]
                    region = img[y0:y1, x0:x1]
                    if region.size > 0:
                        large_reg = cv2.resize(region, None, fx=4, fy=4, interpolation=cv2.INTER_LANCZOS4)
                        cached_card_image = enhance_card_image(large_reg)
                    send_preview_now = True
                    if card:
                        latest_open_card = card
                        print(f"[INFO] オープンカード初回検出: {card}")

            elif state == State.BETTING:
                # タイマー値が検出されたら、目標時刻を補正・更新する
                if timer_value is not None and 1 <= timer_value <= 15:
                    new_end_time = now + timer_value
                    if abs(new_end_time - countdown_end_time) > 1.0:
                        print(f"[INFO] countdown_end_time を補正: {countdown_end_time - now:.1f}s -> {timer_value:.1f}s")
                    countdown_end_time = new_end_time

                if card:
                    if latest_open_card is None:
                        open_detected_at = datetime.now(UTC).isoformat()
                        print(f"[INFO] オープンカード初回検出: {card}  at={open_detected_at}")
                        y0, y1, x0, x1 = cap["open_card_crop"]
                        region = img[y0:y1, x0:x1]
                        if region.size > 0:
                            large_reg = cv2.resize(region, None, fx=4, fy=4, interpolation=cv2.INTER_LANCZOS4)
                            cached_card_image = enhance_card_image(large_reg)
                        # ML予測（初回確定時のみ）
                        if _prediction_model is not None or _side_bet_models is not None:
                            try:
                                recent = fetch_recent_games(client, base_url, token, limit=50)
                                recent_games_cache = recent
                                if _prediction_model is not None:
                                    cached_prediction = ml_predict(_prediction_model, card, recent, cached_jackpot_stock)
                                    print(f"[INFO] 予測: {cached_prediction}")
                                if _side_bet_models is not None:
                                    cached_side_bet_pred = predict_side_bets(_side_bet_models, card, recent, cached_jackpot_stock)
                            except Exception as e:
                                print(f"[WARN] 予測失敗: {e}", file=sys.stderr)
                        send_preview_now = True
                    elif card != latest_open_card:
                        print(f"[INFO] オープンカード更新: {latest_open_card} → {card}")
                        y0, y1, x0, x1 = cap["open_card_crop"]
                        region = img[y0:y1, x0:x1]
                        if region.size > 0:
                            large_reg = cv2.resize(region, None, fx=4, fy=4, interpolation=cv2.INTER_LANCZOS4)
                            cached_card_image = enhance_card_image(large_reg)
                    latest_open_card = card

                if result is not None:
                    state = State.RESULT
                    result_detected_at = datetime.now(UTC).isoformat()
                    result_entered_at = now
                    print(f"[INFO] 結果表示を検出 (BETTING → RESULT): result={result}  at={result_detected_at}")
                    result_streak = 1
                    last_streak_result = result
                    result_phase_timer_streak = 0
                    cached_result_image = img.copy()  # 初回検出フレームを保存
                    send_preview_now = True  # 結果検出直後は即時プレビュー送信

            elif state == State.RESULT:
                elapsed_in_result = now - result_entered_at
                # 結果表示フェーズ中のタイマー誤検出に対するエラーハンドリング
                if timer_value is not None and 1 <= timer_value <= 15:
                    if elapsed_in_result >= 2.0:
                        # 結果確定後2秒以上経過してタイマーを検出 → 次ラウンドが開始された
                        # 1回しか検出できていない場合は誤検知の可能性があるため error 扱い
                        if result_streak < 2:
                            print(
                                f"[WARN] RESULT中にタイマー検出 ({timer_value}s, 経過:{elapsed_in_result:.1f}s): "
                                f"result_streak={result_streak} (未確認) のため error として処理します。"
                            )
                            result = "error"
                            last_streak_result = "error"
                        else:
                            print(
                                f"[INFO] RESULT中にタイマー検出 ({timer_value}s, 経過:{elapsed_in_result:.1f}s): "
                                f"次ラウンド開始と判断。result={last_streak_result} で確定します。"
                            )
                            result = last_streak_result
                        result_streak = result_stable_count
                    else:
                        # 入ってすぐタイマー検出 → OCR誤認識の可能性
                        if timer_value == last_result_phase_timer_value:
                            result_phase_timer_streak += 1
                        else:
                            result_phase_timer_streak = 1
                            last_result_phase_timer_value = timer_value
                        print(
                            f"[WARN] 結果表示フェーズ中にタイマー残り時間 {timer_value}s を検出 "
                            f"(経過:{elapsed_in_result:.1f}s, {result_phase_timer_streak}/2)。OCR誤読の可能性があります。"
                        )
                        if result_phase_timer_streak >= 2:
                            print("[WARN] タイマー連続検出により結果を強制的に 'error' として処理します。")
                            result = "error"
                            result_streak = result_stable_count
                            last_streak_result = "error"
                elif result is None:
                    if elapsed_in_result >= 2.0:
                        # 結果が消失したが2秒以上経過している場合は、次ラウンド開始と判断して結果を確定する
                        print(
                            f"[INFO] RESULT中に結果消失 (経過:{elapsed_in_result:.1f}s): "
                            f"次ラウンド開始と判断。result={last_streak_result} で確定します。"
                        )
                        result = last_streak_result
                        result_streak = result_stable_count
                    else:
                        # 入ってすぐ消失 → 誤認識として BETTING に戻す
                        print("[WARN] 結果表示が消失しました。BETTING に戻ります。")
                        state = State.BETTING
                        result_streak = 0
                        last_streak_result = None
                        result_phase_timer_streak = 0
                        last_result_phase_timer_value = None
                else:
                    result_phase_timer_streak = 0
                    last_result_phase_timer_value = None
                    if result == last_streak_result:
                        result_streak += 1
                    else:
                        result_streak = 1
                        last_streak_result = result
                    print(f"[INFO] 結果検出中 ({result_streak}/{result_stable_count}): result={result}")

            # ベット額: カウントダウン終了の 6 秒前にスキャン（余裕を持ってフロントへ反映するため）
            if state == State.BETTING and "bet_crops" in cap:
                if (countdown_end_time - now <= 6.0) and not bet_scanned_this_round:
                    new_bets = detect_all_bets(img, cap["bet_crops"], debug=debug)
                    for k, v in new_bets.items():
                        if v is not None:
                            cached_bets[k] = v
                    bet_scanned_this_round = True
                    # ベット確定後に予測を再計算（ベット比率を特徴量として使用）
                    if latest_open_card and (_prediction_model is not None or _side_bet_models is not None):
                        try:
                            # ラウンド内でキャッシュ済みの recent_games を再利用（API呼び出し節約）
                            recent = recent_games_cache if recent_games_cache is not None \
                                else fetch_recent_games(client, base_url, token, limit=50)
                            bets_for_pred = {"cowboy": cached_bets.get("cowboy"), "bull": cached_bets.get("bull")}
                            if _prediction_model is not None:
                                cached_prediction = ml_predict(
                                    _prediction_model, latest_open_card, recent,
                                    cached_jackpot_stock, current_bets=bets_for_pred
                                )
                                print(f"[INFO] ベット確定後予測更新: {cached_prediction}")
                            if _side_bet_models is not None:
                                cached_side_bet_pred = predict_side_bets(
                                    _side_bet_models, latest_open_card, recent,
                                    cached_jackpot_stock, current_bets=bets_for_pred
                                )
                        except Exception as e:
                            print(f"[WARN] ベット確定後予測更新失敗: {e}", file=sys.stderr)
                    send_preview_now = True  # ベット確定後の更新予測を即時フロントへ送信

            # ── 結果未検出中のみ実行（EasyOCR 系・アニメーション競合回避）────
            if state != State.RESULT:
                # ラウンド番号: 継続取得してキャッシュ（結果画面では非表示の場合がある）
                if "round_crop" in cap and not round_number_scanned_this_round:
                    rn = detect_round_number(img, cap["round_crop"], debug=debug)
                    if rn is not None:
                        # 2回連続で同一の番号が取得できたら確定値として扱う（OCRの一時的な読み違い・揺れ対策）
                        if rn == last_read_rn:
                            rn_streak += 1
                        else:
                            last_read_rn = rn
                            rn_streak = 1

                        if rn_streak >= 2:
                            # 前回確定したラウンド番号と比較し、矛盾（減少または急増）があれば自動補正
                            # 前ラウンド確定から28秒以内はインクリメント(+1)のみ許容する（OCR誤読による+2ジャンプ対策）
                            if last_confirmed_round is not None and (time.time() - last_confirmed_time < 60):
                                elapsed_since_confirmed = time.time() - last_confirmed_time
                                max_jump = 1 if elapsed_since_confirmed < 28 else 3
                                if rn <= last_confirmed_round or rn > last_confirmed_round + max_jump:
                                    corrected_rn = last_confirmed_round + 1
                                    print(f"[WARN] ラウンド番号の誤検知を判定 (OCR: {rn}, 前回確定: {last_confirmed_round}, 経過: {elapsed_since_confirmed:.1f}s, 許容: +{max_jump})。{corrected_rn} に補正します。")
                                    rn = corrected_rn

                            if rn != latest_round_number:
                                print(f"[INFO] ラウンド番号更新 (確定): {latest_round_number} → {rn}")
                                
                                # BETTING 中にラウンド番号が次の番号に変わってしまった場合
                                # = 前のラウンドの結果画面判定を見落としたまま、新しいラウンドが始まったことを意味する
                                # ただし latest_round_number == last_confirmed_round の場合は既にエラーPOST済みのためスキップ
                                if state == State.BETTING and latest_round_number is not None and latest_round_number != last_confirmed_round:
                                    print(
                                        f"[WARN] 結果を検出できないままラウンド番号が更新されました ({latest_round_number} → {rn})。 "
                                        "前ラウンドをエラーとしてPOSTおよびログ保存し、新ラウンドを開始します。"
                                    )
                                    log_file_name = save_round_log(capturer, latest_round_number)
                                    
                                    # 前ラウンドのエラーPOST
                                    error_payload = {
                                        "open_card": latest_open_card,
                                        "result": "error",
                                        "cowboy_hand": None,
                                        "bull_hand": None,
                                        "round_number": latest_round_number,
                                        "jackpot_stock": cached_jackpot_stock,
                                        "bet_cowboy":    cached_bets.get("cowboy"),
                                        "bet_draw":      cached_bets.get("draw"),
                                        "bet_bull":      cached_bets.get("bull"),
                                        "bet_any_flash": cached_bets.get("any_flash"),
                                        "bet_any_pair":  cached_bets.get("any_pair"),
                                        "bet_any_ace":   cached_bets.get("any_ace"),
                                        "bet_win_high":  cached_bets.get("win_high"),
                                        "bet_win_two":   cached_bets.get("win_two"),
                                        "bet_win_sf":    cached_bets.get("win_sf"),
                                        "bet_win_fh":    cached_bets.get("win_fh"),
                                        "bet_win_four":  cached_bets.get("win_four"),
                                        "card_image":    encode_crop(img, cap["open_card_crop"], scale=4) if latest_open_card else None,
                                        "ocr_debug":     "\n".join(ocr_debug_list) if ocr_debug_list else None,
                                        "log_file_name": log_file_name,
                                    }
                                    try:
                                        post_game(client, base_url, token, error_payload)
                                        print(f"[INFO] 前ラウンド ({latest_round_number}) のエラー POST に成功しました。")
                                    except Exception as e:
                                        print(f"[ERROR] 前ラウンドのエラー POST に失敗しました: {e}", file=sys.stderr)

                                    # エラーPOSTでも last_confirmed_round を更新して次ラウンドの補正を有効にする
                                    last_confirmed_round = latest_round_number
                                    last_confirmed_time = time.time()

                                    # 新しいラウンドのカード検出に備えて、オープンカード状態などをリセット
                                    latest_open_card = None
                                    cached_prediction = None
                                    cached_side_bet_pred = None
                                    cached_bets = {k: None for k in ALL_BET_KEYS}
                                    bet_scanned_this_round = False
                                    round_number_scanned_this_round = False
                                    result_streak = 0
                                    last_streak_result = None
                                    ocr_debug_list.clear()
                                    log_file_name = None
                                    capturer.reset()

                                latest_round_number = rn
                                # 新ラウンド検出されたのでタイムアウト計測の基準時刻をリセット
                                if state == State.BETTING:
                                    print("[INFO] ラウンド番号変化を検知 → watching_start をリセット")
                                    watching_start = time.time()
                            
                            round_number_scanned_this_round = True

            # 結果領域の3分割輝度スコア
            result_scores: dict[str, float] = {}
            if "result_crop" in cap:
                y0r, y1r, x0r, x1r = cap["result_crop"]
                reg = img[y0r:y1r, x0r:x1r]
                if reg.size > 0:
                    rw = reg.shape[1]; th = rw // 3
                    for name, sec in {"cowboy": reg[:, :th], "draw": reg[:, th:2*th], "bull": reg[:, 2*th:]}.items():
                        hsv = cv2.cvtColor(sec, cv2.COLOR_BGR2HSV)
                        result_scores[name] = round(float(np.count_nonzero(hsv[:, :, 2] > 220)) / (sec.shape[0] * sec.shape[1]), 3)

            # WIN 領域のリアルタイム輝度スコア
            win_scores: dict[str, float] = {}
            for key, (y0w, y1w, x0w, x1w) in cap.get("win_regions", {}).items():
                sec = img[y0w:y1w, x0w:x1w]
                if sec.size > 0:
                    hsv = cv2.cvtColor(sec, cv2.COLOR_BGR2HSV)
                    win_scores[key] = round(float(np.count_nonzero(hsv[:, :, 2] > 220)) / (sec.shape[0] * sec.shape[1]), 3)

            # WIN 勝利ハンド行の輝度スコア（各行 WIN 判定用）
            winning_hand_scores: list[float] = []
            for y0w, y1w, x0w, x1w in cap.get("winning_hand_rows", []):
                sec = img[y0w:y1w, x0w:x1w]
                if sec.size > 0:
                    hsv = cv2.cvtColor(sec, cv2.COLOR_BGR2HSV)
                    score = float(np.count_nonzero(hsv[:, :, 2] > 220)) / (sec.shape[0] * sec.shape[1])
                    winning_hand_scores.append(round(score, 3))
                else:
                    winning_hand_scores.append(0.0)

            # ジャックポットストックコイン
            if "jackpot_stock_crop" in cap:
                val = detect_jackpot_stock(img, cap["jackpot_stock_crop"], debug=debug)
                if val is not None:
                    cached_jackpot_stock = val

            # ── プレビュー送信（間引き: 3秒ごと、またはカードオープン直後）──
            now_preview = time.time()
            if send_preview_now or (now_preview - preview_last_sent >= PREVIEW_INTERVAL):
                send_preview_now = False
                thumb = cv2.resize(img, (img.shape[1] // 3, img.shape[0] // 3))
                preview_payload = {
                    "state": state.value,
                    "open_detected_at": open_detected_at,
                    "result_detected_at": result_detected_at,
                    "result": result if state == State.RESULT else None,
                    "open_card": latest_open_card,
                    "round_number": latest_round_number,
                    "cowboy_hand": None,
                    "bull_hand": None,
                    "screen_image": encode_jpeg(thumb),
                    # 検出値
                    "bet_values":    {k: v for k, v in cached_bets.items()},
                    "win_scores":    win_scores,
                    "result_scores": result_scores,
                    "winning_hand_scores": winning_hand_scores,
                    "jackpot_stock": cached_jackpot_stock,
                    "prediction":          cached_prediction,
                    "side_bet_prediction": cached_side_bet_pred,
                    "timer_value":         latest_timer_value,
                    "timer_image":         encode_crop(img, cap["timer_crop"]) if "timer_crop" in cap else None,
                    # 全クロップ領域画像（座標チューニング確認用）
                    "round_image":         encode_crop(img, cap["round_crop"]) if "round_crop" in cap else None,
                    "open_card_image":     encode_jpeg(cached_card_image) if (cached_card_image is not None) else encode_crop(img, cap["open_card_crop"]),
                    "result_image":        encode_crop(cached_result_image if (state == State.RESULT and cached_result_image is not None) else img, cap["result_crop"]) if "result_crop" in cap else None,
                    "jackpot_stock_image": encode_crop(img, cap["jackpot_stock_crop"]) if "jackpot_stock_crop" in cap else None,
                    "bet_images":          {k: encode_crop(img, v) for k, v in cap.get("bet_crops", {}).items()},
                    "win_images":          {k: encode_crop(img, v) for k, v in cap.get("win_regions", {}).items()},
                    "winning_hand_images": [encode_crop(img, row) for row in cap.get("winning_hand_rows", [])],
                }
                try:
                    post_capture_preview(client, base_url, token, preview_payload)
                    preview_last_sent = now_preview
                except (httpx.RequestError, httpx.HTTPStatusError) as e:
                    print(f"[WARN] プレビュー送信失敗: {e}", file=sys.stderr)

            # ── 結果確定チェック ──
            if state != State.RESULT or result_streak < result_stable_count:
                # まだ確定ではない: タイムアウトのチェック
                if state != State.PREPARING and (now - watching_start > result_timeout):
                    print(
                        f"[WARN] 結果検出タイムアウト ({result_timeout}s)。"
                        "準備中に戻ります。"
                    )
                    # カードもラウンド番号も一切検出できなかった場合は、無効な画面（または配信停止など）とみなしてログ保存をスキップ
                    if latest_round_number is not None or latest_open_card is not None:
                        log_file_name = save_round_log(capturer, latest_round_number)
                        
                        # エラーPOST
                        error_payload = {
                            "open_card": latest_open_card,
                            "result": "error",
                            "cowboy_hand": None,
                            "bull_hand": None,
                            "round_number": latest_round_number,
                            "jackpot_stock": cached_jackpot_stock,
                            "bet_cowboy":    cached_bets.get("cowboy"),
                            "bet_draw":      cached_bets.get("draw"),
                            "bet_bull":      cached_bets.get("bull"),
                            "bet_any_flash": cached_bets.get("any_flash"),
                            "bet_any_pair":  cached_bets.get("any_pair"),
                            "bet_any_ace":   cached_bets.get("any_ace"),
                            "bet_win_high":  cached_bets.get("win_high"),
                            "bet_win_two":   cached_bets.get("win_two"),
                            "bet_win_sf":    cached_bets.get("win_sf"),
                            "bet_win_fh":    cached_bets.get("win_fh"),
                            "bet_win_four":  cached_bets.get("win_four"),
                            "card_image":    encode_crop(img, cap["open_card_crop"], scale=4) if latest_open_card else None,
                            "ocr_debug":     "\n".join(ocr_debug_list) if ocr_debug_list else None,
                            "log_file_name": log_file_name,
                        }
                        try:
                            post_game(client, base_url, token, error_payload)
                            print(f"[INFO] タイムアウトラウンド ({latest_round_number}) のエラー POST に成功しました。")
                        except Exception as e:
                            print(f"[ERROR] タイムアウトラウンドのエラー POST に失敗しました: {e}", file=sys.stderr)

                        # エラーPOSTでも last_confirmed_round を更新して次ラウンドの補正を有効にする
                        if latest_round_number is not None:
                            last_confirmed_round = latest_round_number
                            last_confirmed_time = time.time()
                    else:
                        print("[INFO] カードおよびラウンド番号が未検出のため、空ログの保存をスキップします。")

                    state = State.PREPARING
                    watching_start = time.time()
                    result_streak = 0
                    last_streak_result = None
                    # latest_round_number をリセットして BETTING 移行後の「ラウンド変更誤検知」を防ぐ
                    latest_round_number = None
                    latest_open_card = None
                    cached_prediction = None
                    cached_side_bet_pred = None
                    round_number_scanned_this_round = False
                    ocr_debug_list.clear()
                    log_file_name = None
                    capturer.reset()
                    latest_timer_value = None
                    timer_active_last_seen = 0.0
                    timer_active_value = 0
                    countdown_end_time = 0.0
                    result_phase_timer_streak = 0
                    last_result_phase_timer_value = None
                    result_entered_at = 0.0
                    cached_result_image = None

                time.sleep(poll_fast)
                if once:
                    break
                continue

            # 結果あり: 連続カウント（RESULT state ブロックで未更新の場合のみ加算）
            if result_streak < result_stable_count:
                if result == last_streak_result:
                    result_streak += 1
                else:
                    result_streak = 1
                    last_streak_result = result

            print(
                f"[INFO] 結果検出 ({result_streak}/{result_stable_count}): "
                f"result={result}  open_card={latest_open_card}"
            )

            if result_streak < result_stable_count:
                # まだ確定に達していない
                time.sleep(poll_fast)
                if once:
                    break
                continue

            # ── 結果確定: POST ────────────────────────────────
            result_detected_at = datetime.now(UTC).isoformat()

            # サブポジション WIN フラグ (8種)
            sub_wins: dict[str, bool] = {k: False for k in ALL_WIN_KEYS}
            if "win_regions" in cap:
                sub_wins = detect_sub_wins(img, cap["win_regions"], debug=debug)

            # ラウンド未取得なら結果確定直前に最終スキャン
            if latest_round_number is None and "round_crop" in cap:
                latest_round_number = detect_round_number(img, cap["round_crop"], debug=debug)
                if latest_round_number is not None:
                    print(f"[INFO] ラウンド番号（結果確定時）: {latest_round_number}")

            # ラウンド番号確定（最終スキャン後）
            round_number = latest_round_number
            if round_number is not None:
                last_confirmed_round = round_number
                last_confirmed_time = time.time()

            # 最終ベット額（キャッシュ優先、WIN時はキャッシュが最も正確）
            # WIN アニメーション後に直接読むと火炎などでラベルが隠れる場合がある
            bets = cached_bets.copy()

            # ラウンドログを保存
            log_file_name = save_round_log(capturer, round_number)

            print(
                f"[INFO] 結果確定 → POST: result={result}  open_card={latest_open_card}  "
                f"round={round_number}  bets={bets}  sub_wins={sub_wins}  log_file={log_file_name}"
            )
            # オープンカード画像を base64 で POST ペイロードに含める
            card_image_b64 = None
            if cached_card_image is not None:
                large = cv2.resize(cached_card_image, None, fx=4, fy=4, interpolation=cv2.INTER_LANCZOS4)
                card_image_b64 = encode_jpeg(large, quality=85)
            elif latest_open_card:
                card_image_b64 = encode_crop(img, cap["open_card_crop"], scale=4)

            payload = {
                "open_card": latest_open_card,
                "result": result,
                "cowboy_hand": None,
                "bull_hand": None,
                "round_number": round_number,
                "jackpot_stock": cached_jackpot_stock,
                "bet_cowboy":    bets.get("cowboy"),
                "bet_draw":      bets.get("draw"),
                "bet_bull":      bets.get("bull"),
                "bet_any_flash": bets.get("any_flash"),
                "bet_any_pair":  bets.get("any_pair"),
                "bet_any_ace":   bets.get("any_ace"),
                "bet_win_high":  bets.get("win_high"),
                "bet_win_two":   bets.get("win_two"),
                "bet_win_sf":    bets.get("win_sf"),
                "bet_win_fh":    bets.get("win_fh"),
                "bet_win_four":  bets.get("win_four"),
                "win_any_flash": sub_wins.get("any_flash"),
                "win_any_pair":  sub_wins.get("any_pair"),
                "win_any_ace":   sub_wins.get("any_ace"),
                "win_high":      sub_wins.get("win_high"),
                "win_two":       sub_wins.get("win_two"),
                "win_sf":        sub_wins.get("win_sf"),
                "win_fh":        sub_wins.get("win_fh"),
                "win_four":      sub_wins.get("win_four"),
                "card_image":    card_image_b64,
                "ocr_debug":     "\n".join(ocr_debug_list) if ocr_debug_list else None,
                "log_file_name": log_file_name,
                "pred_cowboy":   cached_prediction.get("cowboy")        if cached_prediction else None,
                "pred_draw":     cached_prediction.get("draw")          if cached_prediction else None,
                "pred_bull":     cached_prediction.get("bull")          if cached_prediction else None,
                "pred_result":   cached_prediction.get("predicted")     if cached_prediction else None,
                "model_version": cached_prediction.get("model_version") if cached_prediction else None,
                "pred_any_flash": cached_side_bet_pred.get("any_flash") if cached_side_bet_pred else None,
                "pred_any_pair":  cached_side_bet_pred.get("any_pair")  if cached_side_bet_pred else None,
                "pred_any_ace":   cached_side_bet_pred.get("any_ace")   if cached_side_bet_pred else None,
                "pred_win_high":  cached_side_bet_pred.get("win_high")  if cached_side_bet_pred else None,
                "pred_win_two":   cached_side_bet_pred.get("win_two")   if cached_side_bet_pred else None,
                "pred_win_sf":    cached_side_bet_pred.get("win_sf")    if cached_side_bet_pred else None,
                "pred_win_fh":    cached_side_bet_pred.get("win_fh")    if cached_side_bet_pred else None,
                "pred_win_four":  cached_side_bet_pred.get("win_four")  if cached_side_bet_pred else None,
            }
            try:
                resp = post_game(client, base_url, token, payload)
                if resp.get("skipped"):
                    print(f"[INFO] 重複スキップ: {resp.get('reason')}")
                else:
                    game_id = resp.get("id")
                    print(f"[INFO] POST 成功: id={game_id}  result={resp.get('result')}")
                    if game_id:
                        _save_result_capture(game_id, img)
                    # カード画像をファイルにも保存（カバレッジテスト用）
                    if game_id and latest_open_card:
                        if cached_card_image is not None:
                            _save_card_shot(game_id, latest_open_card, cached_card_image)
                        else:
                            _save_card_shot(game_id, latest_open_card, img, cap["open_card_crop"])
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    print("[WARN] トークン期限切れ。再ログインして再送します", file=sys.stderr)
                    try:
                        token = login(client, base_url, username, password)
                        token_refreshed_at = time.time()
                        resp = post_game(client, base_url, token, payload)
                        game_id = resp.get("id")
                        print(f"[INFO] 再送 POST 成功: id={game_id}")
                        if game_id:
                            _save_result_capture(game_id, img)
                        if game_id and latest_open_card:
                            if cached_card_image is not None:
                                _save_card_shot(game_id, latest_open_card, cached_card_image)
                            else:
                                _save_card_shot(game_id, latest_open_card, img, cap["open_card_crop"])
                    except (httpx.RequestError, httpx.HTTPStatusError) as relogin_error:
                        print(f"[ERROR] 再ログイン後 POST 失敗: {relogin_error}", file=sys.stderr)
                else:
                    print(
                        f"[ERROR] POST 失敗: {e.response.status_code} {e.response.text}",
                        file=sys.stderr,
                    )
            except httpx.RequestError as e:
                print(f"[ERROR] POST 失敗: {e}", file=sys.stderr)

            # → COOLDOWN
            state = State.COOLDOWN
            cooldown_start = time.time()
            result_streak = 0
            last_streak_result = None
            latest_open_card = None
            latest_round_number = None
            open_detected_at = None
            result_detected_at = None
            cached_card_image = None
            cached_prediction = None
            cached_side_bet_pred = None
            latest_timer_value = None
            timer_active_last_seen = 0.0
            timer_active_value = 0
            countdown_end_time = 0.0
            result_phase_timer_streak = 0
            last_result_phase_timer_value = None
            result_entered_at = 0.0
            cached_result_image = None
            print(f"[INFO] → COOLDOWN ({post_round_cooldown}s)")

            if once:
                break


def main() -> None:
    parser = argparse.ArgumentParser(description="カウボーイゲーム キャプチャ")
    parser.add_argument("--once", action="store_true", help="1回スキャンして終了")
    parser.add_argument("--debug", action="store_true", help="デバッグ画像を /tmp に保存")
    args = parser.parse_args()

    cfg = load_config()
    run(cfg, once=args.once, debug=args.debug)


if __name__ == "__main__":
    main()
