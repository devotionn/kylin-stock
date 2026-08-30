#!/usr/bin/env python3
"""Print fixed-form OCR/grid diagnostics for one real scan without mutating inventory."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "src-tauri" / "resources" / "ocr_worker.py"
SPEC = importlib.util.spec_from_file_location("kylin_stock_ocr_worker_diag", WORKER)
if SPEC is None or SPEC.loader is None:
    raise SystemExit("cannot load ocr_worker.py")
ocr = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ocr
SPEC.loader.exec_module(ocr)


def token_payload(token):
    if token is None:
        return None
    return {
        "text": token.text,
        "score": round(float(token.score), 4),
        "cx": round(float(token.cx), 1),
        "cy": round(float(token.cy), 1),
        "left": round(float(token.left), 1),
        "right": round(float(token.right), 1),
        "top": round(float(token.top), 1),
        "bottom": round(float(token.bottom), 1),
    }


def main() -> int:
    if len(sys.argv) != 2:
        print('用法: python scripts/diagnose-ocr.py "扫描图片完整路径"', file=sys.stderr)
        return 64

    path = Path(sys.argv[1]).expanduser()
    if not path.is_file():
        print(f"图片不存在: {path}", file=sys.stderr)
        return 2

    from rapidocr import RapidOCR

    engine = RapidOCR()
    page_tokens = ocr.run_engine(engine, str(path))
    image = ocr.load_image(path)
    if image is None:
        print(json.dumps({"error": "OpenCV load_image returned None", "path": str(path)}, ensure_ascii=False, indent=2))
        return 3

    height, width = image.shape[:2]
    layout, layout_warnings = ocr.table_layout(page_tokens, float(width), float(height))
    report = {
        "path": str(path),
        "image": {"width": int(width), "height": int(height)},
        "recognizedTextCount": len(page_tokens),
        "layoutWarnings": layout_warnings,
    }

    if layout is None:
        report["layout"] = None
        report["tokens"] = [token_payload(token) for token in page_tokens]
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    report["layout"] = {
        "nameHeader": token_payload(layout.name_header),
        "specHeader": token_payload(layout.spec_header),
        "quantityHeader": token_payload(layout.quantity_header),
        "nameBounds": [round(layout.name_left, 1), round(layout.name_right, 1)],
        "specBounds": [round(layout.spec_left, 1), round(layout.spec_right, 1)],
        "initialQuantityBounds": [round(layout.qty_left, 1), round(layout.qty_right, 1)],
        "rowRange": [round(layout.row_start, 1), round(layout.row_end, 1)],
    }

    numeric_tokens = []
    for token in page_tokens:
        value = ocr.numeric_value(token.text)
        if value is None:
            continue
        numeric_tokens.append({**token_payload(token), "value": value})
    report["numericTokens"] = numeric_tokens

    horizontal = ocr.detect_horizontal_table_lines(image, layout)
    bands = ocr.select_row_bands(horizontal, layout.row_start, layout.row_end, float(height))
    vertical = ocr.detect_vertical_table_lines(image, layout, bands)
    qty_left, qty_right = ocr.snap_quantity_bounds(vertical, layout, float(width))
    effective = ocr.replace(layout, qty_left=qty_left, qty_right=qty_right)

    report["grid"] = {
        "horizontalCount": len(horizontal),
        "horizontalY": [round(value, 1) for value in horizontal],
        "bandCount": len(bands),
        "bands": [[round(top, 1), round(bottom, 1)] for top, bottom in bands],
        "verticalCount": len(vertical),
        "verticalX": [round(value, 1) for value in vertical],
        "snappedQuantityBounds": [round(qty_left, 1), round(qty_right, 1)],
    }

    row_reports = []
    for index, (top, bottom) in enumerate(bands, start=1):
        name, name_score = ocr.ocr_cell(engine, image, layout.name_left, layout.name_right, top, bottom)
        specification, spec_score = ocr.ocr_cell(engine, image, layout.spec_left, layout.spec_right, top, bottom)
        page_quantity, page_qty_score = ocr.recover_quantity_from_page_tokens(
            page_tokens, effective, top, bottom, float(width)
        )
        cell_quantity, cell_qty_score = ocr.ocr_numeric_cell(
            engine, image, effective, top, bottom, float(width)
        )
        row_reports.append({
            "row": index,
            "top": round(top, 1),
            "bottom": round(bottom, 1),
            "name": name,
            "nameScore": round(float(name_score), 4),
            "specification": specification,
            "specScore": round(float(spec_score), 4),
            "pageTokenQuantity": page_quantity,
            "pageTokenQuantityScore": round(float(page_qty_score), 4),
            "cellOcrQuantity": cell_quantity,
            "cellOcrQuantityScore": round(float(cell_qty_score), 4),
        })
    report["rows"] = row_reports

    report["interpretation"] = (
        "horizontalCount/bandCount < 2 => grid path cannot run; "
        "bands present but quantities missing => inspect numericTokens, verticalX and snappedQuantityBounds"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
