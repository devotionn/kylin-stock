from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "src-tauri" / "resources" / "ocr_worker.py"
SPEC = importlib.util.spec_from_file_location("kylin_stock_ocr_worker", WORKER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load OCR worker")
ocr = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ocr
SPEC.loader.exec_module(ocr)


def token(text: str, x: float, y: float, width: float = 80, height: float = 20, score: float = 0.98):
    return ocr.Token(
        text=text,
        score=score,
        left=x,
        right=x + width,
        top=y,
        bottom=y + height,
        cx=x + width / 2,
        cy=y + height / 2,
        width=width,
        height=height,
    )


class NumpyLikeBox(list):
    """Mimic NumPy's refusal to coerce multi-value arrays to bool."""

    def __bool__(self):
        raise ValueError("truth value of an array with more than one element is ambiguous")


class FixedTransferFormParserTest(unittest.TestCase):
    def test_token_from_accepts_numpy_like_box_without_boolean_coercion(self):
        box = NumpyLikeBox([[10, 20], [110, 20], [110, 40], [10, 40]])

        parsed = ocr.token_from(box, "粉笔", 0.98)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.text, "粉笔")
        self.assertEqual(parsed.left, 10.0)
        self.assertEqual(parsed.right, 110.0)
        self.assertEqual(parsed.top, 20.0)
        self.assertEqual(parsed.bottom, 40.0)

    def test_extracts_customer_target_fields_from_geometry(self):
        tokens = [
            token("调拨依据", 560, 95, 90),
            token("2026年计划", 675, 95, 120),
            token("供应单位", 40, 180, 90),
            token("仓库", 150, 180, 70),
            token("接收单位", 40, 220, 90),
            token("超市", 150, 220, 70),
            token("名称", 90, 300, 70),
            token("规格型号", 250, 300, 100),
            token("单位", 410, 300, 60),
            token("应发数", 510, 285, 80),
            token("数量", 550, 315, 60),
            token("粉笔", 105, 370, 70),
            token("10.9型粉笔", 245, 370, 110),
            token("1000", 555, 370, 70),
            token("橡皮", 105, 420, 70),
            token("20型橡皮", 250, 420, 105),
            token("1000", 555, 420, 70),
            token("调拨单位", 40, 610, 90),
        ]

        basis_anchor = ocr.find_anchor(tokens, ["调拨依据"], max_y=580)
        supplier_anchor = ocr.find_anchor(tokens, ["供应单位"], max_y=580)
        receiver_anchor = ocr.find_anchor(tokens, ["接收单位"], max_y=580)

        basis, _ = ocr.right_value(basis_anchor, tokens, 1000)
        supplier, _ = ocr.right_value(supplier_anchor, tokens, 1000)
        receiver, _ = ocr.right_value(receiver_anchor, tokens, 1000)
        lines, warnings = ocr.extract_table(tokens, 1000, 1000)

        self.assertEqual(basis, "2026年计划")
        self.assertEqual(supplier, "仓库")
        self.assertEqual(receiver, "超市")
        self.assertEqual(warnings, [])
        self.assertEqual(
            [(line["itemName"], line["specification"], line["quantity"]) for line in lines],
            [
                ("粉笔", "10.9型粉笔", 1000.0),
                ("橡皮", "20型橡皮", 1000.0),
            ],
        )

    def test_missing_quantity_column_fails_soft_for_human_review(self):
        tokens = [
            token("名称", 90, 300, 70),
            token("规格型号", 250, 300, 100),
            token("单位", 410, 300, 60),
            token("粉笔", 105, 370, 70),
            token("10.9型粉笔", 245, 370, 110),
            token("调拨单位", 40, 610, 90),
        ]

        lines, warnings = ocr.extract_table(tokens, 1000, 1000)

        self.assertTrue(any("应发数量" in warning for warning in warnings))
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["itemName"], "粉笔")
        self.assertEqual(lines[0]["quantity"], 0.0)
        self.assertTrue(any("数量" in warning for warning in lines[0]["warnings"]))

    def test_material_name_containing_label_word_is_not_filtered(self):
        tokens = [
            token("名称", 90, 300, 70),
            token("规格型号", 250, 300, 100),
            token("单位", 410, 300, 60),
            token("应发数", 510, 285, 80),
            token("数量", 550, 315, 60),
            token("资料袋", 105, 370, 80),
            token("A4透明", 250, 370, 90),
            token("12", 555, 370, 50),
            token("调拨单位", 40, 610, 90),
        ]

        self.assertTrue(ocr.is_probable_label(token("资料", 0, 0)))
        self.assertFalse(ocr.is_probable_label(token("资料袋", 0, 0)))

        lines, warnings = ocr.extract_table(tokens, 1000, 1000)

        self.assertEqual(warnings, [])
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["itemName"], "资料袋")
        self.assertEqual(lines[0]["specification"], "A4透明")
        self.assertEqual(lines[0]["quantity"], 12.0)


if __name__ == "__main__":
    unittest.main()
