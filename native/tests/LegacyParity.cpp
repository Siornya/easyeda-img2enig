#include "Binarizer.hpp"
#include <fstream>
#include <string>

int main(int argc, char** argv) {
	if (argc != 2) return 1;
	const std::string root = argv[1];
	cv::Mat source(128, 256, CV_8UC1);
	std::ifstream input(root + "/input.raw", std::ios::binary);
	if (!input.read(reinterpret_cast<char*>(source.data), source.total())) return 2;
	for (int preset = 0; preset < 5; ++preset) {
		binarizer::Options options;
		if (preset == 1) { options.exposure = 12; options.contrast = -15; options.gamma = 1.3; }
		if (preset == 2) { options.denoiseStrength = 20; options.sharpen = 15; options.clahe = true; }
		if (preset == 3) { options.invert = true; options.flipHorizontal = true; options.flipVertical = true; }
		if (preset == 4) { options.blockSize = 15; options.localK = 0.35; options.adaptiveC = -3; options.threshold = 160; }
		for (int i = 0; i < int(binarizer::methods.size()); ++i) {
			options.method = binarizer::methods[i];
			const auto output = binarizer::process(source, options);
			std::ofstream file(root + "/" + std::to_string(preset) + "-" + std::to_string(i) + ".raw", std::ios::binary);
			file.write(reinterpret_cast<const char*>(output.data), output.total());
			if (!file) return 3;
		}
	}
}
