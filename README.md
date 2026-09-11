# easyeda-img2pcb

将普通图片处理为沉金图案或保留原色的彩色丝印，再转换成可导入嘉立创EDA专业版的 PCB 图案工程。

桌面应用使用 C++20、Qt 6 Quick/QML 和 OpenCV C++。旧版 Python 界面和二值化实现已经移除；Qt 只在最后一步调用 `img2enig.py` 生成 PCB 工程。

## 功能

- 管理多张图片图层，调整位置、显示状态和叠放顺序。
- 每个图层可选择沉金或彩色丝印。
- 提供 8 种阈值方法，包括 Triangle 和 Li 自动阈值；Try All 使用双列大图，并可直接调整算法参数后重新比较。
- 调整曝光、对比度、伽马、降噪、锐化和局部增强等参数。
- 根据图片 DPI 自动计算 PCB 物理尺寸；没有可靠 DPI 时使用 50 mm 默认宽度。
- 选择绿、红、黄、蓝、白或雅黑阻焊并导出 `.epro2`，默认使用白色阻焊。
- 自动跟随系统的浅色模式和深色模式。

## 项目结构

- `core/`：C++/OpenCV 图片处理核心。
- `app/`：Qt 后台任务、图层管理和 PCB 导出调用。
- `qml/`：Qt Quick 界面。
- `img2enig.py`：接收 C++ 输出的图层清单并生成 `.epro2`。
- `tests/`：C++ 算法、控制器和 Python PCB 导出器测试。

## 启动桌面应用

当前机器已在项目目录准备好依赖，可以直接运行：

```sh
./run-local.sh
```

也可以在启动时添加一张图片：

```sh
./run-local.sh --input /absolute/path/to/image.png
```

## 构建

依赖 CMake 3.21 以上、支持 C++20 的编译器、Qt 6.5 以上（Quick、QuickControls2、Concurrent），以及 OpenCV 4（core、imgproc、photo）。TIFF、WebP 等格式还需要 Qt 对应的图片插件。

```sh
cmake -S . -B build-native -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_PREFIX_PATH="/path/to/Qt/6.x;/path/to/opencv"
cmake --build build-native --parallel
ctest --test-dir build-native --output-on-failure
./build-native/bin/binarizer
```

使用 `-DBUILD_GUI=OFF` 可以只构建不依赖 Qt 的图片处理核心和测试。

## Python 导出环境

桌面应用只在生成 PCB 文件时调用 Python 导出器。创建虚拟环境并安装导出依赖：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

程序会优先使用项目中的 `.venv`。也可以通过 `IMAGE_BINARIZER_PYTHON` 指定其他 Python 解释器。

## 使用桌面应用

1. 在右侧点击“添加图层”，选择一张或多张图片。
2. 为沉金图层调整二值化参数，或点击 Try All 比较全部算法。
3. 设置各图层的位置、类型、显示状态和叠放顺序。
4. 选择阻焊颜色和输出目录。
5. 保存黑白图片，或生成包含所有可见图层的 PCB 文件。

## PCB 导出器接口

Qt 应用会把可见图层写入临时 JSON 清单，再调用 `img2enig.py` 完成最后一步 PCB 工程生成。Python 不再负责灰度转换或二值化：沉金输入必须是 C++ 生成的单通道纯黑白 PNG，丝印输入会保留原始颜色和透明区域。当前导出固定使用顶面和 1 mm 板边，与界面行为一致。

图层坐标使用画布像素，X 向右、Y 向下。清单格式如下：

```json
{
    "canvas": {
        "width": 1920,
        "height": 1080,
        "widthMm": 162.56,
        "heightMm": 91.44
    },
    "projectName": "角色铭牌",
    "solderMaskColor": "#191B1D",
    "layers": [
        {"source": "background.png", "type": "silk", "x": 0, "y": 0},
        {"source": "character.png", "type": "silk", "x": 420, "y": 120},
        {"source": "signature.binary.png", "type": "enig", "x": 1380, "y": 850}
    ]
}
```

```sh
.venv/bin/python img2enig.py --manifest layers.json -o output.epro2
```

清单中的相对图片路径以清单文件所在目录为基准，图层可以设置 `"visible": false` 跳过导出。Qt 会根据选中图层的 DPI 计算 `widthMm` 和 `heightMm`；没有可靠 DPI 时，Python 使用 50 mm 画布宽度并保持宽高比。

为方便调试，也保留重复的 `--layer` 参数：

```sh
.venv/bin/python img2enig.py \
    --layer background.png silk 0 0 \
    --layer signature.binary.png enig 1380 850 \
    --canvas-width 1920 \
    --canvas-height 1080 \
    --width-mm 162.56 \
    --height-mm 91.44 \
    -o output.epro2
```

每个 `--layer` 后依次填写图片路径、`enig|silk`、左上 X 和左上 Y。画布宽高和输出路径必须提供。

`.epro2` 内含 `project2.json`，以及包含 `BOARD`、`PCB`、`CONFIG` 文档的 `.epru` 日志。当前不生成 SQLite 格式的 `.eprj2`。

## 测试

```sh
cmake --build build-native --parallel
ctest --test-dir build-native --output-on-failure
.venv/bin/python -m unittest tests.test_img2enig -v
```

生产前应在嘉立创EDA中检查铜层、阻焊层、DRC、2D/3D 和 Gerber 预览，并确认最小线宽、间距和阻焊偏位符合板厂要求。
