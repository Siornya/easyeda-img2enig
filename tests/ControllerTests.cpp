#include "Controller.hpp"
#include <QGuiApplication>
#include <QElapsedTimer>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickStyle>
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
	QQuickStyle::setStyle(QStringLiteral("Fusion"));
	ImageStore images;
	Controller controller(&images);
	QTemporaryDir directory;
	try {
		QImage source(1200, 800, QImage::Format_Grayscale8);
		source.setDotsPerMeterX(11811);
		source.setDotsPerMeterY(11811);
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
		{
			QQmlApplicationEngine engine;
			engine.rootContext()->setContextProperty("controller", &controller);
			engine.load(QUrl::fromLocalFile(QStringLiteral(BINARIZER_SOURCE_DIR "/qml/Main.qml")));
			check(!engine.rootObjects().isEmpty(), "Main QML scene failed to load");
			check(QMetaObject::invokeMethod(engine.rootObjects().front(), "setLayerMaterial",
				Q_ARG(QVariant, QVariant(0)), Q_ARG(QVariant, QVariant(1))),
				"Cannot invoke QML layer type selection");
			check(controller.layerRows()[0].toMap().value("type") == QStringLiteral("silk"),
				"QML silkscreen selection changed the wrong layer");
			controller.setLayerType(0, QStringLiteral("enig"));
		}
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
		QImage signature(400, 200, QImage::Format_ARGB32);
		signature.setDotsPerMeterX(11811);
		signature.setDotsPerMeterY(11811);
		signature.fill(Qt::transparent);
		for (int y = 60; y < 140; ++y)
			for (int x = 40; x < 360; ++x) signature.setPixelColor(x, y, QColor(231, 48, 62));
		const auto signaturePath = directory.filePath(QStringLiteral("签名.png"));
		check(signature.save(signaturePath), "Cannot create layer fixture");
		controller.preview(QUrl::fromLocalFile(signaturePath), {}, 1);
		wait(controller);
		check(controller.layerRows().size() == 2, "Second image did not create a layer");
		check(controller.selectedLayerIndex() == 0, "New layer was not selected");
		check(controller.canvasWidth() == 1200 && controller.canvasHeight() == 800, "Canvas size changed unexpectedly");
		const auto centeredLayer = controller.layerRows()[0].toMap();
		check(centeredLayer.value("leftX").toDouble() == 400.0, "New layer was not horizontally centered");
		check(centeredLayer.value("topY").toDouble() == 300.0, "New layer was not vertically centered");
		controller.setLayerTopLeft(0, 100.0, 120.0);
		check(controller.layerRows()[0].toMap().value("centerX").toDouble() == 300.0, "Top-left X did not update center X");
		check(controller.layerRows()[0].toMap().value("centerY").toDouble() == 220.0, "Top-left Y did not update center Y");
		controller.setLayerTopLeft(0, 1000.0, 700.0);
		check(controller.canvasWidth() == 1400 && controller.canvasHeight() == 900, "Canvas did not expand around a moved layer");
		controller.setLayerCenter(0, 600.0, 400.0);
		check(controller.layerRows()[0].toMap().value("leftX").toDouble() == 400.0, "Center X did not update top-left X");
		check(controller.layerRows()[0].toMap().value("topY").toDouble() == 300.0, "Center Y did not update top-left Y");
		controller.setLayerType(0, QStringLiteral("silk"));
		check(controller.layerRows()[0].toMap().value("type").toString() == QStringLiteral("silk"), "Layer type did not change");
		check(!controller.compositeUrl().isEmpty(), "Layer composite preview is missing");
		QImage composite = images.requestImage("composite", nullptr, {});
		check(composite.pixelColor(450, 370) == QColor(231, 48, 62), "Silkscreen preview did not preserve source color");
		controller.setLayerVisible(1, false);
		controller.setSolderMaskColor(QStringLiteral("blue"));
		check(controller.solderMaskColor() == QStringLiteral("blue"), "Solder-mask selection did not change");
		composite = images.requestImage("composite", nullptr, {});
		check(composite.pixelColor(0, 0) == QColor(QStringLiteral("#164d73")), "Solder-mask preview color did not change");
		controller.setLayerVisible(1, true);
		controller.selectLayer(1);
		check(controller.selectedSourceUrl() == url.toString(), "Layer selection did not restore its source");
		check(controller.status().contains(path), "Layer selection did not report its source path");
		controller.generatePcb(url, directory.path());
		wait(controller);
		const auto pcbPath = directory.filePath(QStringLiteral("输入.epro2"));
		check(QFileInfo::exists(pcbPath), "Python PCB exporter did not create output");
		check(QFileInfo(pcbPath).size() > 0, "Python PCB exporter created an empty file");
		check(controller.status().contains(QStringLiteral("已生成 PCB 文件")), "PCB export status failed");
		check(controller.status().contains(QStringLiteral("按图片 DPI")), "PCB export ignored image DPI");
		check(controller.status().contains(QStringLiteral("图案 101.60 × 67.73 mm")), "PCB export calculated the wrong physical size");
		controller.moveLayer(1, -1);
		check(controller.selectedLayerIndex() == 0, "Moving a layer lost selection");
		controller.setLayerVisible(1, false);
		check(!controller.layerRows()[1].toMap().value("visible").toBool(), "Layer visibility did not change");
		controller.removeLayer(1);
		check(controller.layerRows().size() == 1, "Layer deletion failed");
		controller.invalidate();
		check(controller.candidates().isEmpty() && controller.resultUrl().isEmpty(), "Stale results remain");
		controller.compare(url, {});
		controller.cancel();
		wait(controller);
		check(controller.candidates().isEmpty(), "Cancelled results published");
		controller.compare(QUrl::fromLocalFile(directory.filePath("missing.png")), {});
		wait(controller);
		check(controller.candidates().isEmpty(), "Failed input published results");
		std::cout << "PASS: comparison, image store, full-size selection/export, invalidation, cancel and load failure\n";
	} catch (const std::exception& error) {
		std::cerr << error.what() << '\n';
		controller.cancel();
		wait(controller);
		return 1;
	}
}
