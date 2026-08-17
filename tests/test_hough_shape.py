from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "src-tauri" / "resources" / "ocr_worker.py"
SPEC = importlib.util.spec_from_file_location("kylin_stock_ocr_worker_hough", WORKER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load OCR worker")
ocr = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ocr
SPEC.loader.exec_module(ocr)


class ArrayLike:
    """Small stand-in for NumPy arrays/scalars that expose tolist()."""

    def __init__(self, value):
        self.value = value

    def tolist(self):
        return self.value


class HoughShapeCompatibilityTest(unittest.TestCase):
    def test_accepts_opencv_n_1_4_shape(self):
        lines = ArrayLike([[[10, 20, 110, 20]], [[30, 40, 30, 140]]])
        self.assertEqual(
            ocr.hough_segments(lines),
            [(10.0, 20.0, 110.0, 20.0), (30.0, 40.0, 30.0, 140.0)],
        )

    def test_accepts_opencv_n_4_shape(self):
        lines = ArrayLike([[10, 20, 110, 20], [30, 40, 30, 140]])
        self.assertEqual(
            ocr.hough_segments(lines),
            [(10.0, 20.0, 110.0, 20.0), (30.0, 40.0, 30.0, 140.0)],
        )

    def test_accepts_single_flat_segment(self):
        lines = ArrayLike([10, 20, 110, 20])
        self.assertEqual(ocr.hough_segments(lines), [(10.0, 20.0, 110.0, 20.0)])

    def test_rejects_incomplete_segment_without_throwing(self):
        self.assertEqual(ocr.hough_segments(ArrayLike([10, 20, 110])), [])


if __name__ == "__main__":
    unittest.main()
