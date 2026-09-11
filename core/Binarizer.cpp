#include "Binarizer.hpp"
#include <opencv2/imgproc.hpp>
#include <opencv2/photo.hpp>
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace binarizer {
std::string_view name(Method method) {
	switch (method) {
	case Method::Fixed: return "Fixed";
	case Method::Adaptive: return "Adaptive";
	case Method::Otsu: return "Otsu";
	case Method::Sauvola: return "Sauvola";
	case Method::Wolf: return "Wolf";
	case Method::Nick: return "Nick";
	case Method::Bernsen: return "Bernsen";
	}
	throw std::invalid_argument("Unknown threshold method");
}
static void validate(const Options& o) {
	if (o.threshold < 0 || o.threshold > 255 || o.blockSize < 3 || o.blockSize % 2 == 0
		|| !std::isfinite(o.gamma) || o.gamma <= 0 || o.maxDimension < 0
		|| !std::isfinite(o.adaptiveC) || std::abs(o.adaptiveC) > 100
		|| !std::isfinite(o.localK) || std::abs(o.localK) > 1
		|| std::abs(o.exposure) > 100 || std::abs(o.contrast) > 100
		|| o.denoiseMethod < 0 || o.denoiseMethod > 3)
		throw std::invalid_argument("Invalid binarization parameters");
	for (int value : {o.denoiseStrength, o.smooth, o.sharpen, o.detail, o.edge, o.localContrast})
		if (value < 0 || value > 100) throw std::invalid_argument("Strength must be 0..100");
}
static int kernel(int strength) {
	return strength <= 0 ? 1 : std::min(21, 2 * std::max(1, static_cast<int>(std::nearbyint(strength / 10.0))) + 1);
}
cv::Mat preprocess(const cv::Mat& source, const Options& o) {
	validate(o);
	if (source.empty() || source.depth() != CV_8U)
		throw std::invalid_argument("Expected a nonempty 8-bit image");
	cv::Mat gray;
	if (source.channels() == 1) gray = source.clone();
	else if (source.channels() == 3) cv::cvtColor(source, gray, cv::COLOR_BGR2GRAY);
	else if (source.channels() == 4) {
		cv::Mat color(source.size(), CV_8UC3);
		for (int y = 0; y < source.rows; ++y) {
			const auto* input = source.ptr<cv::Vec4b>(y);
			auto* output = color.ptr<cv::Vec3b>(y);
			for (int x = 0; x < source.cols; ++x) {
				const float alpha = input[x][3] / 255.0f;
				for (int c = 0; c < 3; ++c)
					output[x][c] = static_cast<unsigned char>(input[x][c] * alpha + 255.0f * (1 - alpha));
			}
		}
		cv::cvtColor(color, gray, cv::COLOR_BGR2GRAY);
	} else throw std::invalid_argument("Expected gray, BGR or BGRA image");
	if (o.maxDimension > 0 && std::max(gray.cols, gray.rows) > o.maxDimension) {
		const double scale = double(o.maxDimension) / std::max(gray.cols, gray.rows);
		cv::resize(gray, gray, cv::Size(std::max(1, int(std::nearbyint(gray.cols * scale))),
			std::max(1, int(std::nearbyint(gray.rows * scale)))), 0, 0, cv::INTER_AREA);
	}
	cv::Mat lut(1, 256, CV_8U);
	for (int i = 0; i < 256; ++i) {
		double v = i * std::pow(2.0, o.exposure / 50.0);
		v = std::clamp((v - 127.5) * std::max(0.0, 1 + o.contrast / 50.0) + 127.5, 0.0, 255.0);
		if (o.gamma != 1) v = 255 * std::pow(v / 255, 1 / o.gamma);
		lut.at<unsigned char>(i) = static_cast<unsigned char>(std::clamp(v, 0.0, 255.0));
	}
	cv::LUT(gray, lut, gray);
	const int k = kernel(o.denoiseStrength);
	if (o.denoiseStrength) {
		switch (o.denoiseMethod) {
		case 0: cv::GaussianBlur(gray, gray, cv::Size(k, k), 0); break;
		case 1: cv::medianBlur(gray, gray, k); break;
		case 2: {
			cv::Mat filtered;
			cv::bilateralFilter(gray, filtered, k, std::max(10, o.denoiseStrength * 2), std::max(10, o.denoiseStrength * 2));
			gray = filtered;
			break;
		}
		case 3: cv::fastNlMeansDenoising(gray, gray, float(o.denoiseStrength), 7, 21); break;
		}
	}
	if (o.smooth) cv::GaussianBlur(gray, gray, cv::Size(kernel(o.smooth), kernel(o.smooth)), 0);
	if (o.clahe) cv::createCLAHE(2.0, cv::Size(8, 8))->apply(gray, gray);
	else if (o.equalize) cv::equalizeHist(gray, gray);
	const double amount = (o.sharpen + o.detail) / 100.0;
	if (amount) {
		cv::Mat blurred;
		cv::GaussianBlur(gray, blurred, cv::Size(), 1.2);
		cv::addWeighted(gray, 1 + amount, blurred, -amount, 0, gray);
	}
	if (o.edge) {
		cv::Mat laplacian;
		cv::Laplacian(gray, laplacian, CV_32F, 3);
		for (int y = 0; y < gray.rows; ++y)
			for (int x = 0; x < gray.cols; ++x)
				gray.at<unsigned char>(y, x) = static_cast<unsigned char>(std::clamp(
					gray.at<unsigned char>(y, x) - float(o.edge / 200.0) * laplacian.at<float>(y, x), 0.0f, 255.0f));
	}
	if (o.localContrast) {
		cv::Mat enhanced;
		cv::createCLAHE(1 + o.localContrast / 25.0, cv::Size(8, 8))->apply(gray, enhanced);
		cv::addWeighted(gray, 1 - o.localContrast / 100.0, enhanced, o.localContrast / 100.0, 0, gray);
	}
	return gray;
}
cv::Mat threshold(const cv::Mat& gray, const Options& o) {
	validate(o);
	if (gray.empty() || gray.type() != CV_8UC1) throw std::invalid_argument("Expected grayscale image");
	cv::Mat binary;
	if (o.method == Method::Fixed) cv::threshold(gray, binary, o.threshold, 255, cv::THRESH_BINARY);
	else if (o.method == Method::Otsu) cv::threshold(gray, binary, 0, 255, cv::THRESH_BINARY | cv::THRESH_OTSU);
	else if (o.method == Method::Adaptive)
		cv::adaptiveThreshold(gray, binary, 255, cv::ADAPTIVE_THRESH_GAUSSIAN_C, cv::THRESH_BINARY, o.blockSize, o.adaptiveC);
	else {
		cv::Mat source, mean, squareMean, variance, deviation, thresholdMap;
		gray.convertTo(source, CV_32F);
		const cv::Size size(o.blockSize, o.blockSize);
		cv::boxFilter(source, mean, CV_32F, size);
		cv::boxFilter(source.mul(source), squareMean, CV_32F, size);
		cv::max(squareMean - mean.mul(mean), 0, variance);
		cv::sqrt(variance, deviation);
		switch (o.method) {
		case Method::Sauvola: thresholdMap = mean.mul(1 + o.localK * (deviation / 128 - 1)); break;
		case Method::Wolf: {
			double maximum, minimum;
			cv::minMaxLoc(deviation, nullptr, &maximum);
			cv::minMaxLoc(source, &minimum);
			thresholdMap = mean + o.localK * (deviation / std::max(maximum, 1e-6) - 1).mul(mean - minimum);
			break;
		}
		case Method::Nick: {
			cv::Mat root;
			cv::sqrt(variance + mean.mul(mean), root);
			thresholdMap = mean - std::abs(o.localK) * root;
			break;
		}
		case Method::Bernsen: {
			cv::Mat minimum, maximum, lo, hi;
			const auto element = cv::getStructuringElement(cv::MORPH_RECT, size);
			cv::erode(gray, minimum, element);
			cv::dilate(gray, maximum, element);
			minimum.convertTo(lo, CV_32F);
			maximum.convertTo(hi, CV_32F);
			thresholdMap = (lo + hi) / 2;
			thresholdMap.setTo(o.threshold, hi - lo < 15);
			break;
		}
		default: throw std::invalid_argument("Unknown threshold method");
		}
		cv::compare(source, thresholdMap, binary, cv::CMP_GT);
	}
	if (o.invert) cv::bitwise_not(binary, binary);
	if (o.flipHorizontal) cv::flip(binary, binary, 1);
	if (o.flipVertical) cv::flip(binary, binary, 0);
	return binary;
}
cv::Mat process(const cv::Mat& source, const Options& options) {
	return threshold(preprocess(source, options), options);
}
}
