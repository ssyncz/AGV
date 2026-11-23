"""ManufacturingVision 算法 / 接口 / 管理命令测试。"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

import cv2
import numpy as np
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from . import datasets
from .models import VisionRecord
from .services import (
    _skeletonize_binary,
    analyze_crack,
    analyze_workpiece,
    refine_crack_mask,
)
from .services_defect import available as defect_available
from .services_defect_localization import (
    _merge_boxes,
    _should_join_collinear,
    locate_defect,
)
from .services_supervised import supervised_available


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

    def test_mask_postprocess_returns_one_pixel_skeleton_then_calibrated_width(self):
        binary = np.zeros((80, 120), np.uint8)
        cv2.line(binary, (15, 20), (100, 60), 1, 7)
        skeleton = _skeletonize_binary(binary)
        self.assertTrue(skeleton.any())
        self.assertLessEqual(cv2.connectedComponents(skeleton)[0], 2)
        self.assertLess(
            np.count_nonzero(skeleton),
            np.count_nonzero(binary),
        )

        response = cv2.GaussianBlur(binary.astype(np.float32) * 0.8, (5, 5), 0)
        refined, boxes = refine_crack_mask(
            response,
            {
                "mask_threshold_ratio": 0.5,
                "mask_close_kernel": 3,
                "mask_skeleton": True,
                "mask_min_aspect": 1.5,
                "mask_border_margin": 0,
                "mask_dilation": 2,
            },
        )
        self.assertTrue(refined.any())
        self.assertTrue(boxes)
        self.assertGreater(np.count_nonzero(refined), np.count_nonzero(skeleton))

    def test_mask_postprocess_legacy_fallback_and_sanitization(self):
        response = np.zeros((30, 30), np.float32)
        response[10:20, 15] = 0.6
        mask, boxes = refine_crack_mask(
            response,
            {
                "mask_threshold_ratio": 0,
                "vessel_threshold": 0.55,
                "mask_close_kernel": 2,
                "mask_skeleton": False,
                "mask_min_aspect": 1.0,
                "mask_border_margin": -2,
                "mask_dilation": 20,
            },
        )
        self.assertTrue(mask.any())
        self.assertTrue(boxes)
        analysis = analyze_crack(
            _cracked_canvas(),
            {"mask_close_kernel": 2, "mask_dilation": 20},
        )
        self.assertEqual(analysis["params"]["mask_close_kernel"], 3)
        self.assertEqual(analysis["params"]["mask_dilation"], 8)


class WorkpieceAlgorithmTests(TestCase):
    def test_shape_labels(self):
        for shape in ("circle", "triangle", "square", "rectangle", "hexagon"):
            with self.subTest(shape=shape):
                analysis = analyze_workpiece(_shape_canvas(shape))
                self.assertEqual(analysis["count"], 1)
                self.assertEqual(analysis["objects"][0]["label"], shape)
                self.assertGreater(analysis["objects"][0]["score"], 0.5)


class DefectLocalizationTests(TestCase):
    def test_collinear_fragments_are_joined(self):
        left = [19, 82, 29, 93]
        right = [24, 11, 20, 67]
        self.assertTrue(_should_join_collinear(left, right))
        merged = _merge_boxes(
            [
                {"box": left, "score": 0.8, "area_ratio": 0.01},
                {"box": right, "score": 0.7, "area_ratio": 0.01},
            ],
            join_collinear=True,
        )
        self.assertEqual(len(merged), 1)
        self.assertGreaterEqual(merged[0]["box"][3], 160)

    def test_long_scratches_are_enclosed_by_continuous_boxes(self):
        image = np.full((256, 256, 3), 48, np.uint8)
        cv2.line(image, (78, 18), (82, 238), (225, 225, 225), 3, cv2.LINE_AA)
        cv2.line(image, (184, 24), (179, 231), (210, 210, 210), 2, cv2.LINE_AA)
        located = locate_defect(
            image,
            predicted_class="scratches",
            confidence=0.96,
        )
        boxes = located["boxes"]
        self.assertTrue(boxes)
        self.assertTrue(
            any(
                box[0] <= 78
                and box[0] + box[2] >= 84
                and box[1] <= 30
                and box[1] + box[3] >= 220
                for box in boxes
            )
        )

    def test_patches_use_one_overall_region_but_pitted_can_keep_multiple(self):
        image = np.full((256, 256, 3), 215, np.uint8)
        cv2.rectangle(image, (28, 42), (86, 104), (55, 55, 55), -1)
        cv2.rectangle(image, (158, 146), (220, 214), (62, 62, 62), -1)
        patch_result = locate_defect(
            image,
            predicted_class="patches",
            confidence=0.97,
        )
        self.assertEqual(len(patch_result["boxes"]), 1)

        pitted_result = locate_defect(
            image,
            predicted_class="pitted",
            confidence=0.97,
        )
        boxes = pitted_result["boxes"]
        self.assertGreaterEqual(len(boxes), 2)
        self.assertLessEqual(len(boxes), 5)


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

    def test_neu_group_has_samples_and_labels(self):
        samples = datasets.list_samples(datasets.NEU)
        self.assertEqual(len(samples), 120)
        labels = datasets.load_neu_labels()
        self.assertEqual(set(labels), set(samples))
        self.assertEqual(
            {item["class"] for item in labels.values()},
            {"crazing", "inclusion", "patches", "pitted", "rolled-in", "scratches"},
        )


class VisionApiTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="vision-test-")
        self._override = override_settings(MEDIA_ROOT=self.media_root)
        self._override.enable()
        self.addCleanup(self._override.disable)

    def test_crack_upload(self):
        upload = SimpleUploadedFile("crack.png", _encode_png(_cracked_canvas()), "image/png")
        response = self.client.post(
            "/api/vision/crack/",
            {"image": upload, "params": json.dumps({"algorithm": "frangi"})},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["task_type"], "crack")
        self.assertEqual(payload["result"], "crack")
        self.assertEqual(payload["algorithm"], "frangi")
        self.assertTrue(payload["image_url"].startswith("/media/"))
        self.assertTrue(VisionRecord.objects.filter(id=payload["record_id"]).exists())

    def test_crack_default_algorithm_reported(self):
        upload = SimpleUploadedFile("crack.png", _encode_png(_cracked_canvas()), "image/png")
        response = self.client.post("/api/vision/crack/", {"image": upload})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(payload["algorithm"], {"deepcrack", "frangi"})
        self.assertIn("fallback", payload)

    def test_crack_deepcrack_request_falls_back_without_weights(self):
        upload = SimpleUploadedFile("crack.png", _encode_png(_cracked_canvas()), "image/png")
        response = self.client.post(
            "/api/vision/crack/",
            {"image": upload, "params": json.dumps({"algorithm": "deepcrack"})},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(payload["algorithm"], {"deepcrack", "frangi"})
        if not supervised_available():
            self.assertTrue(payload["fallback"])
            self.assertEqual(payload["algorithm"], "frangi")

    def test_algo_status_reports_deepcrack(self):
        payload = self.client.get("/api/vision/algo/status/").json()
        self.assertIn("deepcrack", payload)
        self.assertIn("weights_found", payload["deepcrack"])

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
        self.client.post(
            "/api/vision/crack/",
            {"image": upload, "params": json.dumps({"algorithm": "frangi"})},
        )
        payload = self.client.get("/api/vision/overview/").json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["crack_hits"], 1)
        self.assertIn("dataset_summary", payload)

    def test_samples_endpoint(self):
        payload = self.client.get("/api/vision/samples/").json()
        for group in datasets.SAMPLE_GROUPS:
            self.assertIn(group, payload["samples"])

    def test_defect_sample_endpoint(self):
        if not defect_available():
            self.skipTest("NEU 权重未就绪")
        samples = datasets.list_samples(datasets.NEU)
        if not samples:
            self.skipTest("NEU 样例缺失")
        name = samples[0]
        response = self.client.post(
            "/api/vision/algo/defect/",
            {"sample": f"neu/{name}"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("predicted_class", payload)
        truth = datasets.load_neu_labels()[name]
        self.assertEqual(payload.get("ground_truth_class"), truth["class"])
        self.assertIn("match", payload)
        self.assertEqual(payload["task_type"], "defect")
        self.assertIn(payload["verdict"], {"defect", "uncertain"})
        self.assertTrue(payload["tta"])
        self.assertEqual(payload["tta_views"], 4)
        self.assertTrue(payload["record_id"])
        record = VisionRecord.objects.get(pk=payload["record_id"])
        self.assertEqual(record.task_type, VisionRecord.TaskType.DEFECT)
        self.assertTrue(record.input_image.name)
        self.assertTrue(record.result_image.name)

    def test_defect_six_class_samples_have_red_boxes_and_records(self):
        if not defect_available():
            self.skipTest("NEU 权重未就绪")
        samples = datasets.list_samples(datasets.NEU)
        labels = datasets.load_neu_labels()
        if not samples:
            self.skipTest("NEU 样例缺失")
        representatives = {}
        for name in samples:
            representatives.setdefault(labels[name]["class"], name)
        self.assertEqual(len(representatives), 6)

        for index, (expected_class, name) in enumerate(representatives.items(), start=1):
            with self.subTest(expected_class=expected_class):
                response = self.client.post(
                    "/api/vision/algo/defect/",
                    {"sample": f"neu/{name}"},
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["raw_predicted_class"], expected_class)
                self.assertEqual(payload["verdict"], "defect")
                self.assertGreaterEqual(len(payload["boxes"]), 1)
                self.assertLessEqual(len(payload["boxes"]), 5)
                for x, y, width, height in payload["boxes"]:
                    self.assertGreaterEqual(x, 0)
                    self.assertGreaterEqual(y, 0)
                    self.assertGreater(width, 0)
                    self.assertGreater(height, 0)
                    self.assertLessEqual(x + width, payload["width"])
                    self.assertLessEqual(y + height, payload["height"])

                record = VisionRecord.objects.get(pk=payload["record_id"])
                result_image = cv2.imread(record.result_image.path)
                self.assertIsNotNone(result_image)
                red = (
                    (result_image[:, :, 2] > 170)
                    & (result_image[:, :, 2] > result_image[:, :, 1] * 1.4)
                    & (result_image[:, :, 2] > result_image[:, :, 0] * 1.4)
                )
                self.assertTrue(red.any())

    def test_defect_low_confidence_is_uncertain_and_still_saved(self):
        low_confidence = {
            "task": "defect_classification",
            "model": "mock",
            "weights": None,
            "predicted_class": "scratches",
            "predicted_label": "划痕",
            "confidence": 0.41,
            "top3": [
                {"class": "scratches", "label": "划痕", "probability": 0.41},
                {"class": "crazing", "label": "龟裂（网状裂纹）", "probability": 0.39},
            ],
            "probabilities": {
                "crazing": 0.39,
                "inclusion": 0.05,
                "patches": 0.05,
                "pitted": 0.05,
                "rolled-in": 0.05,
                "scratches": 0.41,
            },
            "is_line_like": True,
            "note": "",
        }
        upload = SimpleUploadedFile(
            "unknown.png",
            _encode_png(np.full((180, 220, 3), 128, np.uint8)),
            "image/png",
        )
        with mock.patch(
            "ManufacturingVision.views_algo.classify_defect",
            return_value=low_confidence,
        ):
            response = self.client.post(
                "/api/vision/algo/defect/",
                {"image": upload},
                format="multipart",
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["verdict"], "uncertain")
        self.assertEqual(payload["predicted_label"], "不属于6类缺陷或无缺陷，请人工复核")
        self.assertEqual(payload["boxes"], [])
        record = VisionRecord.objects.get(pk=payload["record_id"])
        self.assertEqual(record.verdict, "uncertain")
        self.assertTrue(record.result_image.name)

    def test_defect_record_filter_detail_and_delete(self):
        if not defect_available():
            self.skipTest("NEU 权重未就绪")
        sample = datasets.list_samples(datasets.NEU)[0]
        response = self.client.post(
            "/api/vision/algo/defect/",
            {"sample": f"neu/{sample}"},
            content_type="application/json",
        )
        payload = response.json()
        record_id = payload["record_id"]

        listing = self.client.get("/api/vision/records/?task_type=defect&page=1").json()
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["results"][0]["task_type"], "defect")
        self.assertTrue(listing["results"][0]["verdict_display"])

        detail = self.client.get(f"/api/vision/records/{record_id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["id"], record_id)
        self.assertTrue(detail.json()["result_image_url"])

        record = VisionRecord.objects.get(pk=record_id)
        input_path = Path(record.input_image.path)
        result_path = Path(record.result_image.path)
        self.assertTrue(input_path.is_file())
        self.assertTrue(result_path.is_file())
        self.assertEqual(
            self.client.delete(f"/api/vision/records/{record_id}/").status_code,
            204,
        )
        self.assertFalse(input_path.exists())
        self.assertFalse(result_path.exists())

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


class AlgoInputGuardTests(TestCase):
    def test_dataset_view_rejects_unsafe_input(self):
        client = APIClient()
        for payload in ({"category": "../evil"}, {"category": "a" * 40},
                        {"dst_root": "../../etc"}):
            resp = client.post("/api/vision/algo/dataset/", payload, format="json")
            self.assertEqual(resp.status_code, 400, payload)

    def test_patchcore_rejects_non_image_upload(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        client = APIClient()
        upload = SimpleUploadedFile("a.txt", b"not an image", content_type="text/plain")
        resp = client.post("/api/vision/algo/patchcore/", {"file": upload}, format="multipart")
        self.assertIn(resp.status_code, (400, 503))
