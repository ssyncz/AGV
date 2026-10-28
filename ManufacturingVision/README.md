# ManufacturingVision — 制造视觉检测模块（课程任务 4 / 5）

本应用负责课程选题 A 中的**任务 4 表面裂纹检测**与**任务 5 工件识别**，通过
Django REST Framework 接入 `AGV` 项目，前端在 Vue3 界面中提供「视觉检测」菜单。
任务 4 默认使用 **Frangi 多尺度黑脊**（OpenCV，免训练、可解释），也可在界面上切换到
**DeepCrack 监督式裂纹分割**（PyTorch）。官方 DeepCrack 权重在 MT 磁瓦域迁移效果较差
（实测 F1 0.56，低于 Frangi 的 0.82），因此默认不使用它；若换成域内微调权重，可在
`params` 中显式选择 `algorithm=deepcrack`。任务 5 沿用 OpenCV 几何工件识别。

## 1. 目录结构

```text
ManufacturingVision/
├─ datasets.py                     # 数据集访问层（样例列举、路径解析、标注读取）
├─ services.py                     # OpenCV 算法：裂纹检测 + 工件识别（不依赖 Django）
├─ crack_detection.py              # 命令行裂纹检测原型（保留 detect_crack 签名）
├─ models.py                       # VisionRecord 视觉检测记录表
├─ serializers.py / views.py / urls.py / admin.py
├─ migrations/0001_initial.py
├─ management/commands/
│  ├─ generate_workpiece_dataset.py   # 生成合成几何工件数据集
│  └─ evaluate_vision.py              # 批量评估并输出 CSV / JSON 指标
├─ reports/                        # 评估产物（crack_metrics / workpiece_metrics）
├─ tests.py                        # 24 项算法 / 接口 / 命令测试
└─ README.md
```

## 2. 数据集

详见 [`datasets/vision/README.md`](../datasets/vision/README.md)。

| 分组 | 内容 | 数量 | 真值 |
| --- | --- | --- | --- |
| `crack` | MT_Crack 表面细微裂纹（真实工业图像） | 57 | 同名 PNG 二值掩码 |
| `free` | MT_Free 无缺陷负样本（可复现抽样） | 100 | 无（判定为 normal） |
| `workpiece` | 合成几何工件（圆/三角/方/矩/六边形） | 120（306 个目标） | `labels.json` |

来源为 Magnetic Tile Defect 数据集（中国科学院自动化所发布，GitHub 开源，课程组
参考 `abin24/Magnetic-tile-defect-datasets`）。**正式提交前请复核原始仓库的许可
与引用要求**，详见数据集 README。

## 3. 算法说明

### 3.1 任务 4 裂纹检测（`services.analyze_crack`，回退方案）

真实磁瓦图像中同时存在宽而亮的加工弧纹、工件边缘阴影和纵向纹理沟槽，早期的
“黑帽 + Otsu + 轮廓筛选”方案会把大量纹理判成裂纹（实测准确率仅 0.363）。最终
方案改为面向**细暗线状结构**的经典管线：

1. 缩放长边至 ≤ `max_side`（默认 1024，仅缩小不放大）；
2. 高斯去噪（3×3，σ=0.6）；
3. **多尺度 Frangi 黑脊（vesselness）响应**：对 σ∈{1.0,1.4,2.0,2.8} 计算 Hessian
   特征值，取 `λ₂>0` 且 `R_b=|λ₁|/|λ₂|` 较小的响应，只保留“细、暗、两侧更亮”的
   线状结构，从而抑制块状纹理与阶跃边缘；
4. 连通域分析 + `minAreaRect`，剔除与图像边界相连的成分（工件边缘/光照过渡）并
   要求长宽比 ≥ `min_aspect`；
5. 判定得分 `score = 0.7 × 最大脊响应 + 0.4 × 最强细长连通域得分`，
   `score ≥ score_threshold` 判为 `crack`；
6. 输出掩码使用“相对阈值 + 闭运算 + 宽度校准”：阈值取单图最大脊响应的
   `mask_threshold_ratio`（默认 0.575），用 3×3 椭圆核填补小断裂，再按
   `mask_dilation` 膨胀至人工标注的典型宽度；细长连通域筛选和 1 像素宽
   Zhang-Suen 骨架化均可通过参数启用。

图像级得分仍使用固定 `vessel_threshold` 与边界约束，因此本次掩码后处理只改变
定位结果，不改变“有/无裂纹”的候选分数。后处理参数在 5 组固定种子的标定折上
按键体 IoU 选择，再在同一组留出测试上评估。

### 3.2 任务 5 工件识别（`services.analyze_workpiece`）

1. 灰度化 → 双边滤波（保留边缘、抑制噪声）；
2. Otsu 阈值，并按前景像素占比自动判断是否需要反相；
3. 椭圆核开运算 + 闭运算；
4. 外轮廓 → 面积过滤（`min_area`）→ `approxPolyDP`（`approx_epsilon × 周长`）；
5. 依据顶点数、圆度、多边形边长比分类为 `circle / triangle / square / rectangle /
   hexagon`，无法判定归 `unknown`；
6. 置信分为几何规则与 `cv2.matchShapes` 相似度的启发式组合（**不是校准概率**）。

### 3.3 任务 4 裂纹检测（DeepCrack 监督分割，可选）

选择 DeepCrack 时调用 `services_supervised.analyze_crack_supervised`，内部流程：

1. 懒加载 `deepcrack_model.CrackSegmenter`（权重查找顺序见
   `services_supervised.WEIGHT_CANDIDATES`）；
2. BGR → RGB，并把长边缩放到 `max_side`（默认 512）以内，降低 CPU 推理耗时；
3. 网络输出融合分支的裂纹概率图，按 `threshold` 二值化；
4. 连通域分析生成 `boxes`，并按 `min_area` 过滤离散噪点；
5. 当 `coverage ≥ min_coverage` 且存在连通域时判定为 `crack`；
6. 结果掩膜缩放回原图尺寸，接口同时返回 `coverage / max_prob / mean_prob` 与
   `algorithm` 字段。

若 PyTorch 未安装或找不到权重，接口抛出 `RuntimeError`，视图层捕获后自动回退到
3.1 的 Frangi 方案，并在响应中标记 `fallback=true`。前端「视觉检测」页提供算法
下拉框，可显式选择 `DeepCrack` 或 `Frangi`。

### 3.4 NEU 六类缺陷分类（可选）

`services_defect.py` 实现了一个 64×64 灰度输入的 SmallCNN（3 组 Conv-BN-ReLU-MaxPool +
全局平均池化 + 全连接），输出 NEU 热轧带钢的六类缺陷：
`crazing / inclusion / patches / pitted / rolled-in / scratches`。

模型权重不在仓库里，需要自行训练：

```powershell
# 数据按类别分目录：<data_root>/images/<class>/*.jpg
.\venv\Scripts\python.exe scripts\train_neu.py --data-root datasets/neu --epochs 25
```

训练产物写到 `runs/vision/neu_cnn.pt`（`runs/` 已在 `.gitignore` 中忽略）。
未找到权重时 `/api/vision/algo/status/` 的 `defect.available` 为 `false`，
前端会把「NEU 六类」选项置灰并提示先训练，不会弹出无意义的报错。

课程组当前模型用本地 1800 张（6 类 × 300）训练，按类别分层 80/20 切分，
验证集 360 张，最佳验证准确率 **0.9944**；逐类指标与混淆矩阵见
`runs/vision/neu_cnn.metrics.json`。注意验证集与训练集同源，不能当成独立外部测试集。

网站内置样例是 `datasets/vision/neu/` 下每类 20 张、共 120 张；
缺陷接口支持 `{"sample": "neu/crazing_001.jpg"}`，并返回 `ground_truth_class` 与 `match`。

线状缺陷（`crazing`、`scratches`）建议再调用裂纹分割接口做定位；
其余四类只做类型识别。

## 4. 接口契约

前缀 `/api/vision/`，鉴权沿用项目现状（`AllowAny`），错误统一为 `400 {"detail": "..."}`
（样例图片不存在时为 `404`）。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/vision/crack/` | 裂纹检测 |
| POST | `/api/vision/detect/` | 工件识别 |
| GET | `/api/vision/samples/` | 内置样例列表与数据集规模 |
| GET | `/api/vision/samples/<分组>/<文件名>/` | 返回内置样例原图（前端预览用） |
| GET | `/api/vision/records/` | 检测记录列表（`?task_type=` / `?source=` / `?verdict=`） |
| DELETE | `/api/vision/records/{id}/` | 删除记录，同时清理其输入图与结果图 |
| GET | `/api/vision/overview/` | 检测次数、裂纹检出率、平均耗时、最近记录 |
| GET | `/api/vision/algo/status/` | 深度学习依赖、权重与数据集就绪状态 |
| POST | `/api/vision/algo/deepcrack/` | 直接调用 DeepCrack 分割 |
| GET/POST | `/api/vision/algo/defect/` | NEU 六类缺陷识别（需权重） |
| POST | `/api/vision/algo/patchcore/` | PatchCore 无监督异常检测（需 anomalib） |
| POST | `/api/vision/algo/dataset/` | 把现有数据转成 MVTec-AD 布局 |

请求支持两种模式，二选一：

* `multipart/form-data` 上传：字段 `image`（jpg/png），可选字段 `params`（JSON 字符串）；
* `application/json` 指定内置样例：`{"sample": "crack/exp1_num_249594.jpg", "params": {...}}`。

裂纹检测响应示例：

```json
{
  "success": true, "task_type": "crack", "algorithm": "deepcrack", "fallback": false,
  "result": "crack", "count": 1,
  "localized": true, "score": 0.71, "max_response": 0.83,
  "coverage": 0.0021, "max_prob": 0.98, "mean_prob": 0.14,
  "boxes": [[42, 51, 118, 9]], "image_url": "/media/vision/results/20261003/xxx_result.jpg",
  "input_image_url": "/media/vision/inputs/20261003/xxx_input.jpg",
  "record_id": 12, "elapsed_ms": 18.4, "width": 219, "height": 264, "params": { }
}
```

* `result`：判定结论；`count` / `boxes` / `mask` 为定位结果；`localized` 表示是否定位到
  细长连通域。当 `result="crack"` 而 `localized=false` 时表示“置信分超阈值但未能定位”，
  前端会提示人工复核。

工件识别响应示例：

```json
{
  "success": true, "task_type": "workpiece", "count": 2,
  "objects": [
    {"label": "circle", "box": [58, 61, 121, 119], "center": [118, 120],
     "area": 11234.5, "vertices": 12, "circularity": 0.91, "score": 0.94}
  ],
  "class_counts": {"circle": 1, "hexagon": 1},
  "class_labels": {"circle": "圆形", "hexagon": "六边形"},
  "image_url": "/media/vision/results/20261003/xxx_result.jpg",
  "record_id": 13, "elapsed_ms": 21.7, "width": 400, "height": 400, "params": { }
}
```

## 5. 可调参数

| 任务 | 参数 | 默认值 | 说明 |
| --- | --- | --- | --- |
| 裂纹 | `max_side` | 1024 | 处理前长边上限 |
| 裂纹 | `vessel_threshold` | 0.55 | 黑脊响应二值化阈值 |
| 裂纹 | `vessel_beta` | 0.6 | Frangi 形状敏感度 |
| 裂纹 | `min_aspect` | 2.5 | 连通域长宽比下限 |
| 裂纹 | `score_threshold` | 0.54 | 判定裂纹的得分阈值 |
| 裂纹 | `mask_threshold_ratio` | 0.575 | 掩码相对阈值，相对单图最大脊响应；设为 0 时回退固定阈值 |
| 裂纹 | `mask_close_kernel` | 3 | 掩码闭运算核尺寸，1 表示关闭 |
| 裂纹 | `mask_skeleton` | `false` | 是否执行 Zhang-Suen 骨架化 |
| 裂纹 | `mask_min_aspect` | 2.5 | 掩码细长连通域长宽比下限 |
| 裂纹 | `mask_border_margin` | 0 | 掩码边界剔除像素数；0 允许裂纹接触图像边缘 |
| 裂纹 | `mask_dilation` | 3 | 结果掩码膨胀像素数 |
| 工件 | `min_area` | 300 | 面积过滤下限 |
| 工件 | `approx_epsilon` | 0.02 | 多边形逼近精度系数 |
| 工件 | `morph_kernel` | 5 | 形态学核尺寸 |

参数集中在 `services.VISION_DEFAULTS`，请求中的 `params` 只接受已知键并做范围校验，
非法值会被忽略或截断（见 `tests.CrackAlgorithmTests.test_params_override_is_sanitized`）。

DeepCrack 参数集中在 `services_supervised.DEEPCRACK_DEFAULTS`：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `algorithm` | `frangi` | 裂纹算法选择：`frangi`（默认）/ `deepcrack`（需域内权重） |
| `threshold` | 0.72 | 概率图二值化阈值 |
| `min_area` | 8 | 连通域最小面积（像素） |
| `min_coverage` | 0.0002 | 判定为裂纹的最小前景覆盖率 |
| `max_side` | 512 | 推理前长边缩放上限 |
| `device` | `cpu` | PyTorch 推理设备 |

## 6. 运行与评估

```powershell
# 依赖（opencv-python / numpy 已写入 requirements.txt）
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# 建表（新增 ManufacturingVision_visionrecord）
.\venv\Scripts\python.exe manage.py migrate

# 生成合成工件数据集（固定 seed 可复现）
.\venv\Scripts\python.exe manage.py generate_workpiece_dataset --count 120 --size 400 --seed 42

# 批量评估并输出指标
.\venv\Scripts\python.exe manage.py evaluate_vision --task all --out ManufacturingVision/reports

# 命令行裂纹检测原型
.\venv\Scripts\python.exe ManufacturingVision\crack_detection.py datasets/vision/mt/crack/images/exp1_num_3191.jpg

# 测试（需要 MySQL；也可用内存 SQLite 覆盖 DATABASES 后运行）
.\venv\Scripts\python.exe manage.py test ManufacturingVision -v 2
```

## 7. 指标结果

评估脚本在全部 57 张 MT_Crack + 100 张 MT_Free 上的结果
（`reports/crack_metrics.json`）：

| 指标 | 数值 | 门槛 |
| --- | --- | --- |
| 准确率 | **0.8662** | ≥ 0.85 ✅ |
| 精确率 | 0.7903 | — |
| 召回率 | 0.8596 | — |
| F1 | **0.8235** | ≥ 0.80 ✅ |
| 平均 IoU（像素级定位） | **0.2723** | 参考 |
| 像素精确率 | 0.3577 | 参考 |
| 像素召回率 | 0.4911 | 参考 |
| 召回@3px 容差 | 0.5418 | 参考 |
| 成功定位裂纹的图片 | 49 / 57 | 参考 |

混淆矩阵：TP=49、FP=13、TN=87、FN=8。

为检验泛化能力，另按固定规则做了留出集切分（裂纹按 3 取 1、负样本按 4 取 1 作为
测试集），结果如下——**报告里建议同时给出这两组数字，说明参数是在全量数据上标定的**：

| 数据划分 | 数量 | 准确率 | 精确率 | 召回率 | F1 |
| --- | --- | --- | --- | --- | --- |
| 训练/标定子集 | 38 裂纹 + 75 负样本 | 0.8938 | 0.8095 | 0.8947 | 0.8500 |
| 留出测试子集 | 19 裂纹 + 25 负样本 | 0.7955 | 0.7500 | 0.7895 | 0.7692 |

工件识别结果（`reports/workpiece_metrics.json`，120 张图 / 306 个目标）：

| 指标 | 数值 | 门槛 |
| --- | --- | --- |
| 检测精确率（IoU≥0.5） | 1.0000 | — |
| 检测召回率 | 0.9804 | — |
| 检测 F1 | **0.9901** | ≥ 0.85 ✅ |
| 形状分类准确率 | **0.9767** | ≥ 0.90 ✅ |

逐类召回：圆形 0.952、三角形 0.877、正方形 0.966、矩形 1.000、六边形 1.000。

### 调参记录（用于报告“算法对比”一节）

| 方案 | 准确率 | F1 | 说明 |
| --- | --- | --- | --- |
| 黑帽 + Otsu + 面积/伸长比 | 0.3631 | 0.5327 | 100 张负样本全部误报，纹理沟槽被当成裂纹 |
| 局部对比度 + 边界剔除 + 细长筛选 | 0.5924 | 0.5789 | 抑制边界后仍有大量纵向纹理误报 |
| 多尺度 Frangi 黑脊（仅最大响应） | 0.7962 | 0.7500 | 能区分“细暗线”与“宽弧纹” |
| **黑脊 + 连通域一致性 + mask 后处理** | **0.8662** | **0.8235** | 当前方案；全量平均 IoU 0.1438→0.2723，5 组留出均值 0.1621→0.2803 |

## 8. 前端接入

* `frontend/src/views/VisionView.vue`：新增「视觉检测」页面，含在线检测与检测记录
  两个子页；支持内置样例/本地上传、参数调整、原图与结果图对比、工件明细表、
  记录筛选与删除；裂纹任务提供 DeepCrack / Frangi 算法切换，并按算法展示对应指标。
* `frontend/src/api.js`：`request` 在 `body` 为 `FormData` 时不再强制 JSON
  `Content-Type`；新增 `visionCrack / visionDetect / visionSamples / visionRecords /
  deleteVisionRecord / visionOverview / visionSampleImageUrl`。
* `frontend/src/App.vue`：新增 `vision` 菜单项并渲染 `VisionView`（把原 `AgvView v-else`
  改为 `v-else-if="activeTab === 'agvs'"`）。
* `frontend/vite.config.js`：新增 `/media` 代理，使结果图在开发环境可直接显示。

> 页面样式复用 `styles.css` 中既有的 `panel / form-grid / field / mini-stat /
> metric-grid / table-wrap / notice / tag` 等类，仅在 `VisionView.vue` 内用 `scoped`
> 样式补充图片对比区，未引入新的前端依赖。

## 9. 已知限制与后续可做

1. 裂纹定位的平均 IoU 已从 0.1438 提升至 0.2723，但仍受漏定位和标注宽度差异
   限制；当前最优参数未启用骨架化，后续需要更多同域标注验证更复杂的宽度估计。
2. 参数在 157 张图片上标定，留出集 F1 0.77，说明小样本下存在一定过拟合；
   扩样本或改用交叉验证会更稳。
3. 工件识别基于合成数据，真实产线图像需要重新标注与验证；`unknown` 分支目前
   仅作兜底。
4. 若部署到无图形库服务器，把 `opencv-python` 换成 `opencv-python-headless`
   即可（服务端代码不使用 GUI 函数）。

## 10. AI 使用记录

按课程要求记录本模块的 AI 协作过程（日期 / 工具 / 提示词 / 采用内容 / 人工修改 / 验证结果）。
后续可合并到 `docs/ai_usage.md`。

| 日期 | 工具 | 提示词 | 采用内容 | 人工修改 | 验证结果 |
| --- | --- | --- | --- | --- | --- |
| 2026-10-03 | Codex（GPT-5） | “在 ManufacturingVision 内实现任务 4/5，OpenCV 传统算法并接入 Django+Vue” | 生成 app 骨架（models/serializers/views/urls/admin）、`services.py` 算法、两个管理命令、前端 `VisionView.vue` | 需人工复核参数标定与前端文案；根因 bug（`objects` 字段名冲突、`filterset_fields` 未生效）由人工定位后修正 | `manage.py check` 通过；`test ManufacturingVision` 18 项全绿 |
| 2026-10-03 | Codex（GPT-5） | “跑全量数据集输出精确率/召回率/F1/IoU” | `evaluate_vision` 命令与 `reports/*.json|csv` | 初始方案准确率仅 0.363，人工分析误报来源（宽弧纹/边界阴影）后改算法 | 裂纹准确率 0.866 / F1 0.824；工件 F1 0.990 / 分类 0.977 |
| 2026-10-03 | Codex（GPT-5） | “整理数据集并保留必要子集” | 目录迁移到 `datasets/vision/`、负样本按索引均匀抽样 100 张、丢弃全黑掩码 | 人工确认抽样规则与删除范围后执行 | `datasets/vision` 共 157+120 张；旧目录已删除 |
