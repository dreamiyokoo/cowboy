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

# ────────────────────────────────────────────────
# 設定読み込み
# ────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent / "config.yml"


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


# ────────────────────────────────────────────────
# ステート定義
# ────────────────────────────────────────────────

class State(Enum):
    WATCHING = "watching"   # 結果が出るのを待っている（オープンカードも随時取得）
    COOLDOWN = "cooldown"   # 結果POST後のクールダウン中


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


# ────────────────────────────────────────────────
# 結果判定（カウボーイ / 抽選 / ブル）
# ────────────────────────────────────────────────

def detect_result(img: np.ndarray, crop: list[int], debug: bool = False) -> str | None:
    """
    結果ボタン行を3分割し、WIN バッジ（非常に明るいピクセルが集中する）が
    どのセクションにあるかで勝者を判定する。

    ボタン配置（左→右）:
      左1/3 → カウボーイ勝利 (cowboy)
      中1/3 → 抽選         (draw)
      右1/3 → ノルの勝利   (bull)

    「WIN バッジ」は他セクションより明らかに明るいため、
    V チャンネル > 220 のピクセル比率でスコアリングする。
    max スコア < BRIGHT_THRESHOLD → まだ結果表示前 → None を返す
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
        # V > 220 の非常に明るいピクセルの比率
        bright = float(np.count_nonzero(hsv[:, :, 2] > 220)) / (sec.shape[0] * sec.shape[1])
        scores[name] = bright

    if debug:
        print(f"[DEBUG] result brightness: {scores}")
        cv2.imwrite("/tmp/cowboy_result_region.png", region)

    # WIN バッジが表示されているセクションは 0.30 以上になる
    # カウントダウン中はすべてのセクションが低い値
    BRIGHT_THRESHOLD = 0.30
    max_score = max(scores.values())

    if max_score < BRIGHT_THRESHOLD:
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


def detect_open_card(img: np.ndarray, crop: list[int], scale: int, debug: bool = False) -> str | None:
    """
    オープンカード領域から カード文字列 (例: "AH", "KS", "10D") を OCR で取得する。
    Tesseract で試み、取得できなければ EasyOCR にフォールバック。
    """
    y0, y1, x0, x1 = crop
    region = img[y0:y1, x0:x1]
    if region.size == 0:
        return None

    large = cv2.resize(region, None, fx=scale, fy=scale, interpolation=cv2.INTER_LANCZOS4)
    gray = cv2.cvtColor(large, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Tesseract: PSM 8（単一ワード）で試みる
    config = "--oem 1 --psm 8 -c tessedit_char_whitelist=AKQJakqj0123456789SHDCshdc"
    tess_text = pytesseract.image_to_string(thresh, config=config).strip()

    if debug:
        print(f"[DEBUG] open_card Tesseract raw: {repr(tess_text)}")
        cv2.imwrite("/tmp/cowboy_open_card.png", region)
        cv2.imwrite("/tmp/cowboy_open_card_thresh.png", thresh)

    result = _parse_card_text(tess_text, region)
    if result:
        return result

    # Tesseract で取れなかった場合 EasyOCR でフォールバック
    reader = _get_ocr_reader()
    if reader is not None:
        easyocr_results = reader.readtext(large, detail=0)
        easy_text = " ".join(easyocr_results)
        if debug:
            print(f"[DEBUG] open_card EasyOCR raw: {repr(easy_text)}")
        result = _parse_card_text(easy_text, region)
        if result:
            return result

    return None


def _estimate_suit_by_color(card_img: np.ndarray) -> str:
    """カード画像の赤成分比率でスートを大まかに推定する"""
    hsv = cv2.cvtColor(card_img, cv2.COLOR_BGR2HSV)
    red1 = cv2.inRange(hsv, np.array([0, 80, 80]), np.array([10, 255, 255]))
    red2 = cv2.inRange(hsv, np.array([160, 80, 80]), np.array([180, 255, 255]))
    red_pixels = np.count_nonzero(cv2.bitwise_or(red1, red2))
    total = card_img.shape[0] * card_img.shape[1]
    if total > 0 and red_pixels / total > 0.03:
        return "H"
    return "S"


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
        nums = re.findall(r"\d{4,}", text)
        if nums:
            return int(max(nums, key=len))

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
        nums = re.findall(r"\d{4,}", text)
        if nums:
            return int(max(nums, key=len))

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
        nums = re.findall(r"\d{4,}", full_text)
        if nums:
            return int(max(nums, key=len))

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

    if not username or not password:
        print(
            "[ERROR] username/password が設定されていません。"
            "config.yml か環境変数 CAPTURE_USERNAME / CAPTURE_PASSWORD を設定してください。",
            file=sys.stderr,
        )
        sys.exit(1)

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
        state               = State.WATCHING
        watching_start      = time.time()   # WATCHING に入った時刻（タイムアウト計測用）
        cooldown_start      = 0.0           # COOLDOWN に入った時刻
        result_streak       = 0             # 同一結果の連続検出回数
        last_streak_result  = None          # 連続検出中の結果値
        latest_open_card    = None          # 最後に読み取ったオープンカード
        latest_round_number: int | None = None   # 最後に読み取ったラウンド番号
        open_detected_at: str | None = None      # オープンカード初回検出時刻
        result_detected_at: str | None = None    # 結果確定時刻
        # ベット額キャッシュ: WATCHING 中に継続更新し、POST 時に使用
        # （WIN バッジのアニメーションでラベルが隠れる前に読み取る）
        cached_bets: dict[str, int | None] = {k: None for k in ALL_BET_KEYS}
        bet_last_updated    = 0.0           # EasyOCR 最終実行時刻（間引き用）
        BET_OCR_INTERVAL    = 3.0           # EasyOCR 実行間隔（秒）
        cached_jackpot_stock: int | None = None  # ジャックポットストックコイン

        print(f"[INFO] ステートマシン開始: state={state.value}")
        print(f"[INFO] タイミング設定: cooldown={post_round_cooldown}s  "
              f"poll_fast={poll_fast}s  stable_count={result_stable_count}  "
              f"timeout={result_timeout}s")

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

                # クールダウン終了 → WATCHING へ
                state = State.WATCHING
                watching_start = time.time()
                result_streak = 0
                last_streak_result = None
                latest_open_card = None
                latest_round_number = None
                open_detected_at = None
                result_detected_at = None
                cached_bets = {k: None for k in ALL_BET_KEYS}
                bet_last_updated = 0.0
                print(f"[INFO] クールダウン終了 → WATCHING")
                if once:
                    break
                continue

            # ════════════════════════════════════════════════
            # WATCHING: スクリーンショットを取得して解析
            # ════════════════════════════════════════════════
            img = take_screenshot(device)
            if img is None:
                print("[WARN] スクリーンショット取得失敗。再試行します...")
                time.sleep(poll_fast)
                if once:
                    break
                continue

            # ── オープンカードを随時更新 ──────────────────────
            card = detect_open_card(img, cap["open_card_crop"], cap["scale"], debug=debug)
            if card:
                if latest_open_card is None:
                    open_detected_at = datetime.now(UTC).isoformat()
                    print(f"[INFO] オープンカード初回検出: {card}  at={open_detected_at}")
                elif card != latest_open_card:
                    print(f"[INFO] オープンカード更新: {latest_open_card} → {card}")
                latest_open_card = card

            # ── 結果検出（軽い輝度判定を先に実行）────────────────
            result = detect_result(img, cap["result_crop"], debug=debug)

            # ベット額: 3秒ごと更新（結果表示中も継続してキャッシュを維持）
            if "bet_crops" in cap:
                if time.time() - bet_last_updated >= BET_OCR_INTERVAL:
                    new_bets = detect_all_bets(img, cap["bet_crops"], debug=debug)
                    for k, v in new_bets.items():
                        if v is not None:
                            cached_bets[k] = v
                    bet_last_updated = time.time()

            # ── 結果未検出中のみ実行（EasyOCR 系・アニメーション競合回避）────
            if result is None:
                # ラウンド番号: 継続取得してキャッシュ（結果画面では非表示の場合がある）
                if "round_crop" in cap:
                    rn = detect_round_number(img, cap["round_crop"], debug=debug)
                    if rn is not None and rn != latest_round_number:
                        print(f"[INFO] ラウンド番号更新: {latest_round_number} → {rn}")
                        latest_round_number = rn

            # プレビューを API に送信（UI 確認用）
            thumb = cv2.resize(img, (img.shape[1] // 3, img.shape[0] // 3))

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

            # 勝利ハンド行の輝度スコア（各行 WIN 判定用）
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

            preview_payload = {
                "open_detected_at": open_detected_at,
                "result_detected_at": result_detected_at,
                "result": result,
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
                # 全クロップ領域画像（座標チューニング確認用）
                "round_image":         encode_crop(img, cap["round_crop"]) if "round_crop" in cap else None,
                "open_card_image":     encode_crop(img, cap["open_card_crop"]),
                "result_image":        encode_crop(img, cap["result_crop"]) if "result_crop" in cap else None,
                "jackpot_stock_image": encode_crop(img, cap["jackpot_stock_crop"]) if "jackpot_stock_crop" in cap else None,
                "bet_images":          {k: encode_crop(img, v) for k, v in cap.get("bet_crops", {}).items()},
                "win_images":          {k: encode_crop(img, v) for k, v in cap.get("win_regions", {}).items()},
                "winning_hand_images": [encode_crop(img, row) for row in cap.get("winning_hand_rows", [])],
            }
            try:
                post_capture_preview(client, base_url, token, preview_payload)
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                print(f"[WARN] プレビュー送信失敗: {e}", file=sys.stderr)

            if result is None:
                # まだ結果表示されていない（カウントダウン中）
                result_streak = 0
                last_streak_result = None

                # タイムアウトチェック
                if now - watching_start > result_timeout:
                    print(
                        f"[WARN] 結果検出タイムアウト ({result_timeout}s)。"
                        "クロップ座標を確認してください。WATCHING をリセットします。"
                    )
                    watching_start = time.time()

                time.sleep(poll_fast)
                if once:
                    break
                continue

            # 結果あり: 連続カウント
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

            # 最終ベット額（キャッシュ優先、WIN時はキャッシュが最も正確）
            # WIN アニメーション後に直接読むと火炎などでラベルが隠れる場合がある
            bets = cached_bets.copy()

            print(
                f"[INFO] 結果確定 → POST: result={result}  open_card={latest_open_card}  "
                f"round={round_number}  bets={bets}  sub_wins={sub_wins}"
            )
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
            }
            try:
                resp = post_game(client, base_url, token, payload)
                if resp.get("skipped"):
                    print(f"[INFO] 重複スキップ: {resp.get('reason')}")
                else:
                    print(f"[INFO] POST 成功: id={resp.get('id')}  result={resp.get('result')}")
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    print("[WARN] トークン期限切れ。再ログインして再送します", file=sys.stderr)
                    try:
                        token = login(client, base_url, username, password)
                        token_refreshed_at = time.time()
                        resp = post_game(client, base_url, token, payload)
                        print(f"[INFO] 再送 POST 成功: id={resp.get('id')}")
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
