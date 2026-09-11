#include "Binarizer.hpp"
#include <opencv2/imgproc.hpp>
#include <iostream>
#include <stdexcept>
#include <utility>

static void check(bool condition, const char* message) {
	if (!condition) throw std::runtime_error(message);
}
int main() {
	using namespace binarizer;
	try {
		cv::Mat source(80, 256, CV_8UC1);
		for (int y = 0; y < source.rows; ++y)
			for (int x = 0; x < source.cols; ++x) source.at<unsigned char>(y, x) = x;
		Options options;
		const auto original = source.clone();
		for (auto method : methods) {
			options.method = method;
			const auto result = process(source, options);
			check(result.size() == source.size(), "Output dimensions changed");
			check(cv::countNonZero((result != 0) & (result != 255)) == 0, "Output is not binary");
			const auto prepared = preprocess(source, options);
			check(cv::countNonZero(result != threshold(prepared, options)) == 0, "Shared preprocessing differs");
			for (int level : {0, 128, 255}) {
				const auto flat = process(cv::Mat(1, 1, CV_8UC1, cv::Scalar(level)), options);
				check(flat.rows == 1 && flat.cols == 1, "Tiny image failed");
			}
		}
		check(cv::countNonZero(source != original) == 0, "Source was mutated");
		cv::Mat liSample(1, 100, CV_8UC1);
		int offset = 0;
		for (const auto [level, count] : {std::pair{0, 20}, std::pair{20, 40},
			std::pair{60, 10}, std::pair{120, 15}, std::pair{200, 10}, std::pair{250, 5}})
			for (int index = 0; index < count; ++index) liSample.at<unsigned char>(offset++) = level;
		options.method = Method::Li;
		check(cv::countNonZero(process(liSample, options)) == 30, "Li threshold is incorrect");
		options.method = Method::Fixed;
		options.maxDimension = 64;
		check(process(source, options).size() == cv::Size(64, 20), "Preview dimensions incorrect");
		options.maxDimension = 0;
		cv::Mat alpha(1, 2, CV_8UC4, cv::Scalar(0, 0, 0, 0));
		alpha.at<cv::Vec4b>(0, 1)[3] = 255;
		auto binary = process(alpha, options);
		check(binary.at<unsigned char>(0, 0) == 255 && binary.at<unsigned char>(0, 1) == 0, "Alpha compositing failed");
		options.flipHorizontal = true;
		binary = process(alpha, options);
		check(binary.at<unsigned char>(0, 0) == 0, "Flip failed");
		options.invert = true;
		binary = process(alpha, options);
		check(binary.at<unsigned char>(0, 0) == 255, "Invert failed");
		bool rejected = false;
		try { options.blockSize = 4; process(source, options); }
		catch (const std::invalid_argument&) { rejected = true; }
		check(rejected, "Invalid window accepted");
		std::cout << "PASS: all algorithms, tiny/flat images, shared preprocessing, alpha, dimensions, transforms, validation\n";
	} catch (const std::exception& error) {
		std::cerr << error.what() << '\n';
		return 1;
	}
}
