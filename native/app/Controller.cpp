#include "Controller.hpp"
#include <QFileInfo>
#include <QFutureWatcher>
#include <QImageReader>
#include <QMutexLocker>
#include <QPainter>
#include <QProcess>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QTimer>
#include <QtConcurrent/QtConcurrentRun>
#include <QDir>
#include <stdexcept>
#include <opencv2/imgproc.hpp>
#include <algorithm>
#include <cmath>
#include <vector>

QImage ImageStore::requestImage(const QString& id, QSize* size, const QSize& requested) {
	QMutexLocker lock(&mutex);
	QImage image = images.value(id.section('?', 0, 0));
	if (size) *size = image.size();
	if (requested.isValid()) image = image.scaled(requested, Qt::KeepAspectRatio, Qt::FastTransformation);
	return image;
}
void ImageStore::put(const QString& id, const QImage& image) {
	QMutexLocker lock(&mutex);
	images.insert(id, image);
}
void ImageStore::clear() {
	QMutexLocker lock(&mutex);
	images.clear();
}
static QImage display(const cv::Mat& binary) {
	return QImage(binary.data, binary.cols, binary.rows, int(binary.step), QImage::Format_Grayscale8).copy();
}
struct Comparison {
	cv::Mat source;
	QImage original;
	int dotsPerMeterX = 0;
	int dotsPerMeterY = 0;
	bool hasPhysicalResolution = false;
	std::vector<QImage> previews;
	std::vector<QString> errors;
	QString error;
};
struct Applied {
	QImage image;
	QString error;
};

static QColor solderMaskPreviewColor(const QString& color) {
	if (color == QStringLiteral("red")) return QColor(QStringLiteral("#78242b"));
	if (color == QStringLiteral("yellow")) return QColor(QStringLiteral("#b58b22"));
	if (color == QStringLiteral("blue")) return QColor(QStringLiteral("#164d73"));
	if (color == QStringLiteral("white")) return QColor(QStringLiteral("#ecebe6"));
	if (color == QStringLiteral("black")) return QColor(QStringLiteral("#191b1d"));
	return QColor(QStringLiteral("#264f3a"));
}

static QString solderMaskExportColor(const QString& color) {
	return solderMaskPreviewColor(color).name(QColor::HexRgb).toUpper();
}
Controller::Controller(ImageStore* images, QObject* parent) : QObject(parent), images(images) {}
Controller::~Controller() {
	if (cancelled) cancelled->store(true);
	if (pcbProcess) {
		pcbProcess->kill();
		pcbProcess->waitForFinished();
	}
}
void Controller::invalidate() {
	if (active) return;
	rows.clear();
	result.clear();
	output = {};
	if (selectedLayer >= 0 && selectedLayer < int(artworkLayers.size()))
		artworkLayers[selectedLayer].outputImage = {};
	refreshLayerPresentation();
	message = QStringLiteral("设置已更新，请点击 Try All 重新比较");
	emit changed();
}
QString Controller::localPath(const QUrl& url) const { return url.toLocalFile(); }
QUrl Controller::fileUrl(const QString& path) const { return QUrl::fromLocalFile(path); }
QString Controller::sourceDirectory(const QUrl& source) const { return QFileInfo(source.toLocalFile()).absolutePath(); }
QString Controller::selectedSourceUrl() const {
	if (selectedLayer < 0 || selectedLayer >= int(artworkLayers.size())) return {};
	return QUrl::fromLocalFile(artworkLayers[selectedLayer].sourcePath).toString();
}
QVariantMap Controller::selectedParameters() const {
	if (selectedLayer < 0 || selectedLayer >= int(artworkLayers.size())) return {};
	const auto& options = artworkLayers[selectedLayer].settings;
	return {
		{"method", int(options.method)}, {"threshold", options.threshold},
		{"blockSize", options.blockSize}, {"adaptiveC", options.adaptiveC},
		{"localK", options.localK}, {"exposure", options.exposure},
		{"contrast", options.contrast}, {"gamma", options.gamma},
		{"denoiseMethod", options.denoiseMethod}, {"denoiseStrength", options.denoiseStrength},
		{"smooth", options.smooth}, {"sharpen", options.sharpen},
		{"detail", options.detail}, {"edge", options.edge},
		{"localContrast", options.localContrast}, {"equalize", options.equalize},
		{"clahe", options.clahe}, {"invert", options.invert},
		{"flipHorizontal", options.flipHorizontal}, {"flipVertical", options.flipVertical}
	};
}
bool Controller::hasExportableLayers() const {
	return std::any_of(artworkLayers.cbegin(), artworkLayers.cend(), [](const ArtworkLayer& layer) {
		return layer.visible && (layer.type == QStringLiteral("silk")
			? !layer.originalImage.isNull() : !layer.outputImage.isNull());
	});
}
int Controller::canvasWidth() const { return canvasSize().width(); }
int Controller::canvasHeight() const { return canvasSize().height(); }
QUrl Controller::outputFile(const QUrl& source, const QString& directory) const {
	const QFileInfo file(source.toLocalFile());
	return QUrl::fromLocalFile(QDir(directory.isEmpty() ? file.absolutePath() : directory)
		.filePath(file.completeBaseName() + ".binary.png"));
}
void Controller::compare(const QUrl& url, const QVariantMap& p) { run(url, p, -1); }
void Controller::preview(const QUrl& url, const QVariantMap& p, int method) {
	if (method < 0 || method >= int(binarizer::methods.size())) return;
	run(url, p, method);
}
void Controller::run(const QUrl& url, const QVariantMap& p, int singleMethod) {
	if (active) return;
	if (!url.isLocalFile()) {
		message = QStringLiteral("请先选择本地图片");
		emit changed();
		return;
	}
	rows.clear();
	binarizer::Options requestedSettings;
	requestedSettings.threshold = p.value("threshold", 127).toInt();
	requestedSettings.blockSize = p.value("blockSize", 31).toInt();
	requestedSettings.adaptiveC = p.value("adaptiveC", 5).toDouble();
	requestedSettings.localK = p.value("localK", 0.2).toDouble();
	requestedSettings.exposure = p.value("exposure", 0).toInt();
	requestedSettings.contrast = p.value("contrast", 0).toInt();
	requestedSettings.gamma = p.value("gamma", 1).toDouble();
	requestedSettings.denoiseMethod = p.value("denoiseMethod", 0).toInt();
	requestedSettings.denoiseStrength = p.value("denoiseStrength", 0).toInt();
	requestedSettings.smooth = p.value("smooth", 0).toInt();
	requestedSettings.sharpen = p.value("sharpen", 0).toInt();
	requestedSettings.detail = p.value("detail", 0).toInt();
	requestedSettings.edge = p.value("edge", 0).toInt();
	requestedSettings.localContrast = p.value("localContrast", 0).toInt();
	requestedSettings.equalize = p.value("equalize", false).toBool();
	requestedSettings.clahe = p.value("clahe", false).toBool();
	requestedSettings.invert = p.value("invert", false).toBool();
	requestedSettings.flipHorizontal = p.value("flipHorizontal", false).toBool();
	requestedSettings.flipVertical = p.value("flipVertical", false).toBool();
	settings = requestedSettings;
	const QString sourcePath = url.toLocalFile();
	const bool createLayer = selectedLayer < 0 || selectedLayer >= int(artworkLayers.size())
		|| artworkLayers[selectedLayer].sourcePath != sourcePath;
	const int targetLayerId = createLayer ? 0 : artworkLayers[selectedLayer].id;
	active = true;
	message = singleMethod < 0 ? QStringLiteral("正在生成 7 种方案…") : QStringLiteral("正在更新预览…");
	cancelled = std::make_shared<std::atomic_bool>(false);
	const auto stop = cancelled;
	auto options = requestedSettings;
	options.maxDimension = singleMethod < 0 ? 640 : 0;
	auto* watcher = new QFutureWatcher<Comparison>(this);
	connect(watcher, &QFutureWatcher<Comparison>::finished, this,
		[this, watcher, stop, singleMethod, sourcePath, requestedSettings, createLayer, targetLayerId] {
		const auto batch = watcher->result();
		watcher->deleteLater();
		active = false;
		if (stop->load()) message = QStringLiteral("已取消");
		else if (!batch.error.isEmpty()) message = batch.error;
		else {
			int targetIndex = -1;
			const QSize placementCanvas = canvasSize();
			if (createLayer) {
				ArtworkLayer layer;
				layer.id = nextLayerId++;
				layer.name = QFileInfo(sourcePath).completeBaseName();
				layer.sourcePath = sourcePath;
				artworkLayers.insert(artworkLayers.begin(), std::move(layer));
				targetIndex = 0;
			} else {
				for (int index = 0; index < int(artworkLayers.size()); ++index)
					if (artworkLayers[index].id == targetLayerId) targetIndex = index;
			}
			if (targetIndex < 0) {
				message = QStringLiteral("目标图层已不存在");
				emit changed();
				return;
			}
			auto& layer = artworkLayers[targetIndex];
			layer.sourceImage = batch.source;
			layer.originalImage = batch.original;
			layer.settings = requestedSettings;
			layer.dotsPerMeterX = batch.dotsPerMeterX;
			layer.dotsPerMeterY = batch.dotsPerMeterY;
			layer.hasPhysicalResolution = batch.hasPhysicalResolution;
			if (createLayer) {
				const QSize size = layerSize(layer);
				if (minimumCanvasWidth == 0 || minimumCanvasHeight == 0) {
					minimumCanvasWidth = size.width();
					minimumCanvasHeight = size.height();
				} else {
					layer.x = std::max(0.0, (placementCanvas.width() - size.width()) / 2.0);
					layer.y = std::max(0.0, (placementCanvas.height() - size.height()) / 2.0);
				}
			}
			selectedLayer = targetIndex;
			++revision;
			const QString key = QString::number(revision) + "/original";
			images->put(key, batch.original);
			original = "image://results/" + key;
			if (singleMethod >= 0) {
				if (!batch.errors.front().isEmpty()) message = batch.errors.front();
				else {
					layer.outputImage = batch.previews.front();
					message = QStringLiteral("图层“%1”处理完成：%2 × %3")
						.arg(layer.name).arg(layer.outputImage.width()).arg(layer.outputImage.height());
				}
				loadSelectedLayer();
				refreshLayerPresentation();
				emit changed();
				return;
			}
			for (int i = 0; i < int(batch.previews.size()); ++i) {
				const auto method = binarizer::methods[i];
				const QString id = QString::number(revision) + "/" + QString::number(i);
				images->put(id, batch.previews[i]);
				QString parameters;
				if (method == binarizer::Method::Otsu) parameters = QStringLiteral("自动阈值");
				else if (method == binarizer::Method::Fixed) parameters = QStringLiteral("阈值 %1").arg(settings.threshold);
				else if (method == binarizer::Method::Adaptive) parameters = QStringLiteral("窗口 %1 · C %2").arg(settings.blockSize).arg(settings.adaptiveC);
				else if (method == binarizer::Method::Bernsen) parameters = QStringLiteral("窗口 %1 · 回退阈值 %2").arg(settings.blockSize).arg(settings.threshold);
				else parameters = QStringLiteral("窗口 %1 · k %2").arg(settings.blockSize).arg(method == binarizer::Method::Nick ? -std::abs(settings.localK) : settings.localK);
				rows.append(QVariantMap{{"name", QString::fromUtf8(binarizer::name(method).data())},
					{"image", batch.previews[i].isNull() ? QString() : "image://results/" + id},
					{"parameters", parameters}, {"error", batch.errors[i]}});
			}
			message = QStringLiteral("选择一个方案，以原始分辨率重新处理。局部算法的缩略预览与原图细节可能不同。");
			loadSelectedLayer();
			refreshLayerPresentation();
		}
		emit changed();
	});
	watcher->setFuture(QtConcurrent::run([path = url.toLocalFile(), options, stop, singleMethod] {
		Comparison batch;
		try {
			QImageReader reader(path);
			QImage image = reader.read();
			if (image.isNull()) throw std::runtime_error(reader.errorString().toStdString());
			batch.dotsPerMeterX = image.dotsPerMeterX();
			batch.dotsPerMeterY = image.dotsPerMeterY();
			const QImage defaultResolution(1, 1, QImage::Format_Grayscale8);
			const double dpiX = batch.dotsPerMeterX * 0.0254;
			const double dpiY = batch.dotsPerMeterY * 0.0254;
			const bool isQtDefault = batch.dotsPerMeterX == defaultResolution.dotsPerMeterX()
				&& batch.dotsPerMeterY == defaultResolution.dotsPerMeterY();
			batch.hasPhysicalResolution = !isQtDefault
				&& dpiX >= 10.0 && dpiX <= 2400.0
				&& dpiY >= 10.0 && dpiY <= 2400.0;
			image = image.convertToFormat(QImage::Format_RGBA8888);
			const cv::Mat rgba(image.height(), image.width(), CV_8UC4, image.bits(), image.bytesPerLine());
			cv::cvtColor(rgba, batch.source, cv::COLOR_RGBA2BGRA);
			batch.original = image;
			if (stop->load()) return batch;
			const auto gray = binarizer::preprocess(batch.source, options);
			for (int index = 0; index < int(binarizer::methods.size()); ++index) {
				if (stop->load()) break;
				if (singleMethod >= 0 && index != singleMethod) continue;
				const auto method = binarizer::methods[index];
				auto candidate = options;
				candidate.method = method;
				try {
					batch.previews.push_back(display(binarizer::threshold(gray, candidate)));
					batch.errors.emplace_back();
				} catch (const std::exception& error) {
					batch.previews.emplace_back();
					batch.errors.push_back(QString::fromUtf8(error.what()));
				}
			}
		} catch (const std::exception& error) { batch.error = QString::fromUtf8(error.what()); }
		return batch;
	}));
	emit changed();
}
void Controller::apply(int index) {
	if (active || index < 0 || index >= rows.size() || sourceImage.empty()
		|| selectedLayer < 0 || selectedLayer >= int(artworkLayers.size())) return;
	if (!rows[index].toMap().value("error").toString().isEmpty()) return;
	active = true;
	output = {};
	result.clear();
	message = QStringLiteral("正在以原始分辨率处理 %1…").arg(rows[index].toMap().value("name").toString());
	cancelled = std::make_shared<std::atomic_bool>(false);
	const auto stop = cancelled;
	auto options = settings;
	options.method = binarizer::methods[index];
	const auto source = sourceImage;
	const int targetLayerId = artworkLayers[selectedLayer].id;
	auto* watcher = new QFutureWatcher<Applied>(this);
	connect(watcher, &QFutureWatcher<Applied>::finished, this, [this, watcher, stop, options, targetLayerId] {
		const auto applied = watcher->result();
		watcher->deleteLater();
		active = false;
		if (stop->load()) message = QStringLiteral("已取消");
		else if (!applied.error.isEmpty()) message = applied.error;
		else {
			for (int layerIndex = 0; layerIndex < int(artworkLayers.size()); ++layerIndex) {
				if (artworkLayers[layerIndex].id != targetLayerId) continue;
				selectedLayer = layerIndex;
				artworkLayers[layerIndex].outputImage = applied.image;
				artworkLayers[layerIndex].settings = options;
				break;
			}
			loadSelectedLayer();
			refreshLayerPresentation();
			message = QStringLiteral("已应用到图层“%1”：%2 × %3")
				.arg(artworkLayers[selectedLayer].name).arg(output.width()).arg(output.height());
		}
		emit changed();
	});
	watcher->setFuture(QtConcurrent::run([source, options, stop] {
		Applied applied;
		try {
			if (!stop->load()) applied.image = display(binarizer::process(source, options));
		} catch (const std::exception& error) { applied.error = QString::fromUtf8(error.what()); }
		return applied;
	}));
	emit changed();
}

void Controller::selectLayer(int index) {
	if (active || index < 0 || index >= int(artworkLayers.size()) || index == selectedLayer) return;
	selectedLayer = index;
	rows.clear();
	loadSelectedLayer();
	refreshLayerPresentation();
	message = QStringLiteral("已选择图层：%1").arg(artworkLayers[index].name);
	emit changed();
}

void Controller::setLayerType(int index, const QString& type) {
	if (active || index < 0 || index >= int(artworkLayers.size())) return;
	if (type != QStringLiteral("enig") && type != QStringLiteral("silk")) return;
	artworkLayers[index].type = type;
	refreshLayerPresentation();
	message = QStringLiteral("图层“%1”已设为%2")
		.arg(artworkLayers[index].name, type == QStringLiteral("enig") ? QStringLiteral("沉金") : QStringLiteral("丝印"));
	emit changed();
}

void Controller::setLayerVisible(int index, bool visible) {
	if (active || index < 0 || index >= int(artworkLayers.size())) return;
	artworkLayers[index].visible = visible;
	refreshLayerPresentation();
	emit changed();
}

void Controller::removeLayer(int index) {
	if (active || index < 0 || index >= int(artworkLayers.size())) return;
	const QString name = artworkLayers[index].name;
	artworkLayers.erase(artworkLayers.begin() + index);
	if (artworkLayers.empty()) selectedLayer = -1;
	else if (selectedLayer > index) --selectedLayer;
	else if (selectedLayer >= int(artworkLayers.size())) selectedLayer = int(artworkLayers.size()) - 1;
	rows.clear();
	loadSelectedLayer();
	refreshLayerPresentation();
	message = QStringLiteral("已删除图层：%1").arg(name);
	emit changed();
}

void Controller::moveLayer(int index, int offset) {
	if (active || index < 0 || index >= int(artworkLayers.size())) return;
	const int destination = index + offset;
	if (destination < 0 || destination >= int(artworkLayers.size())) return;
	std::swap(artworkLayers[index], artworkLayers[destination]);
	if (selectedLayer == index) selectedLayer = destination;
	else if (selectedLayer == destination) selectedLayer = index;
	refreshLayerPresentation();
	emit changed();
}

void Controller::setLayerTopLeft(int index, double x, double y) {
	if (active || index < 0 || index >= int(artworkLayers.size())
		|| !std::isfinite(x) || !std::isfinite(y)) return;
	artworkLayers[index].x = std::max(0.0, x);
	artworkLayers[index].y = std::max(0.0, y);
	refreshLayerPresentation();
	emit changed();
}

void Controller::setLayerCenter(int index, double x, double y) {
	if (active || index < 0 || index >= int(artworkLayers.size())
		|| !std::isfinite(x) || !std::isfinite(y)) return;
	const QSize size = layerSize(artworkLayers[index]);
	setLayerTopLeft(index, x - size.width() / 2.0, y - size.height() / 2.0);
}

void Controller::setSolderMaskColor(const QString& color) {
	static const QStringList colors{
		QStringLiteral("green"), QStringLiteral("red"), QStringLiteral("yellow"),
		QStringLiteral("blue"), QStringLiteral("white"), QStringLiteral("black")
	};
	if (!colors.contains(color) || maskColor == color) return;
	maskColor = color;
	refreshLayerPresentation();
	emit changed();
}

void Controller::loadSelectedLayer() {
	if (selectedLayer < 0 || selectedLayer >= int(artworkLayers.size())) {
		sourceImage.release();
		output = {};
		result.clear();
		original.clear();
		return;
	}
	const auto& layer = artworkLayers[selectedLayer];
	sourceImage = layer.sourceImage;
	output = layer.outputImage;
	settings = layer.settings;
	if (!layer.originalImage.isNull()) {
		images->put("selected-original", layer.originalImage);
		original = "image://results/selected-original?revision=" + QString::number(revision);
	} else original.clear();
}

QSize Controller::layerSize(const ArtworkLayer& layer) const {
	return layer.outputImage.isNull() ? layer.originalImage.size() : layer.outputImage.size();
}

QSize Controller::canvasSize() const {
	int width = minimumCanvasWidth;
	int height = minimumCanvasHeight;
	for (const auto& layer : artworkLayers) {
		const QSize size = layerSize(layer);
		width = std::max(width, int(std::ceil(layer.x + size.width())));
		height = std::max(height, int(std::ceil(layer.y + size.height())));
	}
	return {width, height};
}

QImage Controller::materialMask(const QString& type, bool* hasArtwork) const {
	const QSize canvas = canvasSize();
	const int width = canvas.width();
	const int height = canvas.height();
	if (hasArtwork) *hasArtwork = false;
	if (width == 0 || height == 0) return {};
	QImage mask(width, height, QImage::Format_Grayscale8);
	mask.fill(255);
	for (auto iterator = artworkLayers.crbegin(); iterator != artworkLayers.crend(); ++iterator) {
		const auto& layer = *iterator;
		if (!layer.visible || layer.type != type || layer.outputImage.isNull()) continue;
		const QImage source = layer.outputImage.convertToFormat(QImage::Format_Grayscale8);
		const int offsetX = qRound(layer.x);
		const int offsetY = qRound(layer.y);
		for (int y = 0; y < source.height() && y + offsetY < height; ++y) {
			const uchar* sourceLine = source.constScanLine(y);
			uchar* destinationLine = mask.scanLine(y + offsetY) + offsetX;
			for (int x = 0; x < source.width() && x + offsetX < width; ++x) {
				if (sourceLine[x] < 128) {
					destinationLine[x] = 0;
					if (hasArtwork) *hasArtwork = true;
				}
			}
		}
	}
	return mask;
}

QImage Controller::colorSilkImage(bool* hasArtwork) const {
	const QSize canvas = canvasSize();
	if (hasArtwork) *hasArtwork = false;
	if (canvas.isEmpty()) return {};
	QImage image(canvas, QImage::Format_ARGB32_Premultiplied);
	image.fill(Qt::transparent);
	QPainter painter(&image);
	for (auto iterator = artworkLayers.crbegin(); iterator != artworkLayers.crend(); ++iterator) {
		const auto& layer = *iterator;
		if (!layer.visible || layer.type != QStringLiteral("silk") || layer.originalImage.isNull()) continue;
		painter.drawImage(QPointF(layer.x, layer.y), layer.originalImage);
		if (hasArtwork) *hasArtwork = true;
	}
	return image;
}

void Controller::refreshLayerPresentation() {
	++revision;
	layerItems.clear();
	const QSize canvas = canvasSize();
	const int canvasWidth = canvas.width();
	const int canvasHeight = canvas.height();
	for (int index = 0; index < int(artworkLayers.size()); ++index) {
		const auto& layer = artworkLayers[index];
		QString thumbnail;
		const QImage thumbnailImage = layer.type == QStringLiteral("silk")
			? layer.originalImage : layer.outputImage;
		if (!thumbnailImage.isNull()) {
			const QString key = QStringLiteral("layer/%1").arg(layer.id);
			images->put(key, thumbnailImage);
			thumbnail = QStringLiteral("image://results/%1?revision=%2").arg(key).arg(revision);
		}
		layerItems.append(QVariantMap{
			{"name", layer.name}, {"type", layer.type},
			{"typeName", layer.type == QStringLiteral("enig") ? QStringLiteral("沉金") : QStringLiteral("丝印")},
			{"visible", layer.visible}, {"selected", index == selectedLayer},
			{"leftX", layer.x}, {"topY", layer.y},
			{"centerX", layer.x + layerSize(layer).width() / 2.0},
			{"centerY", layer.y + layerSize(layer).height() / 2.0},
			{"width", layerSize(layer).width()}, {"height", layerSize(layer).height()},
			{"thumbnail", thumbnail}, {"source", QUrl::fromLocalFile(layer.sourcePath).toString()}
		});
	}
	if (selectedLayer >= 0 && selectedLayer < int(artworkLayers.size())
		&& !artworkLayers[selectedLayer].outputImage.isNull()) {
		output = artworkLayers[selectedLayer].outputImage;
		images->put("selected", output);
		result = "image://results/selected?revision=" + QString::number(revision);
	} else {
		output = {};
		result.clear();
	}
	if (canvasWidth == 0 || canvasHeight == 0) {
		composite.clear();
		return;
	}
	const double scale = std::min(1.0, 1400.0 / std::max(canvasWidth, canvasHeight));
	const int previewWidth = std::max(1, int(canvasWidth * scale));
	const int previewHeight = std::max(1, int(canvasHeight * scale));
	QImage preview(previewWidth, previewHeight, QImage::Format_RGB32);
	preview.fill(solderMaskPreviewColor(maskColor));
	for (auto iterator = artworkLayers.crbegin(); iterator != artworkLayers.crend(); ++iterator) {
		const auto& layer = *iterator;
		if (!layer.visible) continue;
		if (layer.type == QStringLiteral("silk")) {
			if (layer.originalImage.isNull()) continue;
			QImage source = layer.originalImage;
			if (scale < 1.0)
				source = source.scaled(std::max(1, int(source.width() * scale)),
					std::max(1, int(source.height() * scale)), Qt::IgnoreAspectRatio, Qt::SmoothTransformation);
			QPainter painter(&preview);
			painter.drawImage(QPointF(layer.x * scale, layer.y * scale), source);
			continue;
		}
		if (layer.outputImage.isNull()) continue;
		QImage source = layer.outputImage.convertToFormat(QImage::Format_Grayscale8);
		if (scale < 1.0)
			source = source.scaled(std::max(1, int(source.width() * scale)),
				std::max(1, int(source.height() * scale)), Qt::IgnoreAspectRatio, Qt::FastTransformation);
		const int offsetX = qRound(layer.x * scale);
		const int offsetY = qRound(layer.y * scale);
		const QRgb color = qRgb(222, 181, 72);
		for (int y = 0; y < source.height() && y + offsetY < preview.height(); ++y) {
			const uchar* sourceLine = source.constScanLine(y);
			QRgb* destinationLine = reinterpret_cast<QRgb*>(preview.scanLine(y + offsetY));
			for (int x = 0; x < source.width() && x + offsetX < preview.width(); ++x)
				if (sourceLine[x] < 128) destinationLine[x + offsetX] = color;
		}
	}
	images->put("composite", preview);
	composite = "image://results/composite?revision=" + QString::number(revision);
}
void Controller::cancel() {
	if (pcbProcess && active) {
		pcbCancelled = true;
		message = QStringLiteral("正在取消 PCB 文件生成…");
		pcbProcess->terminate();
		const QPointer<QProcess> process = pcbProcess;
		QTimer::singleShot(1500, this, [process] {
			if (process && process->state() != QProcess::NotRunning) process->kill();
		});
		emit changed();
		return;
	}
	if (cancelled && active) {
		cancelled->store(true);
		message = QStringLiteral("正在结束当前计算…");
		emit changed();
	}
}
void Controller::save(const QUrl& destination) {
	if (active || output.isNull()) return;
	if (!destination.isLocalFile()) return;
	QString path = destination.toLocalFile();
	if (!path.endsWith(".png", Qt::CaseInsensitive)) path += ".png";
	message = output.save(path, "PNG") ? QStringLiteral("已保存：%1").arg(path) : QStringLiteral("保存失败，请检查路径和权限");
	emit changed();
}
void Controller::generatePcb(const QUrl& source, const QString& directory) {
	if (active) return;
	if (!hasExportableLayers()) {
		message = QStringLiteral("没有可用于生成 PCB 文件的可见图层");
		emit changed();
		return;
	}
	QString projectSource = source.toLocalFile();
	if (!QFileInfo::exists(projectSource) && !artworkLayers.empty())
		projectSource = artworkLayers.front().sourcePath;
	const QFileInfo sourceFile(projectSource);
	if (!sourceFile.isFile()) {
		message = QStringLiteral("请先选择输入图片");
		emit changed();
		return;
	}
	const QString root = QStringLiteral(BINARIZER_SOURCE_DIR);
	const QString script = QDir(root).filePath(QStringLiteral("img2enig.py"));
	if (!QFileInfo::exists(script)) {
		message = QStringLiteral("找不到 Python PCB 导出器：%1").arg(script);
		emit changed();
		return;
	}
	QString python = qEnvironmentVariable("IMAGE_BINARIZER_PYTHON");
	if (python.isEmpty()) {
		const QString unixEnvironment = QDir(root).filePath(QStringLiteral(".venv/bin/python"));
		const QString windowsEnvironment = QDir(root).filePath(QStringLiteral(".venv/Scripts/python.exe"));
		if (QFileInfo(unixEnvironment).isExecutable()) python = unixEnvironment;
		else if (QFileInfo(windowsEnvironment).isExecutable()) python = windowsEnvironment;
		else python = QStandardPaths::findExecutable(QStringLiteral("python3"));
	}
	if (python.isEmpty() || !QFileInfo(python).isExecutable()) {
		message = QStringLiteral("找不到可用的 Python 运行环境");
		emit changed();
		return;
	}
	QDir outputDirectory(directory.isEmpty() ? sourceFile.absolutePath() : directory);
	if (!outputDirectory.exists() && !QDir().mkpath(outputDirectory.absolutePath())) {
		message = QStringLiteral("无法创建输出目录：%1").arg(outputDirectory.absolutePath());
		emit changed();
		return;
	}
	pcbTemporaryDirectory = std::make_unique<QTemporaryDir>(
		QDir::temp().filePath(QStringLiteral("image-binarizer-pcb-XXXXXX")));
	if (!pcbTemporaryDirectory->isValid()) {
		message = QStringLiteral("无法创建 PCB 导出临时目录");
		pcbTemporaryDirectory.reset();
		emit changed();
		return;
	}
	bool hasEnig = false;
	bool hasSilk = false;
	const QImage enigMask = materialMask(QStringLiteral("enig"), &hasEnig);
	const QImage silkImage = colorSilkImage(&hasSilk);
	const QString enigPath = QDir(pcbTemporaryDirectory->path()).filePath(QStringLiteral("enig.png"));
	const QString silkPath = QDir(pcbTemporaryDirectory->path()).filePath(QStringLiteral("silk-color.png"));
	if ((hasEnig && !enigMask.save(enigPath, "PNG")) || (hasSilk && !silkImage.save(silkPath, "PNG"))) {
		message = QStringLiteral("无法写入 PCB 导出临时图层");
		pcbTemporaryDirectory.reset();
		emit changed();
		return;
	}
	pcbDestination = outputDirectory.filePath(sourceFile.completeBaseName() + QStringLiteral(".epro2"));
	pcbCancelled = false;
	const QString primaryPath = hasEnig ? enigPath : silkPath;
	QStringList arguments{script, primaryPath, QStringLiteral("-o"), pcbDestination,
		QStringLiteral("--project-name"), sourceFile.completeBaseName(),
		QStringLiteral("--solder-mask-color"), solderMaskExportColor(maskColor)};
	if (!hasEnig) arguments.append({QStringLiteral("--source-type"), QStringLiteral("color-silk")});
	if (hasEnig && hasSilk) arguments.append({QStringLiteral("--color-silk"), silkPath});
	const ArtworkLayer* resolutionLayer = nullptr;
	if (selectedLayer >= 0 && selectedLayer < int(artworkLayers.size())
		&& artworkLayers[selectedLayer].visible && artworkLayers[selectedLayer].hasPhysicalResolution)
		resolutionLayer = &artworkLayers[selectedLayer];
	if (!resolutionLayer) {
		for (const auto& layer : artworkLayers)
			if (layer.visible && (layer.type == QStringLiteral("silk")
				? !layer.originalImage.isNull() : !layer.outputImage.isNull()) && layer.hasPhysicalResolution) {
				resolutionLayer = &layer;
				break;
			}
	}
	const QImage& boardMask = hasEnig ? enigMask : silkImage;
	if (resolutionLayer) {
		const double widthMm = boardMask.width() * 1000.0 / resolutionLayer->dotsPerMeterX;
		const double heightMm = boardMask.height() * 1000.0 / resolutionLayer->dotsPerMeterY;
		arguments.append({QStringLiteral("--width-mm"), QString::number(widthMm, 'f', 6),
			QStringLiteral("--height-mm"), QString::number(heightMm, 'f', 6)});
		pcbDimensionMessage = QStringLiteral("按图片 DPI：图案 %1 × %2 mm，板框 %3 × %4 mm")
			.arg(widthMm, 0, 'f', 2).arg(heightMm, 0, 'f', 2)
			.arg(widthMm + 2.0, 0, 'f', 2).arg(heightMm + 2.0, 0, 'f', 2);
	} else {
		pcbDimensionMessage = QStringLiteral("未检测到可靠 DPI，图案宽度沿用 50 mm，板框四周各加 1 mm");
	}
	auto* process = new QProcess(this);
	pcbProcess = process;
	process->setProgram(python);
	process->setArguments(arguments);
	process->setWorkingDirectory(root);
	connect(process, &QProcess::finished, this,
		[this, process](int exitCode, QProcess::ExitStatus status) {
			finishPcb(process, exitCode, status != QProcess::NormalExit);
		});
	connect(process, &QProcess::errorOccurred, this,
		[this, process](QProcess::ProcessError error) {
			if (error == QProcess::FailedToStart) finishPcb(process, -1, true);
		});
	active = true;
	message = QStringLiteral("正在生成 PCB 文件…（%1）").arg(pcbDimensionMessage);
	process->start();
	emit changed();
}
void Controller::finishPcb(QProcess* process, int exitCode, bool processFailed) {
	if (!pcbProcess || pcbProcess != process) return;
	const QString error = QString::fromUtf8(process->readAllStandardError()).trimmed();
	active = false;
	if (pcbCancelled) message = QStringLiteral("已取消 PCB 文件生成");
	else if (processFailed || exitCode != 0 || !QFileInfo::exists(pcbDestination))
		message = error.isEmpty() ? QStringLiteral("PCB 文件生成失败") : error;
	else message = QStringLiteral("已生成 PCB 文件：%1（%2）").arg(pcbDestination, pcbDimensionMessage);
	pcbProcess.clear();
	process->deleteLater();
	pcbTemporaryDirectory.reset();
	pcbDestination.clear();
	pcbDimensionMessage.clear();
	pcbCancelled = false;
	emit changed();
}
