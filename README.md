# 图片二值化工具

这是一个独立的图片预处理与二值化工具。它负责把普通图片转换为只包含 `0` 和 `255`
像素值的黑白图片，不负责生成嘉立创EDA工程。

生成的 PNG 可以继续交给同目录中的 `img2enig.py`，转换为沉金 PCB 工程。两个步骤彼此
独立，便于单独调试图片效果和 PCB 文件格式。

## 项目结构

- `image_binarizer.py`：图片处理核心和命令行入口，可作为 Python 模块调用。
- `main.py`：PyQt5 图形界面。
- `img2enig.py`：独立的黑白图片到沉金工程转换器。
- `tests/`：二值化核心测试。

## 安装

建议使用虚拟环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

如果只使用命令行和处理核心，不需要安装 PyQt5；需要图形界面时再安装即可。

## 命令行使用

最简单的调用：

```bash
.venv/bin/python image_binarizer.py input.png
```

默认在原图旁生成 `input.binary.png`，使用自适应阈值，并把超过 3840 像素的图片按比例
缩小。

输出只允许 PNG、BMP 或 TIFF 等无损格式。JPEG 会引入灰色压缩噪点，因此程序会拒绝
保存为 JPEG。

指定输出和阈值算法：

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

使用 `--max-dimension 0` 可以保留原始分辨率。高分辨率图片会显著增加后续
`img2enig.py` 生成的 PCB 图元数量。

## 图形界面

```bash
.venv/bin/python main.py
```

界面支持文件选择和拖放、实时预览、七种阈值方法、四种降噪方法、曝光/对比度/伽马、
平滑、锐化、局部增强、反相和水平/垂直翻转。

## 作为模块调用

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

## 与沉金转换器串联

```bash
.venv/bin/python image_binarizer.py input.png -o input.binary.png --method otsu
.venv/bin/python img2enig.py input.binary.png -o input.epro2
```

第一条命令只决定黑白图案内容；第二条命令只决定 PCB 尺寸、板面、边距和输出格式。

## 测试

```bash
.venv/bin/python -m unittest discover -s tests -v
```

测试覆盖全部阈值算法、透明背景、中文路径、方向翻转和最大尺寸限制。

## 打包 GUI

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python build.py
```
