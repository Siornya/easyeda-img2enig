# easyeda-arknights-enig

将普通图片处理为纯黑白图，再转换成可导入嘉立创EDA专业版的沉金 PCB 图案工程。

项目包含两个相互独立的步骤：

1. `image_binarizer.py` / `main.py` 负责图片预处理和二值化。
2. `img2enig.py` 负责把纯黑白图片转换成 `.epro2`。

分开运行可以先确认黑白图效果，再处理 PCB 文件格式和物理尺寸。

## C++ / Qt Quick 新版

C++ 新版已完成二值化核心、实时预览和 Try All 多算法对比；旧版 Python 界面和 PCB 导出器保持可用。
构建和运行方法见 [新版说明](native/README.md)。

## 项目结构

- `image_binarizer.py`：图片处理核心、Python API 和命令行入口。
- `main.py`：PyQt5 图形界面。
- `img2enig.py`：黑白图片到沉金 PCB 工程转换器。
- `build.py`：PyInstaller GUI 打包脚本。
- `tests/`：二值化和沉金转换测试。

## 安装

建议使用 Python 3.9 或更高版本。

以下是虚拟环境安装步骤：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## 图形界面

```bash
.venv/bin/python main.py
```

界面支持：

- 文件选择和拖放；
- 参数变化后的实时预览；
- “查看原图 / 查看处理结果”切换；
- 固定、自适应、Otsu、Sauvola、Wolf、Nick 和 Bernsen 阈值；
- 高斯、中值、双边和 NLMeans 降噪；
- 曝光、对比度、伽马、平滑、锐化和局部增强；
- 反相、水平翻转和垂直翻转；
- 统一设置黑白图片和 PCB 工程的输出路径；
- 保存纯黑白 PNG；
- 使用当前处理结果直接生成 `.epro2` PCB 文件。

切换到原图时，参数变化仍会生效。

选择输入图片后，“输出路径”默认设为原图所在目录，也可以手动选择其他目录。输出内容为：

- `原文件名.binary.png`
- `原文件名.epro2`

“生成PCB文件”也始终使用最新的二值化结果。GUI 直接生成时使用默认参数：
50 mm 图案宽度、保持比例、顶面、1 mm 板边和自动板框。需要底面或其他尺寸时请使用 `img2enig.py` 命令行。

## 二值化命令行

默认使用自适应阈值，在原图旁生成 `input.binary.png`：

```bash
.venv/bin/python image_binarizer.py input.png
```

指定输出和阈值方法：

```bash
.venv/bin/python image_binarizer.py input.png \
    -o output.png \
    --method sauvola \
    --block-size 31
```

常用参数：

```text
--method fixed|adaptive|otsu|sauvola|wolf|nick|bernsen
--threshold 0..255
--denoise 0..100
--denoise-method gaussian|median|bilateral|nlmeans
--exposure -100..100
--contrast -100..100
--gamma 大于 0
--smooth 0..100
--sharpen 0..100
--equalize
--clahe
--invert
--flip-horizontal
--flip-vertical
--max-dimension 3840
```

默认会把超过 3840 像素的图片按比例缩小。使用 `--max-dimension 0` 可保留原始分辨率，但高分辨率会显著增加后续 PCB 图元数量。

因为 JPEG 会引入灰色压缩噪点，输出只允许 PNG、BMP 或 TIFF。

## 作为 Python 模块调用

```python
from image_binarizer import (
    BinarizationOptions,
    ThresholdMethod,
    binarize_file,
)

options = BinarizationOptions(
    threshold_method=ThresholdMethod.OTSU,
    denoise_strength=10,
)
binarize_file("input.png", "output.png", options)
```

## 生成沉金 PCB 工程

`img2enig.py` 只接受像素值为 `0` 或 `255` 的纯黑白图片。黑色区域代表需要露金的完整面积，白色区域不生成铜箔或阻焊开窗。

转换过程：

1. 将图片向下的 Y 轴转换为 PCB 向上的 Y 轴，同时保持左右方向不变；
2. 将连续黑色像素无损合并为填充矩形；
3. 在顶层或底层铜层生成相应 `FILL`；
4. 在对应阻焊层生成完全重合的开窗；
5. 生成矩形板框并封装为 `.epro2`。

基本用法：

```bash
.venv/bin/python img2enig.py input.binary.png
```

默认设置：

- 图案宽度 50 mm；
- 高度保持原图宽高比；
- 顶面沉金；
- 四周 1 mm 板边；
- 自动生成板框；
- 在输入图片旁生成同名 `.epro2`。

指定尺寸和输出：

```bash
.venv/bin/python img2enig.py input.binary.png \
    -o output.epro2 \
    --width-mm 40
```

指定 `--height-mm` 会强制使用给定高度，可能改变原图比例：

```bash
.venv/bin/python img2enig.py input.binary.png \
    --width-mm 40 \
    --height-mm 30
```

选择板面：

```bash
.venv/bin/python img2enig.py input.binary.png --side top
.venv/bin/python img2enig.py input.binary.png --side bottom
```

- 顶面使用顶层铜 `1` 和顶层阻焊 `5`；
- 底面使用底层铜 `2` 和底层阻焊 `6`。

设置板边或取消板框：

```bash
.venv/bin/python img2enig.py input.binary.png --margin-mm 2
.venv/bin/python img2enig.py input.binary.png --no-outline
```

检查生成的工程：

```bash
.venv/bin/python img2enig.py output.epro2 --inspect
```

`.epro2` 内含 `project2.json`，以及一个包含 `BOARD`、`PCB`、`CONFIG` 文档的 `.epru`
日志。当前不生成 SQLite 格式的 `.eprj2`。

## 完整流程

```bash
.venv/bin/python image_binarizer.py input.png \
    -o input.binary.png \
    --method otsu

.venv/bin/python img2enig.py input.binary.png \
    -o input.epro2 \
    --side top \
    --width-mm 40 \
    --margin-mm 1

.venv/bin/python img2enig.py input.epro2 --inspect
```

## 制造注意事项

- 沉金不是彩色打印，而是阻焊开窗处的裸露铜面经过化学镍金处理。
- PCB 下单时必须选择沉金表面处理。
- 当前铜图形和阻焊开窗尺寸完全相同；生产前应结合板厂能力检查阻焊偏位。
- 过小的孤立区域、线宽和间距可能低于制造能力。
- 下单前应在嘉立创EDA中检查铜层、阻焊层、DRC、2D/3D 和 Gerber 预览。

## 测试

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## 打包 GUI

```bash
.venv/bin/python build.py
```
