"""ManufacturingVision 算法 / 接口 / 管理命令测试。"""
from __future__ import annotations

import tempfile
from pathlib import Path

import cv2
import numpy as np
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings

from . import datasets
from .models import VisionRecord
from .services import analyze_crack, analyze_workpiece


def _encode_png(image: np.ndarray) -> bytes:
    success, buffer = cv2.imencode(".png", image)
    if not success:  # pragma: no cover - 编码失败属异常
        raise RuntimeError("PNG 编码失败")
    return buffer.tobytes()


def _blank_canvas(size: int = 240) -> np.ndarray:
    return np.full((size, size, 3), 222, np.uint8)


def _cracked_canvas(size: int = 240) -> np.ndarray:
    canvas = _blank_canvas(size)
    cv2.line(canvas, (24, 32), (size - 30, size - 26), (90, 90, 90), 3, cv2.LINE_AA)
    return canvas


def _shape_canvas(shape: str) -> np.ndarray:
    canvas = np.full((400, 400, 3), 220, np.uint8)
    center = (200, 200)
    if shape == "circle":
        cv2.circle(canvas, center, 80, (90, 90, 90), -1)
    elif shape == "triangle":
        cv2.fillPoly(canvas, [np.array([[200, 110], [110, 290], [290, 290]], np.int32)], (90, 90, 90))
    elif shape == "square":
        cv2.rectangle(canvas, (120, 120), (280, 280), (90, 90, 90), -1)
    elif shape == "rectangle":
        cv2.rectangle(canvas, (80, 130), (320, 250), (90, 90, 90), -1)
    elif shape == "hexagon":
        points = []
        for index in range(6):
            import math

            theta = math.radians(-90 + index * 60)
            points.append([200 + 90 * math.cos(theta), 200 + 90 * math.sin(theta)])
        cv2.fillPoly(canvas, [np.array(points, np.int32)], (90, 90, 90))
    return canvas


class CrackAlgorithmTests(TestCase):
    def test_blank_image_is_normal(self):
        analysis = analyze_crack(_blank_canvas())
        self.assertEqual(analysis["result"], "normal")
        self.assertEqual(analysis["count"], 0)

    def test_line_is_detected_as_crack(self):
        analysis = analyze_crack(_cracked_canvas())
        self.assertEqual(analysis["result"], "crack")
        self.assertGreaterEqual(analysis["count"], 1)
        self.assertTrue(analysis["mask"].any())

    def test_params_override_is_sanitized(self):
        analysis = analyze_crack(_cracked_canvas(), {"score_threshold": 99.0, "unknown_key": 1})
        self.assertEqual(analysis["params"]["score_threshold"], 3.0)
        self.assertNotIn("unknown_key", analysis["params"])
        self.assertEqual(analysis["result"], "normal")


class WorkpieceAlgorithmTests(TestCase):
    def test_shape_labels(self):
        for shape in ("circle", "triangle", "square", "rectangle", "hexagon"):
            with self.subTest(shape=shape):
                analysis = analyze_workpiece(_shape_canvas(shape))
                self.assertEqual(analysis["count"], 1)
                self.assertEqual(analysis["objects"][0]["label"], shape)
                self.assertGreater(analysis["objects"][0]["score"], 0.5)


class DatasetAccessTests(TestCase):
    def test_unknown_group_rejected(self):
        with self.assertRaises(ValueError):
            datasets.resolve_sample("unknown", "a.jpg")

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            datasets.resolve_sample("crack", "../settings.py")

    def test_sample_code_split(self):
        group, name = datasets.split_sample("crack/exp1_num_3191.jpg")
        self.assertEqual(group, "crack")
        self.assertEqual(name, "exp1_num_3191.jpg")


class VisionApiTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="vision-test-")
        self._override = override_settings(MEDIA_ROOT=self.media_root)
        self._override.enable()
        self.addCleanup(self._override.disable)

    def test_crack_upload(self):
        upload = SimpleUploadedFile("crack.png", _encode_png(_cracked_canvas()), "image/png")
        response = self.client.post("/api/vision/crack/", {"image": upload})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["task_type"], "crack")
        self.assertEqual(payload["result"], "crack")
        self.assertTrue(payload["image_url"].startswith("/media/"))
        self.assertTrue(VisionRecord.objects.filter(id=payload["record_id"]).exists())

    def test_detect_upload(self):
        upload = SimpleUploadedFile("part.png", _encode_png(_shape_canvas("circle")), "image/png")
        response = self.client.post("/api/vision/detect/", {"image": upload})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["task_type"], "workpiece")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["objects"][0]["label"], "circle")

    def test_crack_sample_mode(self):
        samples = datasets.list_samples(datasets.CRACK)
        if not samples:
            self.skipTest("MT_Crack 数据集缺失")
        response = self.client.post(
            "/api/vision/crack/", {"sample": f"crack/{samples[0]}"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["input_image_url"][:7], "/media/")

    def test_missing_input_returns_400(self):
        response = self.client.post(
            "/api/vision/crack/", {}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("detail", response.json())

    def test_unknown_sample_returns_400(self):
        response = self.client.post(
            "/api/vision/crack/", {"sample": "crack/not-exist.jpg"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

    def test_records_filter_and_delete(self):
        upload = SimpleUploadedFile("crack.png", _encode_png(_cracked_canvas()), "image/png")
        self.client.post("/api/vision/crack/", {"image": upload})
        upload = SimpleUploadedFile("part.png", _encode_png(_shape_canvas("circle")), "image/png")
        self.client.post("/api/vision/detect/", {"image": upload})

        listing = self.client.get("/api/vision/records/?task_type=crack").json()
        results = listing["results"] if isinstance(listing, dict) else listing
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["task_type"], "crack")

        record_id = results[0]["id"]
        delete = self.client.delete(f"/api/vision/records/{record_id}/")
        self.assertEqual(delete.status_code, 204)
        self.assertFalse(VisionRecord.objects.filter(id=record_id).exists())

    def test_overview(self):
        upload = SimpleUploadedFile("crack.png", _encode_png(_cracked_canvas()), "image/png")
        self.client.post("/api/vision/crack/", {"image": upload})
        payload = self.client.get("/api/vision/overview/").json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["crack_hits"], 1)
        self.assertIn("dataset_summary", payload)

    def test_samples_endpoint(self):
        payload = self.client.get("/api/vision/samples/").json()
        for group in datasets.SAMPLE_GROUPS:
            self.assertIn(group, payload["samples"])

    def test_sample_image_endpoint(self):
        samples = datasets.list_samples(datasets.CRACK)
        if not samples:
            self.skipTest("MT_Crack 数据集缺失")
        response = self.client.get(f"/api/vision/samples/crack/{samples[0]}/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("image/"))
        missing = self.client.get("/api/vision/samples/crack/not-exist.jpg/")
        self.assertEqual(missing.status_code, 404)


class ManagementCommandTests(TestCase):
    def test_generate_workpiece_dataset_is_reproducible(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            common = {"count": 4, "size": 160, "seed": 7, "verbosity": 0}
            call_command("generate_workpiece_dataset", out=first, **common)
            call_command("generate_workpiece_dataset", out=second, **common)

            first_images = sorted(Path(first, "images").glob("wp_*.png"))
            second_images = sorted(Path(second, "images").glob("wp_*.png"))
            self.assertEqual(len(first_images), 4)
            self.assertEqual(len(second_images), 4)
            for left, right in zip(first_images, second_images):
                self.assertEqual(left.read_bytes(), right.read_bytes())

            import json

            labels = json.loads(Path(first, "labels.json").read_text(encoding="utf-8"))
            self.assertEqual(len(labels["images"]), 4)

    def test_evaluate_crack_writes_metrics(self):
        if not datasets.list_samples(datasets.CRACK):
            self.skipTest("MT_Crack 数据集缺失")
        with tempfile.TemporaryDirectory() as out:
            call_command("evaluate_vision", task="crack", out=out, verbosity=0)
            metrics_path = Path(out, "crack_metrics.json")
            self.assertTrue(metrics_path.is_file())
            import json

            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            for key in ("accuracy", "precision", "recall", "f1", "localization", "targets", "pass"):
                self.assertIn(key, metrics)
            for key in ("mean_iou", "mean_pixel_precision", "mean_pixel_recall", "mean_recall_tol3"):
                self.assertIn(key, metrics["localization"])
            self.assertTrue(Path(out, "crack_metrics.csv").is_file())

    def test_evaluate_workpiece_writes_metrics(self):
        if not datasets.load_workpiece_labels():
            self.skipTest("合成工件数据集缺失，请先运行 generate_workpiece_dataset")
        with tempfile.TemporaryDirectory() as out:
            call_command("evaluate_vision", task="workpiece", out=out, verbosity=0)
            metrics_path = Path(out, "workpiece_metrics.json")
            self.assertTrue(metrics_path.is_file())
            import json

            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            self.assertIn("detection", metrics)
            self.assertIn("classification", metrics)
