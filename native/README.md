# C++ / Qt Quick 新版

逐步迁移到 **C++20 + Qt 6 Quick/QML + OpenCV C++ + CMake**。
旧版 Python GUI 和 PCB 导出器保持可用。新功能从这一版开始实现。

本阶段已实现：

- 7 种阈值方法：Fixed、Adaptive、Otsu、Sauvola、Wolf、Nick、Bernsen。
- 曝光、对比度、伽马、4 种降噪、平滑、锐化、均衡化、CLAHE、细节/边缘/局部对比度增强、反相和翻转。
- Try All：最长边 640 像素的预览，预处理一次后共用输入，后台依次比较所有算法。
- 主界面沿用旧版 Python GUI 的布局：左侧分组参数、中间大图预览、右侧图层栏、底部输出目录和操作按钮。
- 参数变化后自动更新右侧预览；Try All 放在独立对比窗口中，选中方案后返回主界面。
- 方案名称、关键参数、逐算法错误、原图对照。
- 选择候选后在后台重新处理完整原图，输出无损黑白 PNG。
- 参数变化清除旧结果；取消会在当前 OpenCV 操作完成后停止，不发布过期结果。
- “生成PCB文件”在后台调用现有 `img2enig.py`，继续生成可导入嘉立创EDA专业版的 `.epro2` 文件。
- PCB 导出优先按原图 DPI 自动计算物理尺寸；没有可靠 DPI 时沿用 50 mm 图案宽度和 1 mm 边距。
- 右侧图层栏可管理多张图片，支持选择、显示/隐藏、排序、删除，并可为每层选择“沉金”或“丝印”。
- 选中图层时，底部状态栏显示一次图层名称和源图片路径。
- 选中图层可输入左上 X/Y 或中心 X/Y 坐标，两组坐标会按图层像素尺寸自动换算；右下角显示画布总体 X/Y 大小。
- 丝印图层保留原图颜色和透明区域；合成预览显示所选阻焊底色、金色沉金图案和彩色丝印。
- 右下角可选择绿、红、黄、蓝、白或雅黑阻焊，所选颜色会同步写入导出的工程配置。

缩略图上的局部窗口仍以预览像素计，因此局部算法在完整原图上的细节可能不同。
实际保存使用完整原图重新计算的结果，不保存放大的缩略图。
默认完整分辨率，与旧版默认限制 3840 像素不同。

## 构建

依赖：CMake >= 3.21、C++20 编译器、Qt >= 6.5（Quick、QuickControls2、Concurrent）、OpenCV 4（core、imgproc、photo）。
TIFF/WebP 等图片格式还需 Qt 对应图片插件；解码失败会显示错误。

```sh
cmake -S . -B build-native -DCMAKE_BUILD_TYPE=Release \
	-DCMAKE_PREFIX_PATH="/path/to/Qt/6.x/macos;/path/to/opencv"
cmake --build build-native --parallel
ctest --test-dir build-native --output-on-failure
./build-native/bin/binarizer
```

可用 `-DBUILD_GUI=OFF` 单独构建和测试不依赖 Qt 的算法库。
新程序运行时不调用 Python。`.native-tools/`、`.native-deps/` 和 `build-native/` 是忽略的本地依赖/构建目录。

## 使用

1. 点击右侧“添加图层”选择图片；修改参数只更新当前选中的图层。
2. 点击候选的“应用”按钮。
3. 在右侧设置每层的沉金/丝印类型、可见性和叠放顺序；丝印直接使用原图颜色，沉金使用当前二值化结果。
4. 在右下角选择阻焊颜色，再点击“生成PCB文件”。程序会合并所有可见图层，按原图 DPI 计算图案尺寸，并在输出目录生成同名 `.epro2`。状态栏会显示图案和板框的毫米尺寸。

新版应用本身不使用 Python 处理界面或二值化，但 PCB 导出仍需要项目的 `.venv`，其中应安装 `numpy` 和 `opencv-python-headless`。也可以通过 `IMAGE_BINARIZER_PYTHON` 环境变量指定其他 Python 解释器。

## 迁移边界

- `core/`：纯 C++/OpenCV 算法与参数，不依赖 Qt、QML 或 Python。
- `app/`：后台任务、参数快照、候选模型、图片提供器、文件输入输出。
- `qml/`：参数编辑、比较网格、结果选择和预览。
- `tests/`：算法性质与后台比较/全尺寸保存/取消/失效流程测试。

后续加入图层缩放和旋转，再迁移工程文档与文字/矢量图层。PCB 导出器可以继续作为独立 Python 模块维护。
当前尚未实现工程保存和 GPU 算法。
未来内容图层与制造层分离，文字保留矢量，图片分类用标签图；GUI 渲染加速不等于算法自动 GPU 化。

Qt 集成采用官方的 [QML CMake 模块](https://doc.qt.io/qt-6/qt-add-qml-module.html)、[Qt Concurrent](https://doc.qt.io/qt-6/qtconcurrentrun.html) 和 [图像提供器](https://doc.qt.io/qt-6/qquickimageprovider.html)。

## 当前机器启动与验证

本机依赖已经安装在项目目录，可以直接启动：

```sh
./native/run-local.sh
```

也可通过 `--input /absolute/path/to/image.png` 启动时打开图片。
本地 Qt 6.8.3 使用已安装的 macOS 15.4 SDK 构建，避免新 SDK 移除 AGL 导致的链接失败。
启动脚本仅针对本机已准备的依赖；其他机器请使用上面的通用构建步骤。

本次验证：

- CTest：算法与控制器两组测试通过。
- Python：11 项测试通过，包含彩色丝印与阻焊颜色导出检查。
- 5 组参数 × 7 种算法：与旧版像素结果完全一致。
- 实际打包的 QML 场景：加载、比较、应用、截图和正常退出通过。

重跑迁移对照（需要旧版 Python 依赖）：

```sh
.venv/bin/python native/tests/compare_legacy.py build-native/bin/legacy_parity
```

该对照允许最多 0.2% 的阈值边界像素差异，以容纳不同 OpenCV 版本和浮点舍入；本机实测差异为 0%。
