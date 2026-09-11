#pragma once
#include <opencv2/core.hpp>
#include <array>
#include <string_view>

namespace binarizer {
enum class Method { Fixed, Adaptive, Otsu, Sauvola, Wolf, Nick, Bernsen };
inline constexpr std::array methods {Method::Fixed, Method::Adaptive, Method::Otsu,
	Method::Sauvola, Method::Wolf, Method::Nick, Method::Bernsen};
std::string_view name(Method method);
struct Options {
	Method method = Method::Adaptive;
	int threshold = 127;
	int blockSize = 31;
	double adaptiveC = 5;
	double localK = 0.2;
	int denoiseMethod = 0;
	int denoiseStrength = 0;
	int exposure = 0;
	int contrast = 0;
	double gamma = 1;
	int smooth = 0;
	int sharpen = 0;
	bool equalize = false;
	bool clahe = false;
	int detail = 0;
	int edge = 0;
	int localContrast = 0;
	bool invert = false;
	bool flipHorizontal = false;
	bool flipVertical = false;
	// Zero retains the original resolution. Previews pass a separate size limit.
	int maxDimension = 0;
};
// Core has no Qt, Python or UI dependency. Input is uint8 gray/BGR/BGRA.
cv::Mat preprocess(const cv::Mat& source, const Options& options);
cv::Mat threshold(const cv::Mat& gray, const Options& options);
cv::Mat process(const cv::Mat& source, const Options& options);
}
