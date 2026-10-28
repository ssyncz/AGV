# 视觉数据集说明（datasets/vision）

本目录存放课程任务 4「表面裂纹检测」、任务 5「工件识别」与 NEU 六类缺陷样例，全部由
`ManufacturingVision` 应用读取，接口、管理命令与测试统一通过
`ManufacturingVision/datasets.py` 定位文件。

## 1. 目录结构

```text
datasets/vision/
├─ mt/                        # Magnetic Tile Defect 真实数据集（抽样后）
│  ├─ crack/images/*.jpg      # MT_Crack 有裂纹样本，57 张
│  ├─ crack/masks/*.png       # 与上面同名的二值真值掩码，非零像素即裂纹
│  └─ free/images/*.jpg       # MT_Free 无缺陷负样本，抽样 100 张
├─ workpiece/
│  ├─ images/wp_*.png         # 合成几何工件，120 张（400×400）
│  └─ labels.json             # 合成数据的真值标注（类别 / 外接框 / 中心 / 面积）
├─ neu/                       # NEU 六类缺陷网站样例，每类 20 张
│  ├─ <class>_001.jpg ...
│  └─ labels.json             # 样例真值（英文类别 + 中文标签）
└─ README.md
```

## 4. NEU 六类缺陷样例（任务 4 扩展）

- 来源：NEU 热轧带钢表面缺陷数据（NEU-DET），课程组在本地整理为 6 类、每类 300 张的
  扁平图片集，统一为 200×200。
- 六类：`crazing`（龟裂）、`inclusion`（夹杂）、`patches`（斑块）、`pitted`（麻点）、
  `rolled-in`（氧化皮压入）、`scratches`（划痕）。
- 网站只保留每类 20 张、共 120 张样例，文件名为 `<class>_001.jpg` 形式，真值写在
  `labels.json`；其余 1680 张原图留在课程组本地，用于训练。
- 训练清单由 `tools/prepare_neu_samples.py` 生成到 `datasets/neu_split.json`：
  按类别分层 80/20 切分，固定 `seed=42`，并按 MD5 去掉完全重复的图片。
- 正式报告需注明数据来源与用途；不要把该子集声称为自己采集。

## 2. MT 数据集（任务 4）

- 来源：Magnetic Tile Defect（磁瓦表面缺陷）数据集，由中国科学院自动化所发布并
  在 GitHub 开源，课程组使用的仓库为 `abin24/Magnetic-tile-defect-datasets`。
- 类别：`MT_Crack`（表面细微裂纹）与 `MT_Free`（无缺陷合格样本）。
- 掩码语义：`crack/masks/*.png` 为 8 位灰度图，`>0` 的像素即人工标注的裂纹区域，
  与同名 jpg 尺寸一致；MT_Free 的原始掩码为全黑（无信息），因此**未保留**。
- 抽样规则（可复现）：`MT_Free` 原文件名升序排序后取索引
  `round(i*(N-1)/99), i=0..99` 去重，得到 100 张负样本；`MT_Crack` 的 57 组图片与
  掩码全部保留。仓库体积从约 37 MB 降到约 6 MB，其余文件（含旧目录
  `ManufacturingVision/imige_crack`、`ManufacturingVision/imige_free`）已删除。
- 许可与引用：原始数据集按发布方说明用于科研/教学用途，仓库内并未附带单独的
  LICENSE 文件。**正式报告与对外提交前，请再次核对原始仓库的许可与引用要求，
  并按发布方要求标注来源**；本项目只保留课程演示所需的子集，不主张数据版权。

## 3. 合成工件数据集（任务 5）

- 用途：任务 5 需要“工件识别”数据，公开数据集与本课程场景差异较大，因此采用
  OpenCV 脚本生成，避免版权风险并自带真值。
- 生成命令：

  ```powershell
  python manage.py generate_workpiece_dataset --count 120 --size 400 --seed 42
  ```

- 图像内容：浅灰背景 + 光照渐变 + 高斯噪声，每张 1~4 个随机位置/尺寸/旋转角度的
  圆形、三角形、正方形、矩形、六边形，另有 0~2 个面积低于检测下限的干扰斑点，
  用于验证面积过滤是否有效。
- `labels.json` 结构：`{"seed":…, "size":400, "count":120, "images":[{"file":"wp_0001.png",
  "objects":[{"label":"circle","bbox":[x,y,w,h],"center":[cx,cy],"area":123.4}]}]}`。
- 可复现性：固定 `--seed` 时输出逐字节一致（测试 `test_generate_workpiece_dataset_is_reproducible`
  已验证）。
