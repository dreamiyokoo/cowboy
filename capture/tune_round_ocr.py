#!/usr/bin/env python3
"""
tune_round_ocr.py — ラウンド番号 OCR チューニングツール

スクリーンショットを取得し、ラウンド番号領域を切り抜いて、
複数のOCRプリセットでリアルタイムに精度をテスト。

使い方:
    python3 capture/tune_round_ocr.py

操作:
    - キー 0-7: 異なるプリセットを試す
    - n:     次のスクリーンショットを取得
    - s:     現在の領域をconfig.ymlに保存
    - q:     終了
"""

import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytesseract
import yaml

try:
    import easyocr as _easyocr
    READER = _easyocr.Reader(["en"], gpu=False, verbose=False)
except ImportError:
    READER = None
    print("[WARN] EasyOCR 未インストール")

CONFIG_PATH = Path(__file__).parent / "config.yml"

# OCR プリセット
PRESETS = [
    {
        "name": "EasyOCR (CLAHE 強調)",
        "fn": "easyocr_clahe",
    },
    {
        "name": "Tesseract (反転 psm=7)",
        "fn": "tesseract_inv_psm7",
    },
    {
        "name": "Tesseract (反転 psm=8)",
        "fn": "tesseract_inv_psm8",
    },
    {
        "name": "Tesseract (反転 psm=13)",
        "fn": "tesseract_inv_psm13",
    },
    {
        "name": "Tesseract (nolist psm=7)",
        "fn": "tesseract_nolist_psm7",
    },
    {
        "name": "EasyOCR (raw)",
        "fn": "easyocr_raw",
    },
    {
        "name": "Tesseract (元画像 psm=7)",
        "fn": "tesseract_raw_psm7",
    },
    {
        "name": "適応的閾値",
        "fn": "adaptive_threshold",
    },
]


def take_screenshot() -> np.ndarray | None:
    """ADB screencap"""
    try:
        result = subprocess.run(
            ["adb", "exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            print(f"[ERROR] screencap failed: {result.stderr.decode()}")
            return None
        arr = np.frombuffer(result.stdout, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception as e:
        print(f"[ERROR] {e}")
        return None


def load_config() -> dict:
    """config.yml を読み込む"""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def save_crop_to_config(y0: int, y1: int, x0: int, x1: int) -> None:
    """クロップ座標をconfig.ymlに保存"""
    cfg = load_config()
    cfg["capture"]["round_crop"] = [y0, y1, x0, x1]
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
    print(f"[INFO] config.yml に保存: round_crop = [{y0}, {y1}, {x0}, {x1}]")


def easyocr_clahe(region: np.ndarray) -> str:
    """EasyOCR + CLAHE"""
    if READER is None:
        return "(EasyOCR なし)"
    lab = cv2.cvtColor(region, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    l = clahe.apply(l)
    enhanced = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
    large = cv2.resize(enhanced, None, fx=3, fy=3, interpolation=cv2.INTER_LANCZOS4)
    results = READER.readtext(large, detail=0)
    return " ".join(results)


def tesseract_inv_psm7(region: np.ndarray) -> str:
    """Tesseract (反転, psm=7)"""
    large = cv2.resize(region, None, fx=3, fy=3, interpolation=cv2.INTER_LANCZOS4)
    gray = cv2.cvtColor(large, cv2.COLOR_BGR2GRAY)
    _, bright = cv2.threshold(gray, 140, 255, cv2.THRESH_BINARY)
    bright_inv = cv2.bitwise_not(bright)
    cfg = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789"
    return pytesseract.image_to_string(bright_inv, config=cfg).strip()


def tesseract_inv_psm8(region: np.ndarray) -> str:
    """Tesseract (反転, psm=8)"""
    large = cv2.resize(region, None, fx=3, fy=3, interpolation=cv2.INTER_LANCZOS4)
    gray = cv2.cvtColor(large, cv2.COLOR_BGR2GRAY)
    _, bright = cv2.threshold(gray, 140, 255, cv2.THRESH_BINARY)
    bright_inv = cv2.bitwise_not(bright)
    cfg = "--oem 3 --psm 8 -c tessedit_char_whitelist=0123456789"
    return pytesseract.image_to_string(bright_inv, config=cfg).strip()


def tesseract_inv_psm13(region: np.ndarray) -> str:
    """Tesseract (反転, psm=13)"""
    large = cv2.resize(region, None, fx=3, fy=3, interpolation=cv2.INTER_LANCZOS4)
    gray = cv2.cvtColor(large, cv2.COLOR_BGR2GRAY)
    _, bright = cv2.threshold(gray, 140, 255, cv2.THRESH_BINARY)
    bright_inv = cv2.bitwise_not(bright)
    cfg = "--oem 3 --psm 13 -c tessedit_char_whitelist=0123456789"
    return pytesseract.image_to_string(bright_inv, config=cfg).strip()


def tesseract_nolist_psm7(region: np.ndarray) -> str:
    """Tesseract (whitelist なし, psm=7)"""
    large = cv2.resize(region, None, fx=3, fy=3, interpolation=cv2.INTER_LANCZOS4)
    gray = cv2.cvtColor(large, cv2.COLOR_BGR2GRAY)
    _, bright = cv2.threshold(gray, 140, 255, cv2.THRESH_BINARY)
    bright_inv = cv2.bitwise_not(bright)
    cfg = "--oem 3 --psm 7"
    return pytesseract.image_to_string(bright_inv, config=cfg).strip()


def easyocr_raw(region: np.ndarray) -> str:
    """EasyOCR (前処理なし)"""
    if READER is None:
        return "(EasyOCR なし)"
    large = cv2.resize(region, None, fx=3, fy=3, interpolation=cv2.INTER_LANCZOS4)
    results = READER.readtext(large, detail=0)
    return " ".join(results)


def tesseract_raw_psm7(region: np.ndarray) -> str:
    """Tesseract (元画像, psm=7, whitelist あり)"""
    large = cv2.resize(region, None, fx=3, fy=3, interpolation=cv2.INTER_LANCZOS4)
    gray = cv2.cvtColor(large, cv2.COLOR_BGR2GRAY)
    cfg = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789"
    return pytesseract.image_to_string(gray, config=cfg).strip()


def adaptive_threshold(region: np.ndarray) -> str:
    """適応的閾値 + Tesseract"""
    large = cv2.resize(region, None, fx=3, fy=3, interpolation=cv2.INTER_LANCZOS4)
    gray = cv2.cvtColor(large, cv2.COLOR_BGR2GRAY)
    thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
    cfg = "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789"
    return pytesseract.image_to_string(thresh, config=cfg).strip()


OCR_FUNCS = {
    "easyocr_clahe": easyocr_clahe,
    "tesseract_inv_psm7": tesseract_inv_psm7,
    "tesseract_inv_psm8": tesseract_inv_psm8,
    "tesseract_inv_psm13": tesseract_inv_psm13,
    "tesseract_nolist_psm7": tesseract_nolist_psm7,
    "easyocr_raw": easyocr_raw,
    "tesseract_raw_psm7": tesseract_raw_psm7,
    "adaptive_threshold": adaptive_threshold,
}


def display_results(region: np.ndarray, current_preset: int) -> None:
    """全プリセットのOCR結果をテキスト表示"""
    print("\n" + "=" * 70)
    print("ラウンド番号 OCR 結果")
    print("=" * 70)

    for i, preset in enumerate(PRESETS):
        fn = OCR_FUNCS.get(preset["fn"])
        if fn is None:
            result = "(関数なし)"
        else:
            result = fn(region)

        marker = "→" if i == current_preset else " "
        print(f"{marker} [{i}] {preset['name']:<30} : {result}")

    print("=" * 70)
    print("操作: 0-7=プリセット選択, n=新規取得, s=保存, q=終了")
    print("=" * 70)


def main() -> None:
    print("[INFO] ラウンド番号 OCR チューニングツール")
    print("[INFO] ADB スクリーンショットを取得中...")

    img = take_screenshot()
    if img is None:
        print("[ERROR] スクリーンショット取得失敗")
        sys.exit(1)

    cfg = load_config()
    y0, y1, x0, x1 = cfg["capture"]["round_crop"]
    current_preset = 0
    print(f"[INFO] 現在のクロップ: y=[{y0},{y1}] x=[{x0},{x1}]")
    print("\n[ヒント] 座標微調整:")
    print("  w/a/s/d = y0/x0減少, W/A/S/D = y0/x0増加")
    print("  i/j/k/l = y1/x1減少, I/J/K/L = y1/x1増加")

    while True:
        region = img[y0:y1, x0:x1]
        if region.size == 0:
            print("[ERROR] 無効なクロップ座標")
            break

        # 結果表示＆保存
        display_results(region, current_preset)

        # クロップ画像も保存
        h, w = region.shape[:2]
        display_img = region.copy()
        cv2.putText(display_img, f"Preset {current_preset}: {PRESETS[current_preset]['name']}", (5, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.imwrite("/tmp/round_ocr_crop.png", display_img)
        print(f"[INFO] クロップ画像を保存: /tmp/round_ocr_crop.png")

        # 入力待ち
        try:
            key = input("\n入力 (0-7/n/s/座標調整/q): ").strip().lower()
        except EOFError:
            print("[INFO] EOF検出、終了")
            break

        if key == "q":
            print("[INFO] 終了")
            break
        elif key == "n":
            img = take_screenshot()
            if img is not None:
                print("[INFO] 新しいスクリーンショットを取得しました")
                region_new = img[y0:y1, x0:x1]
                if region_new.size > 0:
                    cv2.imwrite("/tmp/round_ocr_new.png", region_new)
            else:
                print("[WARN] スクリーンショット取得失敗")
        elif key == "s":
            save_crop_to_config(y0, y1, x0, x1)
        elif key in "01234567":
            current_preset = int(key)
            print(f"[INFO] プリセット {current_preset}: {PRESETS[current_preset]['name']}")
        # 座標調整: y0
        elif key == "w":
            y0 = max(0, y0 - 5)
            print(f"[INFO] y0 = {y0}")
        elif key == "W":
            y0 = min(img.shape[0], y0 + 5)
            print(f"[INFO] y0 = {y0}")
        # 座標調整: y1
        elif key == "i":
            y1 = max(y0 + 10, y1 - 5)
            print(f"[INFO] y1 = {y1}")
        elif key == "I":
            y1 = min(img.shape[0], y1 + 5)
            print(f"[INFO] y1 = {y1}")
        # 座標調整: x0
        elif key == "a":
            x0 = max(0, x0 - 5)
            print(f"[INFO] x0 = {x0}")
        elif key == "A":
            x0 = min(img.shape[1], x0 + 5)
            print(f"[INFO] x0 = {x0}")
        # 座標調整: x1
        elif key == "j":
            x1 = max(x0 + 10, x1 - 5)
            print(f"[INFO] x1 = {x1}")
        elif key == "J":
            x1 = min(img.shape[1], x1 + 5)
            print(f"[INFO] x1 = {x1}")
        elif key == "p":
            print(f"[INFO] 現在の座標: y=[{y0},{y1}] x=[{x0},{x1}]")
        else:
            if key:
                print(f"[INFO] 不正な入力: {key}")


if __name__ == "__main__":
    main()
