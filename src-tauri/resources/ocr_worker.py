#!/usr/bin/env python3
"""Offline OCR worker for fixed-layout transfer/receiving forms.

The worker intentionally returns a conservative draft. It extracts the fields
needed by KylinStock, but never posts inventory by itself. The desktop UI is the
human verification boundary.

For fixed grid forms the preferred path is two-stage OCR:
1. OCR the whole page to locate semantic headers/columns.
2. Detect horizontal table rules and OCR each material cell independently.

This prevents a full-page detector from merging two adjacent material rows into
one text box (for example `粉笔橡皮`). If grid detection is unavailable or not
reliable enough, the older geometry-token parser remains as a safe fallback.
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
    "序号",
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


@dataclass(frozen=True)
class TableLayout:
    name_header: Token
    spec_header: Token
    quantity_header: Token | None
    name_left: float
    name_right: float
    spec_left: float
    spec_right: float
    qty_left: float
    qty_right: float
    row_start: float
    row_end: float


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
    # RapidOCR 3.x returns NumPy arrays for boxes. A NumPy array cannot be used
    # in a boolean expression (`if not box`) when it contains multiple values,
    # so validate it structurally instead.
    if box is None or len(box) < 4:
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
        score=float(score),
        left=left,
        right=right,
        top=top,
        bottom=bottom,
        cx=(left + right) / 2.0,
        cy=(top + bottom) / 2.0,
        width=right - left,
        height=bottom - top,
    )


def tokens_from_result(result) -> list[Token]:
    boxes = getattr(result, "boxes", None)
    txts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if boxes is None or txts is None or scores is None:
        return []

    tokens: list[Token] = []
    for box, text, score in zip(boxes, txts, scores):
        token = token_from(box, str(text), float(score))
        if token is not None and token.text:
            tokens.append(token)
    return tokens


def run_engine(engine, source) -> list[Token]:
    # RapidOCR emits informational logs. stdout is reserved for our single JSON
    # protocol document, so redirect library stdout to stderr for every pass.
    with contextlib.redirect_stdout(sys.stderr):
        result = engine(source)
    return tokens_from_result(result)


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
    # Use exact labels only. Substring matching would incorrectly discard real
    # material names such as “资料袋” or “附件盒”.
    return compact(token.text) in LABEL_WORDS


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
    ordered = sorted(tokens, key=lambda token: (token.top, token.left))
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


def table_layout(tokens: Sequence[Token], page_width: float, page_height: float) -> tuple[TableLayout | None, list[str]]:
    warnings: list[str] = []
    upper_limit = page_height * 0.62
    name_header = find_anchor(tokens, ["名称"], max_y=upper_limit)
    spec_header = find_anchor(tokens, ["规格型号", "规格"], max_y=upper_limit)
    if name_header is None or spec_header is None:
        return None, ["未可靠定位“名称/规格型号”表头，请人工核对明细。"]

    serial_header = find_anchor(
        tokens,
        ["序号"],
        min_y=max(0.0, name_header.cy - page_height * 0.05),
        max_y=name_header.cy + page_height * 0.05,
    )
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
        # The first “数量” under the 应发数 group is the business quantity we
        # need. Choose by proximity to that group rather than by absolute page x.
        quantity_header = min(
            quantity_candidates,
            key=lambda token: abs(token.cx - issued_header.cx) + abs(token.cy - issued_header.cy) * 0.35,
        )
    elif quantity_candidates:
        quantity_header = min(quantity_candidates, key=lambda token: token.cx)
    else:
        warnings.append("未可靠定位“应发数量”列，请人工填写数量。")

    header_bottom = max(
        name_header.bottom,
        spec_header.bottom,
        quantity_header.bottom if quantity_header else spec_header.bottom,
    )
    row_start = header_bottom + max(name_header.height, spec_header.height) * 0.20

    footer_candidates = []
    for label in ("调拨单位", "供应单位", "接收单位"):
        anchor = find_anchor(tokens, [label], min_y=row_start + page_height * 0.08)
        if anchor is not None:
            footer_candidates.append(anchor.top)
    row_end = min(footer_candidates) if footer_candidates else page_height * 0.74

    # Exclude the serial-number column. The earlier implementation extended the
    # name column leftward by 8% of the page, which is why a real scan produced
    # `12粉笔橡皮` instead of two material names.
    if serial_header is not None and serial_header.cx < name_header.cx:
        name_left = (serial_header.cx + name_header.cx) / 2.0
    else:
        name_left = max(0.0, name_header.left - page_width * 0.025)
    name_right = (name_header.cx + spec_header.cx) / 2.0

    spec_left = name_right
    if unit_header is not None and unit_header.cx > spec_header.cx:
        spec_right = (spec_header.cx + unit_header.cx) / 2.0
    else:
        spec_right = min(page_width, spec_header.right + page_width * 0.10)

    if quantity_header is not None:
        same_header_row = [
            token
            for token in tokens
            if abs(token.cy - quantity_header.cy) <= page_height * 0.03
            and compact(token.text) in {"等级", "数量"}
        ]
        peers = sorted({token.cx for token in same_header_row})
        left_peers = [x for x in peers if x < quantity_header.cx - 1]
        right_peers = [x for x in peers if x > quantity_header.cx + 1]
        qty_left = (
            (max(left_peers) + quantity_header.cx) / 2.0
            if left_peers
            else quantity_header.cx - max(quantity_header.width * 1.6, page_width * 0.025)
        )
        qty_right = (
            (quantity_header.cx + min(right_peers)) / 2.0
            if right_peers
            else quantity_header.cx + max(quantity_header.width * 1.6, page_width * 0.025)
        )
    else:
        qty_left = qty_right = -1.0

    return TableLayout(
        name_header=name_header,
        spec_header=spec_header,
        quantity_header=quantity_header,
        name_left=name_left,
        name_right=name_right,
        spec_left=spec_left,
        spec_right=spec_right,
        qty_left=qty_left,
        qty_right=qty_right,
        row_start=row_start,
        row_end=row_end,
    ), warnings


def cluster_positions(values: Sequence[float], tolerance: float) -> list[float]:
    clusters: list[list[float]] = []
    for value in sorted(values):
        if not clusters or value - sum(clusters[-1]) / len(clusters[-1]) > tolerance:
            clusters.append([value])
        else:
            clusters[-1].append(value)
    return [sum(cluster) / len(cluster) for cluster in clusters]


def select_row_bands(
    horizontal_lines: Sequence[float],
    row_start: float,
    row_end: float,
    page_height: float,
) -> list[tuple[float, float]]:
    """Turn detected horizontal rules into material row bands.

    Keeping this pure makes the critical row-separation rule unit-testable even
    on CI runners without OpenCV.
    """
    tolerance = max(3.0, page_height * 0.004)
    lines = cluster_positions(horizontal_lines, tolerance)
    near = [
        y
        for y in lines
        if row_start - page_height * 0.025 <= y <= row_end + page_height * 0.015
    ]
    if len(near) < 2:
        return []

    # First rule at/after the header is the top edge of data row 1.
    top_candidates = [y for y in near if y >= row_start - page_height * 0.018]
    if not top_candidates:
        return []
    first = min(top_candidates)
    boundaries = [y for y in near if y >= first - tolerance]
    minimum_height = max(10.0, page_height * 0.012)

    bands: list[tuple[float, float]] = []
    for top, bottom in zip(boundaries, boundaries[1:]):
        if bottom - top >= minimum_height:
            bands.append((top, bottom))
    return bands[:200]


def detect_horizontal_table_lines(image, layout: TableLayout) -> list[float]:
    try:
        import cv2
        import numpy as np
    except Exception:
        return []

    if image is None or not hasattr(image, "shape") or len(image.shape) < 2:
        return []
    height, width = image.shape[:2]
    if height <= 0 or width <= 0:
        return []

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    min_length = max(80, int((layout.qty_right - layout.name_left) * 0.65))
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180.0,
        threshold=max(40, min_length // 6),
        minLineLength=min_length,
        maxLineGap=max(12, int(width * 0.02)),
    )
    if lines is None:
        return []

    y_values: list[float] = []
    left_needed = max(0.0, layout.name_left - width * 0.06)
    right_needed = min(float(width), max(layout.spec_right, layout.qty_right) + width * 0.03)
    max_slope = 0.08  # tolerate modest camera skew/perspective

    for raw in lines:
        x1, y1, x2, y2 = [float(value) for value in raw[0]]
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        if dx <= 1 or dy / dx > max_slope:
            continue
        if max(x1, x2) < right_needed or min(x1, x2) > left_needed:
            continue
        y_mid = (y1 + y2) / 2.0
        if layout.row_start - height * 0.04 <= y_mid <= layout.row_end + height * 0.02:
            y_values.append(y_mid)

    return cluster_positions(y_values, max(3.0, height * 0.004))


def crop_cell(image, left: float, right: float, top: float, bottom: float):
    try:
        import cv2
    except Exception:
        return None
    if image is None:
        return None
    height, width = image.shape[:2]
    # Stay inside grid rules; a few pixels of white margin are added afterward.
    inset_x = max(2, int(width * 0.0015))
    inset_y = max(2, int(height * 0.0015))
    x1 = max(0, min(width - 1, int(round(left)) + inset_x))
    x2 = max(x1 + 1, min(width, int(round(right)) - inset_x))
    y1 = max(0, min(height - 1, int(round(top)) + inset_y))
    y2 = max(y1 + 1, min(height, int(round(bottom)) - inset_y))
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        return None

    # Upscale short cells so small Chinese characters/digits are not penalized.
    target_height = 96
    if crop.shape[0] < target_height:
        scale = target_height / max(1, crop.shape[0])
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    crop = cv2.copyMakeBorder(crop, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    return crop


def ocr_cell(engine, image, left: float, right: float, top: float, bottom: float) -> tuple[str, float]:
    crop = crop_cell(image, left, right, top, bottom)
    if crop is None:
        return "", 0.0
    try:
        tokens = run_engine(engine, crop)
    except Exception:
        return "", 0.0
    return join_tokens(tokens)


def extract_table_by_grid(
    engine,
    image,
    layout: TableLayout,
    page_height: float,
) -> tuple[list[dict], list[str]]:
    horizontal_lines = detect_horizontal_table_lines(image, layout)
    bands = select_row_bands(horizontal_lines, layout.row_start, layout.row_end, page_height)
    if not bands:
        return [], ["未可靠检测到表格横线，已回退到整页文字框解析。"]

    lines: list[dict] = []
    for top, bottom in bands:
        name, name_score = ocr_cell(engine, image, layout.name_left, layout.name_right, top, bottom)
        specification, spec_score = ocr_cell(engine, image, layout.spec_left, layout.spec_right, top, bottom)
        if layout.quantity_header is not None:
            quantity_text, qty_score = ocr_cell(engine, image, layout.qty_left, layout.qty_right, top, bottom)
            quantity = numeric_value(quantity_text) if quantity_text else None
        else:
            quantity_text, qty_score, quantity = "", 0.0, None

        # Empty rows are common in the printed template; do not surface them.
        if not name and not specification and quantity is None:
            continue

        confidence_values = [score for score in (name_score, spec_score, qty_score) if score > 0]
        confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
        row_warnings: list[str] = []
        if not name:
            row_warnings.append("物资名称未识别")
        if not specification:
            row_warnings.append("规格型号未识别")
        if quantity is None or quantity <= 0:
            row_warnings.append("应发数量未可靠识别")

        lines.append(
            {
                "itemName": name,
                "specification": specification,
                "quantity": quantity if quantity is not None else 0.0,
                "confidence": round(confidence, 4),
                "warnings": row_warnings,
            }
        )

    if not lines:
        return [], ["表格线已检测，但各数据行未识别到内容，已回退到整页文字框解析。"]
    return lines, []


def extract_table_from_tokens(
    tokens: Sequence[Token],
    layout: TableLayout,
    page_height: float,
) -> tuple[list[dict], list[str]]:
    candidates: list[Token] = []
    for token in tokens:
        if token.cy <= layout.row_start or token.cy >= layout.row_end or is_probable_label(token):
            continue
        in_name = layout.name_left <= token.cx < layout.name_right
        in_spec = layout.spec_left <= token.cx < layout.spec_right
        in_qty = (
            layout.quantity_header is not None
            and layout.qty_left <= token.cx <= layout.qty_right
        )
        if in_name or in_spec or in_qty:
            candidates.append(token)

    if not candidates:
        return [], ["表格区域未识别到物资明细，请人工录入。"]

    typical_height = median([token.height for token in candidates])
    # Conservative fallback: do not merge rows simply because a detector emitted
    # one unusually tall box. Grid-cell OCR is preferred for real fixed forms.
    tolerance = max(min(typical_height * 0.72, page_height * 0.018), page_height * 0.006)
    rows = cluster_rows(candidates, tolerance)

    lines: list[dict] = []
    for row in rows:
        name_tokens = [token for token in row if layout.name_left <= token.cx < layout.name_right]
        spec_tokens = [token for token in row if layout.spec_left <= token.cx < layout.spec_right]
        qty_tokens = [
            token
            for token in row
            if layout.quantity_header is not None and layout.qty_left <= token.cx <= layout.qty_right
        ]
        name, name_score = join_tokens(name_tokens)
        specification, spec_score = join_tokens(spec_tokens)
        quantity_text, qty_score = join_tokens(qty_tokens)
        quantity = numeric_value(quantity_text) if quantity_text else None

        if not name and not specification and quantity is None:
            continue
        confidence_values = [score for score in (name_score, spec_score, qty_score) if score > 0]
        confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
        row_warnings: list[str] = []
        if not name:
            row_warnings.append("物资名称未识别")
        if not specification:
            row_warnings.append("规格型号未识别")
        if quantity is None or quantity <= 0:
            row_warnings.append("应发数量未可靠识别")
        lines.append(
            {
                "itemName": name,
                "specification": specification,
                "quantity": quantity if quantity is not None else 0.0,
                "confidence": round(confidence, 4),
                "warnings": row_warnings,
            }
        )

    if not lines:
        return [], ["未形成可用物资行，请人工录入。"]
    return lines, []


def load_image(path: Path):
    try:
        import cv2
    except Exception:
        return None
    return cv2.imread(str(path), cv2.IMREAD_COLOR)


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

    engine = RapidOCR()
    tokens = run_engine(engine, str(path))
    if not tokens:
        raise RuntimeError("图片中未识别到文字，请确认扫描清晰度和单据方向")

    image = load_image(path)
    if image is not None:
        page_height, page_width = image.shape[:2]
        page_height = float(page_height)
        page_width = float(page_width)
    else:
        page_width = max(token.right for token in tokens)
        page_height = max(token.bottom for token in tokens)

    top_area = page_height * 0.58
    basis_anchor = find_anchor(tokens, ["调拨依据"], max_y=top_area)
    supplier_anchor = find_anchor(tokens, ["供应单位"], max_y=top_area)
    receiver_anchor = find_anchor(tokens, ["接收单位"], max_y=top_area)

    transfer_basis, basis_score = right_value(basis_anchor, tokens, page_width)
    supplier_unit, supplier_score = right_value(supplier_anchor, tokens, page_width)
    receiver_unit, receiver_score = right_value(receiver_anchor, tokens, page_width)

    layout, layout_warnings = table_layout(tokens, page_width, page_height)
    warnings = list(layout_warnings)
    lines: list[dict] = []
    parser_mode = "token-fallback"

    if layout is not None:
        if image is not None:
            grid_lines, grid_warnings = extract_table_by_grid(engine, image, layout, page_height)
            if grid_lines:
                lines = grid_lines
                parser_mode = "grid-cell"
            else:
                warnings.extend(grid_warnings)
        if not lines:
            token_lines, token_warnings = extract_table_from_tokens(tokens, layout, page_height)
            lines = token_lines
            warnings.extend(token_warnings)

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
        "parserMode": parser_mode,
        "recognizedTextCount": len(tokens),
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: ocr_worker.py <image-path>", file=sys.stderr)
        return 64
    try:
        payload = run(sys.argv[1])
        # stdout is a UTF-8 JSON protocol, independent of the Windows console
        # code page. Rust also launches us with PYTHONUTF8/PYTHONIOENCODING set.
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8", errors="replace"
        )
        sys.stdout.buffer.write(encoded + b"\n")
        sys.stdout.buffer.flush()
        return 0
    except Exception as exc:
        message = f"OCR识别失败：{exc}".encode("utf-8", errors="replace")
        sys.stderr.buffer.write(message + b"\n")
        sys.stderr.buffer.flush()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
