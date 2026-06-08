#!/usr/bin/env python3
"""
debug_view.py — スクリーンショットを取得してOCR領域を可視化する

使い方:
    python3 capture/debug_view.py                   # ADB でスクリーンショット取得
    python3 capture/debug_view.py --file screen.png # 既存のPNGを使う
    python3 capture/debug_view.py --out /tmp/out.png # 出力先を指定（デフォルト: /tmp/cowboy_debug.png）

出力画像に各クロップ領域を色分けして描画し、OCR結果をオーバーレイ表示する。
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytesseract
import yaml

try:
    import easyocr as _easyocr
    _reader = _easyocr.Reader(["en"], gpu=False, verbose=False)
    print("[INFO] EasyOCR ロード完了")
except ImportError:
    _reader = None
    print("[WARN] EasyOCR 未インストール: ラウンド・ベット検出はスキップ")

CONFIG_PATH = Path(__file__).parent / "config.yml"

# 領域ごとの色 (BGR)
COLORS = {
    "open_card":     (0,   255, 255),  # 黄
    "round":         (255, 128,   0),  # 青
    "result":        (0,   255,   0),  # 緑
    "bet":           (255,   0, 255),  # マゼンタ
    "win_region":    (0,   128, 255),  # オレンジ
    "winning_hand":  (128, 255,   0),  # 黄緑
}

FONT       = cv2.FONT_HERSHEY_SIMPLEX
FONT_SCALE = 0.55
THICKNESS  = 1


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def take_screenshot(device: str) -> np.ndarray | None:
    base = ["adb"]
    if device != "usb":
        base += ["-s", device]
    cmd = base + ["exec-out", "screencap", "-p"]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=15)
        if result.returncode != 0:
            print(f"[ERROR] screencap 失敗: {result.stderr.decode(errors='ignore')}", file=sys.stderr)
            return None
        arr = np.frombuffer(result.stdout, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except subprocess.TimeoutExpired:
        print("[ERROR] screencap タイムアウト", file=sys.stderr)
        return None


def draw_region(canvas: np.ndarray, y0: int, y1: int, x0: int, x1: int,
                label: str, color: tuple, ocr_text: str = "") -> None:
    cv2.rectangle(canvas, (x0, y0), (x1, y1), color, 2)
    # ラベル背景
    (tw, th), _ = cv2.getTextSize(label, FONT, FONT_SCALE, THICKNESS)
    ly = max(y0 - 4, th + 4)
    cv2.rectangle(canvas, (x0, ly - th - 4), (x0 + tw + 4, ly + 2), color, -1)
    cv2.putText(canvas, label, (x0 + 2, ly - 2), FONT, FONT_SCALE, (0, 0, 0), THICKNESS, cv2.LINE_AA)
    # OCR 結果テキスト
    if ocr_text:
        display = ocr_text[:40] + ("..." if len(ocr_text) > 40 else "")
        cv2.putText(canvas, display, (x0 + 2, y0 + 20), FONT, FONT_SCALE, color, THICKNESS, cv2.LINE_AA)


def ocr_tesseract(region: np.ndarray, scale: int = 4) -> str:
    large = cv2.resize(region, None, fx=scale, fy=scale, interpolation=cv2.INTER_LANCZOS4)
    gray  = cv2.cvtColor(large, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    cfg   = "--oem 1 --psm 8 -c tessedit_char_whitelist=AKQJakqj0123456789SHDCshdc"
    return pytesseract.image_to_string(th, config=cfg).strip()


def ocr_easyocr(region: np.ndarray, scale: int = 2) -> str:
    if _reader is None:
        return "(EasyOCR なし)"
    large   = cv2.resize(region, None, fx=scale, fy=scale, interpolation=cv2.INTER_LANCZOS4)
    results = _reader.readtext(large, detail=0)
    return " ".join(results)


def brightness_score(region: np.ndarray) -> float:
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    return float(np.count_nonzero(hsv[:, :, 2] > 220)) / (region.shape[0] * region.shape[1])


def save_crop(img: np.ndarray, y0: int, y1: int, x0: int, x1: int, name: str, out_dir: str) -> None:
    region = img[y0:y1, x0:x1]
    if region.size == 0:
        return
    path = os.path.join(out_dir, f"crop_{name}.png")
    cv2.imwrite(path, region)
    # 前処理版も保存
    large = cv2.resize(region, None, fx=2, fy=2, interpolation=cv2.INTER_LANCZOS4)
    gray  = cv2.cvtColor(large, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    cv2.imwrite(os.path.join(out_dir, f"crop_{name}_thresh.png"), th)


def annotate(img: np.ndarray, cfg: dict, out_dir: str = "/tmp") -> np.ndarray:
    cap     = cfg["capture"]
    canvas  = img.copy()
    h, w    = canvas.shape[:2]
    results = []

    # ── オープンカード ──────────────────────────
    y0, y1, x0, x1 = cap["open_card_crop"]
    region  = img[y0:y1, x0:x1]
    tess    = ocr_tesseract(region, cap.get("scale", 4))
    easy    = ocr_easyocr(region)
    text    = f"Tess:{tess!r}  Easy:{easy!r}"
    draw_region(canvas, y0, y1, x0, x1, "open_card", COLORS["open_card"], text)
    save_crop(img, y0, y1, x0, x1, "open_card", out_dir)
    results.append(("open_card", text))
    print(f"[open_card]  {text}")

    # ── ラウンド番号 ────────────────────────────
    if "round_crop" in cap:
        y0, y1, x0, x1 = cap["round_crop"]
        region = img[y0:y1, x0:x1]
        save_crop(img, y0, y1, x0, x1, "round", out_dir)

        # 輝度閾値 + Tesseract
        large_r   = cv2.resize(region, None, fx=3, fy=3, interpolation=cv2.INTER_LANCZOS4)
        gray_r    = cv2.cvtColor(large_r, cv2.COLOR_BGR2GRAY)
        _, bright = cv2.threshold(gray_r, 140, 255, cv2.THRESH_BINARY)
        bright_inv = cv2.bitwise_not(bright)
        cv2.imwrite(os.path.join(out_dir, "crop_round_bright.png"), bright)
        cv2.imwrite(os.path.join(out_dir, "crop_round_bright_inv.png"), bright_inv)
        tess_num = ""
        for psm in [7, 8, 13]:
            _cfg = f"--oem 3 --psm {psm} -c tessedit_char_whitelist=0123456789"
            _t   = pytesseract.image_to_string(bright_inv, config=_cfg).strip()
            print(f"  [DEBUG] round Tess psm={psm}: {_t!r}")
            nums = re.findall(r"\d{4,}", _t)
            if nums:
                tess_num = max(nums, key=len)
                break
        best_t   = tess_num  # 既に4桁以上のみ

        # CLAHE + EasyOCR
        lab = cv2.cvtColor(region, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
        l = clahe.apply(l)
        region_enh = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
        easy  = ocr_easyocr(region_enh, 3)
        cv2.imwrite(os.path.join(out_dir, "crop_round_enhanced.png"), region_enh)
        nums_e = re.findall(r"\d+", easy)
        best_e = max(nums_e, key=len) if nums_e else ""

        # EasyOCR を優先（capture.py と同じ順序）
        best  = best_e if len(best_e) >= 4 else (best_t if len(best_t) >= 4 else "(なし)")
        text  = f"Tess:{tess_num!r}  Easy:{easy!r}  →  {best}"
        draw_region(canvas, y0, y1, x0, x1, "round", COLORS["round"], text)
        results.append(("round", text))
        print(f"[round]      {text}")

    # ── 結果領域 ────────────────────────────────
    y0, y1, x0, x1 = cap["result_crop"]
    region  = img[y0:y1, x0:x1]
    rw      = region.shape[1]
    third   = rw // 3
    scores  = {
        "cowboy": brightness_score(region[:, :third]),
        "draw":   brightness_score(region[:, third:2*third]),
        "bull":   brightness_score(region[:, 2*third:]),
    }
    winner  = max(scores, key=scores.get)
    detected = winner if scores[winner] >= 0.30 else "未検出"
    text    = f"bright={scores}  → {detected}"
    draw_region(canvas, y0, y1, x0, x1, "result", COLORS["result"], text)
    # 3分割線を描画
    cv2.line(canvas, (x0 + third, y0), (x0 + third, y1), COLORS["result"], 1)
    cv2.line(canvas, (x0 + 2*third, y0), (x0 + 2*third, y1), COLORS["result"], 1)
    results.append(("result", text))
    print(f"[result]     {text}")

    # ── ベット額 ────────────────────────────────
    if "bet_crops" in cap:
        for key, coords in cap["bet_crops"].items():
            y0, y1, x0, x1 = coords
            region = img[y0:y1, x0:x1]
            easy   = ocr_easyocr(region, 2)
            label  = f"bet:{key}"
            draw_region(canvas, y0, y1, x0, x1, label, COLORS["bet"], easy)
        print(f"[bet]        EasyOCR で {len(cap['bet_crops'])} 領域を描画")

    # ── WIN 判定領域 ────────────────────────────
    if "win_regions" in cap:
        for key, coords in cap["win_regions"].items():
            y0, y1, x0, x1 = coords
            region = img[y0:y1, x0:x1]
            score  = brightness_score(region)
            win    = score >= 0.30
            label  = f"win:{key}"
            color  = (0, 0, 255) if win else COLORS["win_region"]
            draw_region(canvas, y0, y1, x0, x1, label, color, f"bright={score:.3f} {'WIN!' if win else ''}")

    # ── サマリーをコンソールに出力 ───────────────
    print("\n─── サマリー ────────────────────────────────────────────")
    for name, val in results:
        print(f"  {name:<12}: {val}")

    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR 領域デバッグビュー")
    parser.add_argument("--file", help="既存のスクリーンショット PNG を使用")
    parser.add_argument("--out", default="/tmp/cowboy_debug.png", help="出力ファイルパス")
    args = parser.parse_args()

    cfg = load_config()

    if args.file:
        img = cv2.imread(args.file)
        if img is None:
            print(f"[ERROR] 画像を読み込めませんでした: {args.file}", file=sys.stderr)
            sys.exit(1)
        print(f"[INFO] ファイルから読み込み: {args.file}  ({img.shape[1]}x{img.shape[0]})")
    else:
        device = cfg["adb"]["device"]
        print(f"[INFO] ADB スクリーンショット取得中 (device={device}) ...")
        img = take_screenshot(device)
        if img is None:
            sys.exit(1)
        print(f"[INFO] 取得完了: {img.shape[1]}x{img.shape[0]}")

    out_dir = os.path.dirname(args.out)
    annotated = annotate(img, cfg, out_dir=out_dir)
    cv2.imwrite(args.out, annotated)
    print(f"\n[INFO] 保存完了: {args.out}")
    print("[INFO] 画像を開いて各領域の位置と OCR 結果を確認してください。")


if __name__ == "__main__":
    main()
