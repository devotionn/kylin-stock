#!/usr/bin/env python3
"""Offline OCR worker for fixed-layout transfer/receiving forms.

The worker returns a conservative draft only. Inventory mutation remains behind
human review in the desktop application.

For the fixed transfer/receiving form we intentionally prefer already-recognized
full-page OCR tokens for structured fields. Physical grid detection is an
auxiliary geometry signal, not a prerequisite: a photographed or screen-captured
form may contain fragmented horizontal rules even when the text OCR is excellent.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass, replace
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


def required_row_confidence(
    name_score: float,
    spec_score: float,
    qty_score: float,
    quantity_ok: bool,
) -> float:
    confidence = (
        max(0.0, min(1.0, name_score))
        + max(0.0, min(1.0, spec_score))
        + max(0.0, min(1.0, qty_score))
    ) / 3.0
    if not quantity_ok:
        confidence = min(confidence, 0.65)
    return confidence


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


def synthetic_quantity_token(
    issued_header: Token,
    actual_header: Token,
    actual_quantity: Token | None,
    spec_header: Token,
) -> tuple[Token, float]:
    """Infer the issued-quantity child when OCR only sees the mirrored actual child.

    The printed form repeats the same two-child structure under 应发数 and 实发数.
    If the left child label “数量” is missed but the right child is recognized, the
    mirrored offset is more reliable than accidentally selecting the actual column.
    """
    group_gap = max(1.0, actual_header.cx - issued_header.cx)
    if actual_quantity is not None:
        center = issued_header.cx + (actual_quantity.cx - actual_header.cx)
        width = max(18.0, actual_quantity.width)
        height = max(12.0, actual_quantity.height)
        cy = actual_quantity.cy
        score = min(issued_header.score, actual_header.score, actual_quantity.score) * 0.92
    else:
        center = issued_header.cx + group_gap * 0.25
        width = max(18.0, group_gap * 0.28)
        height = max(12.0, spec_header.height)
        cy = spec_header.cy
        score = min(issued_header.score, actual_header.score) * 0.80
    half_width = max(group_gap * 0.25, width * 0.75)
    return (
        Token(
            text="数量",
            score=score,
            left=center - width / 2.0,
            right=center + width / 2.0,
            top=cy - height / 2.0,
            bottom=cy + height / 2.0,
            cx=center,
            cy=cy,
            width=width,
            height=height,
        ),
        half_width,
    )


def table_layout(tokens: Sequence[Token], page_width: float, page_height: float) -> tuple[TableLayout | None, list[str]]:
    warnings: list[str] = []
    upper_limit = page_height * 0.62
    name_header = find_anchor(tokens, ["名称"], max_y=upper_limit)
    spec_header = find_anchor(tokens, ["规格型号", "规格"], max_y=upper_limit)
    if name_header is None or spec_header is None:
        return None, ["未可靠定位“名称/规格型号”表头，请人工核对明细。"]

    header_min_y = max(0.0, spec_header.cy - page_height * 0.055)
    header_max_y = spec_header.cy + page_height * 0.055
    serial_header = find_anchor(
        tokens,
        ["序号"],
        min_y=max(0.0, name_header.cy - page_height * 0.05),
        max_y=name_header.cy + page_height * 0.05,
    )
    unit_header = exact_header_near(tokens, "单位", spec_header, page_height, require_right=True)
    issued_header = find_anchor(tokens, ["应发数", "应发"], min_y=header_min_y, max_y=header_max_y)
    actual_header = find_anchor(tokens, ["实发数", "实发"], min_y=header_min_y, max_y=header_max_y)

    quantity_candidates = [
        token
        for token in tokens
        if compact(token.text) == "数量"
        and token.cy >= min(name_header.cy, spec_header.cy) - page_height * 0.035
        and token.cy <= max(name_header.cy, spec_header.cy) + page_height * 0.075
        and token.cx > spec_header.cx
    ]

    quantity_header: Token | None = None
    inferred_half_width: float | None = None
    if issued_header is not None and actual_header is not None and actual_header.cx > issued_header.cx:
        split = (issued_header.cx + actual_header.cx) / 2.0
        issued_candidates = [token for token in quantity_candidates if token.cx < split]
        actual_candidates = [token for token in quantity_candidates if token.cx >= split]
        expected = issued_header.cx + (actual_header.cx - issued_header.cx) * 0.25
        if issued_candidates:
            quantity_header = min(issued_candidates, key=lambda token: abs(token.cx - expected))
        else:
            actual_quantity = (
                min(actual_candidates, key=lambda token: abs(token.cx - actual_header.cx))
                if actual_candidates
                else None
            )
            quantity_header, inferred_half_width = synthetic_quantity_token(
                issued_header, actual_header, actual_quantity, spec_header
            )
    elif quantity_candidates and issued_header is not None:
        quantity_header = min(quantity_candidates, key=lambda token: abs(token.cx - issued_header.cx))
    elif quantity_candidates:
        quantity_header = min(quantity_candidates, key=lambda token: token.cx)
    elif issued_header is not None and actual_header is not None and actual_header.cx > issued_header.cx:
        quantity_header, inferred_half_width = synthetic_quantity_token(
            issued_header, actual_header, None, spec_header
        )
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

    if quantity_header is not None and inferred_half_width is not None:
        qty_left = quantity_header.cx - inferred_half_width
        qty_right = quantity_header.cx + inferred_half_width
    elif quantity_header is not None:
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


def recover_quantity_from_page_tokens(
    tokens: Sequence[Token],
    layout: TableLayout,
    top: float,
    bottom: float,
    page_width: float,
) -> tuple[float | None, float]:
    if layout.quantity_header is None:
        return None, 0.0

    row_margin = max(4.0, (bottom - top) * 0.16)
    strict_width = max(1.0, layout.qty_right - layout.qty_left)
    broad_half = max(strict_width * 1.5, page_width * 0.035)
    center = (
        (layout.qty_left + layout.qty_right) / 2.0
        if layout.qty_right > layout.qty_left
        else layout.quantity_header.cx
    )
    broad_left = center - broad_half
    broad_right = center + broad_half

    candidates: list[tuple[int, float, float, float, Token]] = []
    for token in tokens:
        if token.cy < top - row_margin or token.cy > bottom + row_margin:
            continue
        if token.cx < broad_left or token.cx > broad_right:
            continue
        if is_probable_label(token):
            continue
        value = numeric_value(token.text)
        if value is None or value <= 0:
            continue
        strict_rank = 0 if layout.qty_left <= token.cx <= layout.qty_right else 1
        candidates.append(
            (
                strict_rank,
                abs(token.cx - center),
                abs(token.cy - (top + bottom) / 2.0),
                -token.score,
                token,
            )
        )

    if not candidates:
        return None, 0.0
    candidates.sort(key=lambda item: item[:4])
    token = candidates[0][4]
    return numeric_value(token.text), token.score


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
    tolerance = max(3.0, page_height * 0.004)
    lines = cluster_positions(horizontal_lines, tolerance)
    near = [
        y
        for y in lines
        if row_start - page_height * 0.025 <= y <= row_end + page_height * 0.015
    ]
    if len(near) < 2:
        return []

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


def flatten_hough_values(value) -> list[object]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        flattened: list[object] = []
        for item in value:
            flattened.extend(flatten_hough_values(item))
        return flattened
    return [value]


def hough_segments(lines) -> list[tuple[float, float, float, float]]:
    if lines is None:
        return []
    values = flatten_hough_values(lines)
    if len(values) < 4 or len(values) % 4 != 0:
        return []
    segments: list[tuple[float, float, float, float]] = []
    for index in range(0, len(values), 4):
        try:
            x1, y1, x2, y2 = (float(value) for value in values[index : index + 4])
        except (TypeError, ValueError):
            continue
        segments.append((x1, y1, x2, y2))
    return segments


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
    min_length = max(80, int((layout.qty_right - layout.name_left) * 0.45))
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180.0,
        threshold=max(32, min_length // 8),
        minLineLength=min_length,
        maxLineGap=max(12, int(width * 0.025)),
    )
    if lines is None:
        return []

    y_values: list[float] = []
    max_slope = 0.08
    for x1, y1, x2, y2 in hough_segments(lines):
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        if dx <= 1 or dy / dx > max_slope:
            continue
        y_mid = (y1 + y2) / 2.0
        if layout.row_start - height * 0.04 <= y_mid <= layout.row_end + height * 0.02:
            y_values.append(y_mid)
    return cluster_positions(y_values, max(3.0, height * 0.004))


def detect_vertical_table_lines(
    image,
    layout: TableLayout,
    bands: Sequence[tuple[float, float]],
) -> list[float]:
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

    if bands:
        body_top = min(top for top, _ in bands)
        body_bottom = max(bottom for _, bottom in bands)
    else:
        body_top = layout.row_start
        body_bottom = layout.row_end
    body_height = max(1.0, body_bottom - body_top)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    min_length = max(45, int(body_height * 0.32))
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180.0,
        threshold=max(32, min_length // 3),
        minLineLength=min_length,
        maxLineGap=max(10, int(height * 0.018)),
    )
    if lines is None:
        return []

    target_center = layout.quantity_header.cx if layout.quantity_header is not None else 0.0
    search_half = max(width * 0.16, max(1.0, layout.qty_right - layout.qty_left) * 4.0)
    search_left = max(0.0, target_center - search_half)
    search_right = min(float(width), target_center + search_half)

    x_values: list[float] = []
    for x1, y1, x2, y2 in hough_segments(lines):
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        if dy <= 1 or dx / dy > 0.12:
            continue
        if max(y1, y2) < body_top - height * 0.025 or min(y1, y2) > body_bottom + height * 0.025:
            continue
        x_mid = (x1 + x2) / 2.0
        if search_left <= x_mid <= search_right:
            x_values.append(x_mid)
    return cluster_positions(x_values, max(3.0, width * 0.004))


def snap_quantity_bounds(
    vertical_lines: Sequence[float],
    layout: TableLayout,
    page_width: float,
) -> tuple[float, float]:
    if layout.quantity_header is None:
        return layout.qty_left, layout.qty_right
    center = layout.quantity_header.cx
    clustered = cluster_positions(vertical_lines, max(3.0, page_width * 0.004))
    lefts = [x for x in clustered if x < center - 2.0]
    rights = [x for x in clustered if x > center + 2.0]
    if not lefts or not rights:
        return layout.qty_left, layout.qty_right

    left = max(lefts)
    right = min(rights)
    width = right - left
    min_width = max(18.0, page_width * 0.018)
    max_width = page_width * 0.12
    if width < min_width or width > max_width:
        return layout.qty_left, layout.qty_right
    relative = (center - left) / width
    if relative < 0.12 or relative > 0.88:
        return layout.qty_left, layout.qty_right
    return left, right


def crop_cell(image, left: float, right: float, top: float, bottom: float):
    try:
        import cv2
    except Exception:
        return None
    if image is None:
        return None
    height, width = image.shape[:2]
    inset_x = max(2, int(width * 0.0015))
    inset_y = max(2, int(height * 0.0015))
    x1 = max(0, min(width - 1, int(round(left)) + inset_x))
    x2 = max(x1 + 1, min(width, int(round(right)) - inset_x))
    y1 = max(0, min(height - 1, int(round(top)) + inset_y))
    y2 = max(y1 + 1, min(height, int(round(bottom)) - inset_y))
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        return None
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


def ocr_numeric_cell(
    engine,
    image,
    layout: TableLayout,
    top: float,
    bottom: float,
    page_width: float,
) -> tuple[float | None, float]:
    if layout.quantity_header is None:
        return None, 0.0
    strict_text, strict_score = ocr_cell(engine, image, layout.qty_left, layout.qty_right, top, bottom)
    strict_value = numeric_value(strict_text) if strict_text else None
    if strict_value is not None and strict_value > 0:
        return strict_value, strict_score

    center = (layout.qty_left + layout.qty_right) / 2.0
    strict_width = max(1.0, layout.qty_right - layout.qty_left)
    half = max(strict_width * 1.15, page_width * 0.025)
    crop = crop_cell(image, center - half, center + half, top, bottom)
    if crop is None:
        return None, 0.0
    try:
        tokens = run_engine(engine, crop)
    except Exception:
        tokens = []
    numeric_tokens = [
        (numeric_value(token.text), token.score, token)
        for token in tokens
        if numeric_value(token.text) is not None and numeric_value(token.text) > 0
    ]
    if numeric_tokens:
        target = crop.shape[1] / 2.0
        numeric_tokens.sort(key=lambda item: (abs(item[2].cx - target), -item[1]))
        return numeric_tokens[0][0], numeric_tokens[0][1]

    try:
        import cv2
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        binary = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        tokens = run_engine(engine, binary)
    except Exception:
        return None, 0.0
    numeric_tokens = [
        (numeric_value(token.text), token.score, token)
        for token in tokens
        if numeric_value(token.text) is not None and numeric_value(token.text) > 0
    ]
    if not numeric_tokens:
        return None, 0.0
    target = binary.shape[1] / 2.0
    numeric_tokens.sort(key=lambda item: (abs(item[2].cx - target), -item[1]))
    return numeric_tokens[0][0], numeric_tokens[0][1]


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
        in_qty = layout.quantity_header is not None and layout.qty_left <= token.cx <= layout.qty_right
        if in_name or in_spec or in_qty:
            candidates.append(token)

    if not candidates:
        return [], ["表格区域未识别到物资明细，请人工录入。"]

    typical_height = median([token.height for token in candidates])
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
        quantity_ok = quantity is not None and quantity > 0
        confidence = required_row_confidence(name_score, spec_score, qty_score, quantity_ok)
        row_warnings: list[str] = []
        if not name:
            row_warnings.append("物资名称未识别")
        if not specification:
            row_warnings.append("规格型号未识别")
        if not quantity_ok:
            row_warnings.append("应发数量未可靠识别")
        lines.append(
            {
                "itemName": name,
                "specification": specification,
                "quantity": quantity if quantity_ok else 0.0,
                "confidence": round(confidence, 4),
                "warnings": row_warnings,
            }
        )

    if not lines:
        return [], ["未形成可用物资行，请人工录入。"]
    return lines, []


def row_bands_from_token_lines(
    lines: Sequence[dict],
    tokens: Sequence[Token],
    layout: TableLayout,
    page_height: float,
) -> list[tuple[float, float]]:
    """Build approximate row bands from recognized name/spec token centers.

    This is used only as a cell-OCR fallback when printed horizontal rules are
    fragmented. It never changes inventory by itself.
    """
    row_tokens = [
        token
        for token in tokens
        if layout.row_start < token.cy < layout.row_end
        and (
            layout.name_left <= token.cx < layout.name_right
            or layout.spec_left <= token.cx < layout.spec_right
        )
        and not is_probable_label(token)
    ]
    if not row_tokens:
        return []
    centers = cluster_positions([token.cy for token in row_tokens], max(6.0, page_height * 0.012))
    if not centers:
        return []
    bands: list[tuple[float, float]] = []
    for index, center in enumerate(centers):
        prev_center = centers[index - 1] if index > 0 else None
        next_center = centers[index + 1] if index + 1 < len(centers) else None
        top = (prev_center + center) / 2.0 if prev_center is not None else center - page_height * 0.018
        bottom = (center + next_center) / 2.0 if next_center is not None else center + page_height * 0.018
        bands.append((max(layout.row_start, top), min(layout.row_end, bottom)))
    return bands[: max(len(lines), 1)]


def recover_missing_quantities_with_cells(
    engine,
    image,
    page_tokens: Sequence[Token],
    layout: TableLayout,
    lines: list[dict],
    page_width: float,
    page_height: float,
) -> list[dict]:
    if image is None or not lines or layout.quantity_header is None:
        return lines
    bands = row_bands_from_token_lines(lines, page_tokens, layout, page_height)
    if len(bands) < len(lines):
        return lines

    repaired: list[dict] = []
    for line, (top, bottom) in zip(lines, bands):
        if line.get("quantity", 0) and float(line["quantity"]) > 0:
            repaired.append(line)
            continue
        quantity, score = recover_quantity_from_page_tokens(page_tokens, layout, top, bottom, page_width)
        if quantity is None or quantity <= 0:
            quantity, score = ocr_numeric_cell(engine, image, layout, top, bottom, page_width)
        if quantity is None or quantity <= 0:
            repaired.append(line)
            continue
        updated = dict(line)
        updated["quantity"] = quantity
        updated["warnings"] = [warning for warning in updated.get("warnings", []) if "数量" not in warning]
        updated["confidence"] = round(
            max(float(updated.get("confidence", 0.0)), min(1.0, 0.67 + score / 3.0)), 4
        )
        repaired.append(updated)
    return repaired


def load_image(path: Path):
    try:
        import cv2
        import numpy as np
    except Exception:
        return None
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def run(image_path: str) -> dict:
    path = Path(image_path)
    if not path.is_file():
        raise RuntimeError("图片文件不存在")

    source_sha256 = sha256_file(path)
    try:
        from rapidocr import RapidOCR
    except Exception as exc:
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
        effective_layout = layout
        if image is not None and layout.quantity_header is not None:
            vertical_lines = detect_vertical_table_lines(image, layout, [])
            qty_left, qty_right = snap_quantity_bounds(vertical_lines, layout, page_width)
            effective_layout = replace(layout, qty_left=qty_left, qty_right=qty_right)
            if (qty_left, qty_right) != (layout.qty_left, layout.qty_right):
                parser_mode = "token-geometry+grid-snapped-quantity"

        token_lines, token_warnings = extract_table_from_tokens(tokens, effective_layout, page_height)
        lines = token_lines
        warnings.extend(token_warnings)

        if lines and image is not None and any(float(line.get("quantity", 0.0)) <= 0 for line in lines):
            lines = recover_missing_quantities_with_cells(
                engine,
                image,
                tokens,
                effective_layout,
                lines,
                page_width,
                page_height,
            )
            if all(float(line.get("quantity", 0.0)) > 0 for line in lines):
                parser_mode = "token-geometry+cell-quantity-fallback"

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
