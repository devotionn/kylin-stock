#!/usr/bin/env python3
"""Offline OCR worker for fixed-layout transfer/receiving forms.

The worker intentionally returns a conservative draft. It extracts the fields
needed by KylinStock, but never posts inventory by itself. The desktop UI is the
human verification boundary.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Iterable, Sequence


LABEL_WORDS = {
    "调拨依据",
    "供应单位",
    "接收单位",
    "名称",
    "规格型号",
    "单位",
    "单价",
    "应发数",
    "实发数",
    "等级",
    "数量",
    "性能",
    "外观",
    "资料",
    "附件",
}


@dataclass(frozen=True)
class Token:
    text: str
    score: float
    left: float
    right: float
    top: float
    bottom: float
    cx: float
    cy: float
    width: float
    height: float


def compact(value: str) -> str:
    return re.sub(r"\s+", "", value or "").strip("：:")


def clean_value(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().strip("：:")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def token_from(box: Sequence[Sequence[float]], text: str, score: float) -> Token | None:
    if not box or len(box) < 4:
        return None
    try:
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
    except (TypeError, ValueError, IndexError):
        return None
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    if right <= left or bottom <= top:
        return None
    return Token(
        text=clean_value(text),
        score=float(score or 0.0),
        left=left,
        right=right,
        top=top,
        bottom=bottom,
        cx=(left + right) / 2.0,
        cy=(top + bottom) / 2.0,
        width=right - left,
        height=bottom - top,
    )


def find_anchor(
    tokens: Sequence[Token],
    labels: Sequence[str],
    *,
    min_y: float = 0.0,
    max_y: float = math.inf,
) -> Token | None:
    candidates: list[tuple[int, float, Token]] = []
    for token in tokens:
        if token.cy < min_y or token.cy > max_y:
            continue
        text = compact(token.text)
        for label in labels:
            target = compact(label)
            if not text:
                continue
            if target == text:
                candidates.append((0, token.top, token))
                break
            if target in text or (len(text) >= 2 and text in target):
                candidates.append((1, token.top, token))
                break
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], -item[2].score))
    return candidates[0][2]


def is_probable_label(token: Token) -> bool:
    # Header labels are short and deterministic in this fixed template. Using
    # substring matching here would incorrectly drop legitimate material names
    # such as “资料袋” or “附件盒”. Punctuation is already normalized by compact().
    value = compact(token.text)
    return value in LABEL_WORDS


def right_value(anchor: Token | None, tokens: Sequence[Token], page_width: float) -> tuple[str, float]:
    if anchor is None:
        return "", 0.0
    y_tolerance = max(anchor.height * 1.8, 12.0)
    candidates: list[tuple[float, Token]] = []
    for token in tokens:
        if token is anchor or is_probable_label(token):
            continue
        if token.left < anchor.right - max(4.0, anchor.width * 0.08):
            continue
        if token.left - anchor.right > page_width * 0.48:
            continue
        y_distance = abs(token.cy - anchor.cy)
        if y_distance > y_tolerance:
            continue
        distance = max(0.0, token.left - anchor.right) + y_distance * 2.5
        candidates.append((distance, token))
    if not candidates:
        return "", 0.0
    candidates.sort(key=lambda item: (item[0], -item[1].score))
    token = candidates[0][1]
    return clean_value(token.text), token.score


def numeric_value(value: str) -> float | None:
    candidate = compact(value).replace(",", "")
    if candidate and sum(ch.isdigit() for ch in candidate) >= max(1, len(candidate) - 2):
        candidate = candidate.replace("O", "0").replace("o", "0").replace("〇", "0")
    match = re.search(r"\d+(?:\.\d+)?", candidate)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def join_tokens(tokens: Iterable[Token]) -> tuple[str, float]:
    ordered = sorted(tokens, key=lambda token: token.left)
    if not ordered:
        return "", 0.0
    text = "".join(clean_value(token.text) for token in ordered).strip()
    score = sum(token.score for token in ordered) / len(ordered)
    return text, score


def cluster_rows(tokens: Sequence[Token], tolerance: float) -> list[list[Token]]:
    rows: list[list[Token]] = []
    for token in sorted(tokens, key=lambda item: (item.cy, item.left)):
        best_index = None
        best_distance = math.inf
        for index, row in enumerate(rows):
            row_y = sum(item.cy for item in row) / len(row)
            distance = abs(token.cy - row_y)
            if distance <= tolerance and distance < best_distance:
                best_index = index
                best_distance = distance
        if best_index is None:
            rows.append([token])
        else:
            rows[best_index].append(token)
    rows.sort(key=lambda row: sum(item.cy for item in row) / len(row))
    return rows


def exact_header_near(
    tokens: Sequence[Token],
    text: str,
    reference: Token,
    page_height: float,
    *,
    require_right: bool = False,
) -> Token | None:
    candidates = [
        token
        for token in tokens
        if compact(token.text) == compact(text)
        and abs(token.cy - reference.cy) <= page_height * 0.045
        and (not require_right or token.cx > reference.cx)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda token: (abs(token.cy - reference.cy), abs(token.cx - reference.cx)))


def extract_table(tokens: Sequence[Token], page_width: float, page_height: float) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    upper_limit = page_height * 0.62
    name_header = find_anchor(tokens, ["名称"], max_y=upper_limit)
    spec_header = find_anchor(tokens, ["规格型号", "规格"], max_y=upper_limit)

    if name_header is None or spec_header is None:
        warnings.append("未可靠定位“名称/规格型号”表头，请人工核对明细。")
        return [], warnings

    unit_header = exact_header_near(tokens, "单位", spec_header, page_height, require_right=True)
    issued_header = find_anchor(
        tokens,
        ["应发数", "应发"],
        min_y=max(0.0, spec_header.cy - page_height * 0.055),
        max_y=spec_header.cy + page_height * 0.055,
    )

    quantity_candidates = [
        token
        for token in tokens
        if compact(token.text) == "数量"
        and token.cy >= min(name_header.cy, spec_header.cy) - page_height * 0.035
        and token.cy <= max(name_header.cy, spec_header.cy) + page_height * 0.075
        and token.cx > spec_header.cx
    ]
    quantity_header: Token | None = None
    if quantity_candidates and issued_header is not None:
        quantity_header = min(
            quantity_candidates,
            key=lambda token: abs(token.cx - (issued_header.cx + issued_header.width * 0.22))
            + abs(token.cy - issued_header.cy) * 0.35,
        )
    elif quantity_candidates:
        quantity_header = min(quantity_candidates, key=lambda token: token.cx)

    if quantity_header is None:
        warnings.append("未可靠定位“应发数量”列，请人工填写数量。")

    header_bottom = max(
        name_header.bottom,
        spec_header.bottom,
        quantity_header.bottom if quantity_header else spec_header.bottom,
    )
    row_start = header_bottom + max(name_header.height, spec_header.height) * 0.25

    footer_candidates = []
    for label in ("调拨单位", "供应单位", "接收单位"):
        anchor = find_anchor(tokens, [label], min_y=row_start + page_height * 0.08)
        if anchor is not None:
            footer_candidates.append(anchor.top)
    row_end = min(footer_candidates) if footer_candidates else page_height * 0.72

    name_left = max(0.0, name_header.left - page_width * 0.08)
    name_right = (name_header.cx + spec_header.cx) / 2.0
    spec_left = name_right
    if unit_header is not None:
        spec_right = (spec_header.cx + unit_header.cx) / 2.0
    else:
        spec_right = spec_header.right + page_width * 0.10

    if quantity_header is not None:
        qty_half_width = max(quantity_header.width * 1.5, page_width * 0.035)
        qty_left = quantity_header.cx - qty_half_width
        qty_right = quantity_header.cx + qty_half_width
    else:
        qty_left = qty_right = -1.0

    candidates: list[Token] = []
    for token in tokens:
        if token.cy <= row_start or token.cy >= row_end or is_probable_label(token):
            continue
        in_name = name_left <= token.cx < name_right
        in_spec = spec_left <= token.cx < spec_right
        in_qty = quantity_header is not None and qty_left <= token.cx <= qty_right
        if in_name or in_spec or in_qty:
            candidates.append(token)

    if not candidates:
        warnings.append("表格区域未识别到物资明细，请人工录入。")
        return [], warnings

    typical_height = median([token.height for token in candidates])
    tolerance = max(typical_height * 1.15, page_height * 0.008)
    rows = cluster_rows(candidates, tolerance)

    lines: list[dict] = []
    for row in rows:
        name_tokens = [token for token in row if name_left <= token.cx < name_right]
        spec_tokens = [token for token in row if spec_left <= token.cx < spec_right]
        qty_tokens = [token for token in row if quantity_header is not None and qty_left <= token.cx <= qty_right]
        name, name_score = join_tokens(name_tokens)
        specification, spec_score = join_tokens(spec_tokens)
        quantity_text, qty_score = join_tokens(qty_tokens)
        quantity = numeric_value(quantity_text) if quantity_text else None

        if not name and not specification and quantity is None:
            continue
        confidence_values = [score for score in (name_score, spec_score, qty_score) if score > 0]
        confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
        line_warnings: list[str] = []
        if not name:
            line_warnings.append("物资名称未识别")
        if not specification:
            line_warnings.append("规格型号未识别")
        if quantity is None or quantity <= 0:
            line_warnings.append("应发数量未可靠识别")

        lines.append(
            {
                "itemName": name,
                "specification": specification,
                "quantity": quantity if quantity is not None else 0.0,
                "confidence": round(confidence, 4),
                "warnings": line_warnings,
            }
        )

    if not lines:
        warnings.append("未形成可用物资行，请人工录入。")
    return lines, warnings


def run(image_path: str) -> dict:
    path = Path(image_path)
    if not path.is_file():
        raise RuntimeError("图片文件不存在")

    source_sha256 = sha256_file(path)

    try:
        from rapidocr import RapidOCR
    except Exception as exc:  # pragma: no cover - target environment concern
        raise RuntimeError(
            "OCR运行环境未安装。请安装 rapidocr 与 onnxruntime，或设置 KYLIN_STOCK_OCR_PYTHON 指向已配置的Python环境。"
        ) from exc

    with contextlib.redirect_stdout(sys.stderr):
        engine = RapidOCR()
        result = engine(str(path))

    boxes = getattr(result, "boxes", None)
    txts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if boxes is None or txts is None or scores is None:
        raise RuntimeError("OCR未返回可解析的文字坐标结果")

    tokens: list[Token] = []
    for box, text, score in zip(boxes, txts, scores):
        token = token_from(box, str(text), float(score))
        if token is not None and token.text:
            tokens.append(token)
    if not tokens:
        raise RuntimeError("图片中未识别到文字，请确认扫描清晰度和单据方向")

    page_width = max(token.right for token in tokens)
    page_height = max(token.bottom for token in tokens)
    top_area = page_height * 0.58

    basis_anchor = find_anchor(tokens, ["调拨依据"], max_y=top_area)
    supplier_anchor = find_anchor(tokens, ["供应单位"], max_y=top_area)
    receiver_anchor = find_anchor(tokens, ["接收单位"], max_y=top_area)

    transfer_basis, basis_score = right_value(basis_anchor, tokens, page_width)
    supplier_unit, supplier_score = right_value(supplier_anchor, tokens, page_width)
    receiver_unit, receiver_score = right_value(receiver_anchor, tokens, page_width)
    lines, warnings = extract_table(tokens, page_width, page_height)

    if not transfer_basis:
        warnings.append("调拨依据未可靠识别。")
    if not supplier_unit:
        warnings.append("供应单位未可靠识别。")
    if not receiver_unit:
        warnings.append("接收单位未可靠识别。")

    header_scores = [score for score in (basis_score, supplier_score, receiver_score) if score > 0]
    header_confidence = sum(header_scores) / len(header_scores) if header_scores else 0.0

    return {
        "documentType": "TRANSFER_RECEIVE",
        "sourceSha256": source_sha256,
        "transferBasis": transfer_basis,
        "supplierUnit": supplier_unit,
        "receiverUnit": receiver_unit,
        "headerConfidence": round(header_confidence, 4),
        "lines": lines,
        "warnings": warnings,
        "ocrEngine": "RapidOCR/ONNX Runtime",
        "recognizedTextCount": len(tokens),
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: ocr_worker.py <image-path>", file=sys.stderr)
        return 64
    try:
        payload = run(sys.argv[1])
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(f"OCR识别失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
