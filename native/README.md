# C++ 二值化核心

图片处理算法正在迁移到 **C++20 + OpenCV C++ + CMake**。本阶段包含 7 种阈值方法和原 Python 版的预处理参数，并保留像素结果对照工具。

```sh
cmake -S . -B build-native -DCMAKE_BUILD_TYPE=Release \
	-DCMAKE_PREFIX_PATH="/path/to/opencv"
cmake --build build-native --parallel
ctest --test-dir build-native --output-on-failure
```

重跑迁移对照：

```sh
.venv/bin/python native/tests/compare_legacy.py build-native/bin/legacy_parity
```
