"""裂纹检测命令行原型（课程任务 4）。

保留原有 ``detect_crack(image_path, output_name)`` 签名，内部统一调用
``ManufacturingVision.services``，避免算法在命令行与接口之间出现两份实现。

用法::

    python ManufacturingVision/crack_detection.py <图片路径> [--out media/vision/crack]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ManufacturingVision.services import (  # noqa: E402
    analyze_crack,
    annotate_crack,
    load_image,
    save_image,
)

DEFAULT_RESULT_DIR = os.path.join("media", "vision", "crack")


def detect_crack(image_path, output_name="result.jpg", result_dir=None):
    """输入图片路径，输出判定结果、裂纹数量与结果图路径。"""
    directory = result_dir or DEFAULT_RESULT_DIR
    image = load_image(image_path)
    if image is None:
        return {"success": False, "result": "read_failed", "count": 0, "image_url": ""}

    analysis = analyze_crack(image)
    annotated = annotate_crack(image, analysis)
    output_path = Path(directory) / output_name
    save_image(output_path, annotated)

    return {
        "success": True,
        "result": analysis["result"],
        "count": analysis["count"],
        "boxes": analysis["boxes"],
        "elapsed_ms": analysis["elapsed_ms"],
        "image_url": f"/media/vision/crack/{output_name}",
        "output_path": str(output_path),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="裂纹检测命令行原型")
    parser.add_argument("image", help="待检测图片路径")
    parser.add_argument("--out", default=DEFAULT_RESULT_DIR, help="结果图保存目录")
    parser.add_argument("--name", default="result.jpg", help="结果图文件名")
    parser.add_argument("--show", action="store_true", help="尝试用 OpenCV 窗口显示结果")
    args = parser.parse_args(argv)

    result = detect_crack(args.image, args.name, args.out)
    if not result["success"]:
        print(f"[失败] 无法读取图片：{args.image}", file=sys.stderr)
        return 1
    print(
        f"[完成] 判定={result['result']} 裂纹数={result['count']} "
        f"耗时={result['elapsed_ms']}ms 结果图={result['output_path']}"
    )
    if args.show:
        try:
            import cv2

            annotated = load_image(result["output_path"])
            cv2.imshow("crack", annotated)
            cv2.waitKey(0)
            cv2.destroyAllWindows()
        except Exception as exc:  # pragma: no cover - 仅交互使用
            print(f"[提示] 无法打开显示窗口：{exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
