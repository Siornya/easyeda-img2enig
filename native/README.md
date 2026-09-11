# C++ / Qt Quick 新版

二值化工具已迁移到 **C++20 + Qt 6 Quick/QML + OpenCV C++ + CMake**，界面保持原 Python 版的参数区、预览区和底部操作布局。

本阶段已实现：

- 7 种阈值方法：Fixed、Adaptive、Otsu、Sauvola、Wolf、Nick、Bernsen。
- 曝光、对比度、伽马、4 种降噪、平滑、锐化、均衡化、CLAHE、细节/边缘/局部对比度增强、反相和翻转。
- Try All：最长边 640 像素的预览，预处理一次后共用输入，后台比较所有算法。
- 选择候选后以完整原图分辨率重新处理，并输出无损黑白 PNG。
- 参数变化后的实时预览、任务取消和逐算法错误显示。

## 构建

依赖：CMake >= 3.21、C++20 编译器、Qt >= 6.5（Quick、QuickControls2、Concurrent）、OpenCV 4（core、imgproc、photo）。

```sh
cmake -S . -B build-native -DCMAKE_BUILD_TYPE=Release \
	-DCMAKE_PREFIX_PATH="/path/to/Qt/6.x/macos;/path/to/opencv"
cmake --build build-native --parallel
ctest --test-dir build-native --output-on-failure
./build-native/bin/binarizer
```

本机依赖准备完成后可以直接运行：

```sh
./native/run-local.sh
```

可通过 `--input /absolute/path/to/image.png` 启动时打开图片。
