# easyeda-arknights-enig

将普通图片处理为沉金图案或保留原色的彩色丝印，再转换成可导入嘉立创EDA专业版的 PCB 图案工程。

桌面应用使用 C++20、Qt 6 Quick/QML 和 OpenCV C++。旧版 Python 界面和二值化实现已经移除；`img2enig.py` 作为独立 PCB 导出器继续使用。

## 功能

- 管理多张图片图层，调整位置、显示状态和叠放顺序。
- 每个图层可选择沉金或彩色丝印。
- 提供 7 种阈值方法和 Try All 多方案比较。
- 调整曝光、对比度、伽马、降噪、锐化和局部增强等参数。
- 根据图片 DPI 自动计算 PCB 物理尺寸；没有可靠 DPI 时使用 50 mm 默认宽度。
- 选择绿、红、黄、蓝、白或雅黑阻焊并导出 `.epro2`。

## 项目结构

- `core/`：C++/OpenCV 图片处理核心。
- `app/`：Qt 后台任务、图层管理和 PCB 导出调用。
- `qml/`：Qt Quick 界面。
- `img2enig.py`：把沉金掩膜和彩色丝印转换成 `.epro2`。
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

## 单独使用 PCB 导出器

`img2enig.py` 的沉金和传统单色丝印输入必须是像素值为 `0` 或 `255` 的纯黑白图片。彩色丝印输入会保留原始 RGBA 颜色和透明区域。

导出沉金图案：

```sh
.venv/bin/python img2enig.py input.binary.png -o output.epro2
```

指定尺寸和板边：

```sh
.venv/bin/python img2enig.py input.binary.png \
    -o output.epro2 \
    --width-mm 40 \
    --margin-mm 2
```

导出彩色丝印并设置阻焊颜色：

```sh
.venv/bin/python img2enig.py silk.png \
    --source-type color-silk \
    --solder-mask-color '#164D73'
```

为沉金图案添加彩色丝印：

```sh
.venv/bin/python img2enig.py enig.binary.png \
    --color-silk silk.png \
    --solder-mask-color '#191B1D'
```

检查生成的工程：

```sh
.venv/bin/python img2enig.py output.epro2 --inspect
```

`.epro2` 内含 `project2.json`，以及包含 `BOARD`、`PCB`、`CONFIG` 文档的 `.epru` 日志。当前不生成 SQLite 格式的 `.eprj2`。

## 测试

```sh
cmake --build build-native --parallel
ctest --test-dir build-native --output-on-failure
.venv/bin/python -m unittest tests.test_img2enig -v
```

生产前应在嘉立创EDA中检查铜层、阻焊层、DRC、2D/3D 和 Gerber 预览，并确认最小线宽、间距和阻焊偏位符合板厂要求。
