#!/usr/bin/env python3
import cv2
import pytesseract
import numpy as np
import re
import os

try:
    import easyocr
    reader = easyocr.Reader(["en"], gpu=False, verbose=False)
except ImportError:
    reader = None

def _estimate_suit_by_color(card_img: np.ndarray) -> str:
    hsv = cv2.cvtColor(card_img, cv2.COLOR_BGR2HSV)
    red1 = cv2.inRange(hsv, np.array([0, 80, 80]), np.array([10, 255, 255]))
    red2 = cv2.inRange(hsv, np.array([160, 80, 80]), np.array([180, 255, 255]))
    red_pixels = np.count_nonzero(cv2.bitwise_or(red1, red2))
    total = card_img.shape[0] * card_img.shape[1]
    ratio = red_pixels / total if total > 0 else 0
    # Let's print the red ratio for debugging
    print(f"    [color] Red ratio: {ratio:.4f}")
    if ratio > 0.03:
        return "H"
    return "S"

def parse_card_text(text: str, region: np.ndarray) -> str | None:
    text = re.sub(r"\s+", "", text.upper())
    rank = None
    for r in ["10", "A", "K", "Q", "J", "9", "8", "7", "6", "5", "4", "3", "2"]:
        if r in text:
            rank = r
            break
    if rank is None:
        return None
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

def run_test():
    img_path = "/app/raw_screen.png"
    if not os.path.exists(img_path):
        print(f"Error: {img_path} not found")
        return
    img = cv2.imread(img_path)
    print(f"Loaded image: {img.shape}")

    # Candidate crops: [y0, y1, x0, x1]
    candidates = [
        ("Current", [730, 860, 300, 380]),
        ("Old Commented", [710, 800, 195, 350]),
        ("Candidate 1", [715, 800, 280, 355]),
        ("Candidate 2", [710, 800, 280, 350]),
        ("Candidate 3", [715, 795, 280, 350]),
        ("Candidate 4", [715, 795, 285, 345]),
        ("Candidate 5", [710, 790, 285, 345]),
    ]

    for name, crop in candidates:
        y0, y1, x0, x1 = crop
        region = img[y0:y1, x0:x1]
        if region.size == 0:
            print(f"{name}: Empty region")
            continue
        
        # Save crop
        cv2.imwrite(f"/app/test_crop_{name}.png", region)

        # Preprocess
        scale = 4
        large = cv2.resize(region, None, fx=scale, fy=scale, interpolation=cv2.INTER_LANCZOS4)
        gray = cv2.cvtColor(large, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        cv2.imwrite(f"/app/test_crop_{name}_thresh.png", thresh)

        # Tesseract
        config = "--oem 1 --psm 8 -c tessedit_char_whitelist=AKQJakqj0123456789SHDCshdc"
        tess_text = pytesseract.image_to_string(thresh, config=config).strip()
        tess_parsed = parse_card_text(tess_text, region)

        # EasyOCR
        easy_text = ""
        easy_parsed = None
        if reader:
            results = reader.readtext(large, detail=0)
            easy_text = " ".join(results)
            easy_parsed = parse_card_text(easy_text, region)

        print(f"=== {name} {crop} ===")
        print(f"  Tess Raw: {repr(tess_text)} -> Parsed: {tess_parsed}")
        print(f"  Easy Raw: {repr(easy_text)} -> Parsed: {easy_parsed}")

if __name__ == "__main__":
    run_test()
