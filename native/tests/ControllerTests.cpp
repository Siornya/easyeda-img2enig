#include "Controller.hpp"
#include <QGuiApplication>
#include <QElapsedTimer>
#include <QTemporaryDir>
#include <QThread>
#include <iostream>
#include <stdexcept>

static void check(bool condition, const char* message) {
	if (!condition) throw std::runtime_error(message);
}
static void wait(Controller& controller) {
	QElapsedTimer timer;
	timer.start();
	while (controller.busy() && timer.elapsed() < 10000) {
		QGuiApplication::processEvents();
		QThread::msleep(2);
	}
	check(!controller.busy(), "Worker timeout");
}
int main(int argc, char** argv) {
	QGuiApplication app(argc, argv);
	ImageStore images;
	Controller controller(&images);
	QTemporaryDir directory;
	try {
		QImage source(1200, 800, QImage::Format_Grayscale8);
		for (int y = 0; y < source.height(); ++y)
			for (int x = 0; x < source.width(); ++x) source.scanLine(y)[x] = (x + y) % 256;
		const auto path = directory.filePath(QStringLiteral("输入.png"));
		check(source.save(path), "Cannot create fixture");
		const auto url = QUrl::fromLocalFile(path);
		check(controller.localPath(url) == path, "Local URL conversion failed");
		check(controller.fileUrl(path) == url, "Local path conversion failed");
		check(controller.sourceDirectory(url) == directory.path(), "Source directory failed");
		check(controller.outputFile(url, {}).toLocalFile().endsWith("输入.binary.png"), "Automatic output name failed");
		controller.preview(url, {}, 1);
		wait(controller);
		check(!controller.resultUrl().isEmpty(), "Main preview failed");
		QSize previewSize;
		images.requestImage("selected", &previewSize, {});
		check(previewSize == source.size(), "Main preview lost resolution");
		controller.compare(url, {});
		wait(controller);
		check(controller.candidates().size() == 7, "Missing candidates");
		for (const auto& candidate : controller.candidates()) {
			check(candidate.toMap().value("error").toString().isEmpty(), "Candidate failed");
			const auto key = candidate.toMap().value("image").toString().mid(QString("image://results/").size());
			QSize size;
			check(!images.requestImage(key, &size, {}).isNull(), "Missing image");
			check(size.width() == 640, "Preview was not bounded");
		}
		controller.apply(2);
		wait(controller);
		check(!controller.resultUrl().isEmpty(), "Selection failed");
		const auto outputPath = directory.filePath(QStringLiteral("输出.png"));
		controller.save(QUrl::fromLocalFile(outputPath));
		QImage output(outputPath);
		check(output.size() == source.size(), "Saved thumbnail instead of original resolution");
		for (int y = 0; y < output.height(); ++y)
			for (int x = 0; x < output.width(); ++x) {
				const auto value = qGray(output.pixel(x, y));
				check(value == 0 || value == 255, "Non-binary saved pixel");
			}
		controller.invalidate();
		check(controller.candidates().isEmpty() && controller.resultUrl().isEmpty(), "Stale results remain");
		controller.compare(url, {});
		controller.cancel();
		wait(controller);
		check(controller.candidates().isEmpty(), "Cancelled results published");
		controller.compare(QUrl::fromLocalFile(directory.filePath("missing.png")), {});
		wait(controller);
		check(controller.candidates().isEmpty(), "Failed input published results");
		std::cout << "PASS: comparison, image store, full-size selection, invalidation, cancel and load failure\n";
	} catch (const std::exception& error) {
		std::cerr << error.what() << '\n';
		controller.cancel();
		wait(controller);
		return 1;
	}
}
