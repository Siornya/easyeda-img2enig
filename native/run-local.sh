#!/bin/sh
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cmake_bin="$project_root/.native-tools/cmake/data/bin/cmake"
if [ ! -x "$cmake_bin" ]; then
	printf '%s\n' '本地构建工具不存在，请按 native/README.md 安装依赖并构建。' >&2
	exit 1
fi
if [ ! -x "$project_root/build-native/bin/binarizer" ]; then
	"$cmake_bin" -S "$project_root" -B "$project_root/build-native" \
		-DCMAKE_BUILD_TYPE=Release -DBUILD_GUI=ON \
		-DCMAKE_PREFIX_PATH="$project_root/.native-deps/qt;$project_root/.native-deps/opencv" \
		-DCMAKE_OSX_SYSROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk
	"$cmake_bin" --build "$project_root/build-native" --parallel
fi
exec "$project_root/build-native/bin/binarizer" "$@"
