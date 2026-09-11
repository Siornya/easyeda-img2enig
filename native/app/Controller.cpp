#include "Controller.hpp"
#include <QDir>
#include <QFileInfo>
#include <QFutureWatcher>
#include <QImageReader>
#include <QMutexLocker>
#include <QtConcurrent/QtConcurrentRun>
#include <cmath>
#include <stdexcept>
#include <opencv2/imgproc.hpp>
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
	std::vector<QImage> previews;
	std::vector<QString> errors;
	QString error;
};
struct Applied {
	QImage image;
	QString error;
};
Controller::Controller(ImageStore* images, QObject* parent) : QObject(parent), images(images) {}
Controller::~Controller() {
	if (cancelled) cancelled->store(true);
}
void Controller::invalidate() {
	if (active) return;
	rows.clear();
	result.clear();
	output = {};
	message = QStringLiteral("设置已更新，请点击 Try All 重新比较");
	emit changed();
}
QString Controller::localPath(const QUrl& url) const { return url.toLocalFile(); }
QUrl Controller::fileUrl(const QString& path) const { return QUrl::fromLocalFile(path); }
QString Controller::sourceDirectory(const QUrl& source) const { return QFileInfo(source.toLocalFile()).absolutePath(); }
QUrl Controller::outputFile(const QUrl& source, const QString& directory) const {
	const QFileInfo file(source.toLocalFile());
	return QUrl::fromLocalFile(QDir(directory.isEmpty() ? file.absolutePath() : directory)
		.filePath(file.completeBaseName() + ".binary.png"));
}
void Controller::compare(const QUrl& url, const QVariantMap& parameters) { run(url, parameters, -1); }
void Controller::preview(const QUrl& url, const QVariantMap& parameters, int method) {
	if (method < 0 || method >= int(binarizer::methods.size())) return;
	run(url, parameters, method);
}
void Controller::run(const QUrl& url, const QVariantMap& p, int singleMethod) {
	if (active) return;
	if (!url.isLocalFile()) {
		message = QStringLiteral("请先选择本地图片");
		emit changed();
		return;
	}
	rows.clear();
	binarizer::Options requested;
	requested.threshold = p.value("threshold", 127).toInt();
	requested.blockSize = p.value("blockSize", 31).toInt();
	requested.adaptiveC = p.value("adaptiveC", 5).toDouble();
	requested.localK = p.value("localK", 0.2).toDouble();
	requested.exposure = p.value("exposure", 0).toInt();
	requested.contrast = p.value("contrast", 0).toInt();
	requested.gamma = p.value("gamma", 1).toDouble();
	requested.denoiseMethod = p.value("denoiseMethod", 0).toInt();
	requested.denoiseStrength = p.value("denoiseStrength", 0).toInt();
	requested.smooth = p.value("smooth", 0).toInt();
	requested.sharpen = p.value("sharpen", 0).toInt();
	requested.detail = p.value("detail", 0).toInt();
	requested.edge = p.value("edge", 0).toInt();
	requested.localContrast = p.value("localContrast", 0).toInt();
	requested.equalize = p.value("equalize", false).toBool();
	requested.clahe = p.value("clahe", false).toBool();
	requested.invert = p.value("invert", false).toBool();
	requested.flipHorizontal = p.value("flipHorizontal", false).toBool();
	requested.flipVertical = p.value("flipVertical", false).toBool();
	settings = requested;
	active = true;
	message = singleMethod < 0 ? QStringLiteral("正在生成 7 种方案…") : QStringLiteral("正在更新预览…");
	cancelled = std::make_shared<std::atomic_bool>(false);
	const auto stop = cancelled;
	auto options = requested;
	options.maxDimension = singleMethod < 0 ? 640 : 0;
	auto* watcher = new QFutureWatcher<Comparison>(this);
	connect(watcher, &QFutureWatcher<Comparison>::finished, this,
		[this, watcher, stop, singleMethod, requested] {
			const auto batch = watcher->result();
			watcher->deleteLater();
			active = false;
			if (stop->load()) message = QStringLiteral("已取消");
			else if (!batch.error.isEmpty()) message = batch.error;
			else {
				sourceImage = batch.source;
				settings = requested;
				++revision;
				images->put("original", batch.original);
				original = "image://results/original?revision=" + QString::number(revision);
				if (singleMethod >= 0) {
					if (!batch.errors.front().isEmpty()) message = batch.errors.front();
					else {
						output = batch.previews.front();
						images->put("selected", output);
						result = "image://results/selected?revision=" + QString::number(revision);
						message = QStringLiteral("处理完成：%1 × %2").arg(output.width()).arg(output.height());
					}
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
			}
			emit changed();
		});
	watcher->setFuture(QtConcurrent::run([path = url.toLocalFile(), options, stop, singleMethod] {
		Comparison batch;
		try {
			QImageReader reader(path);
			QImage image = reader.read();
			if (image.isNull()) throw std::runtime_error(reader.errorString().toStdString());
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
	if (active || index < 0 || index >= rows.size() || sourceImage.empty()) return;
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
	auto* watcher = new QFutureWatcher<Applied>(this);
	connect(watcher, &QFutureWatcher<Applied>::finished, this, [this, watcher, stop, options] {
		const auto applied = watcher->result();
		watcher->deleteLater();
		active = false;
		if (stop->load()) message = QStringLiteral("已取消");
		else if (!applied.error.isEmpty()) message = applied.error;
		else {
			output = applied.image;
			settings = options;
			++revision;
			images->put("selected", output);
			result = "image://results/selected?revision=" + QString::number(revision);
			message = QStringLiteral("已应用：%1 × %2").arg(output.width()).arg(output.height());
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
void Controller::cancel() {
	if (cancelled && active) {
		cancelled->store(true);
		message = QStringLiteral("正在结束当前计算…");
		emit changed();
	}
}
void Controller::save(const QUrl& destination) {
	if (active || output.isNull() || !destination.isLocalFile()) return;
	QString path = destination.toLocalFile();
	if (!path.endsWith(".png", Qt::CaseInsensitive)) path += ".png";
	message = output.save(path, "PNG") ? QStringLiteral("已保存：%1").arg(path) : QStringLiteral("保存失败，请检查路径和权限");
	emit changed();
}
