# 模型权重说明

仓库里只保留**开箱可演示**的权重，其余大文件不入库。

| 文件 | 用途 | 来源 | 大小 |
|---|---|---|---|
| `neu_yolo.pt` | 缺陷检测（YOLOv8n，NEU 六类：crazing / inclusion / patches / pitted_surface / rolled-in_scale / scratches） | 清洗数据 + 正常/难负样本微调；270 张验证集 mAP50 0.767 / mAP50-95 0.431 | 约 6 MB |

## 使用

后端 `ManufacturingVision/services_detector.py` 按以下顺序查找权重，命中即用：

1. `models/neu_yolo.pt` ← **仓库自带**
2. `runs/vision/neu_yolo.pt`
3. `runs/neu_yolo_runs/train/weights/best.pt` ← 重新训练后的产物

放好后访问 `GET /api/v1/vision/algo/status/`，`detector.available` 应为 `true`。

## 自己重新训练

```powershell
python scripts/prepare_neu_detection_dataset_v2.py --src "<NEU 数据集根目录>" --dst runs/neu_yolo_v2 --split-mode source-random
python scripts/train_neu_detection.py --data runs/neu_yolo_v2/data.yaml --model yolov8n.pt --epochs 120 --imgsz 320 --device 0 --lr0 0.001
```

训练完成后把 `runs/neu_yolo_runs/train/weights/best.pt` 覆盖到 `models/neu_yolo.pt` 即可。
当前数据的清洗报告和本次训练产物分别位于 `runs/neu_yolo_v2_source_split/cleaning_report.json`
和 `runs/neu_yolo_runs/v2_yolov8n_source_split/`。

五折交叉验证和外部正常样本评估的说明见
`docs/视觉数据与评估优化.md`。跨域正常样本误报率从约 36.2% 降至 0.61%
（默认置信度阈值 0.25），该指标只用于评估，不参与 NEU mAP 计算。

## 未入库的大文件

| 文件 | 原因 |
|---|---|
| `models/deepcrack.pth`（约 56 MB） | 体积较大，按需自行训练或放置 |
| `runs/` 下的训练产物、`datasets/` 下的数据集 | 体积大，可由脚本重建 |

DeepCrack 缺失时视觉页面会给出提示，并自动回退到 Frangi 算法，不影响演示。
