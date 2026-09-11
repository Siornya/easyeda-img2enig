#pragma once
#include "Binarizer.hpp"
#include <QObject>
#include <QQuickImageProvider>
#include <QMutex>
#include <QHash>
#include <QPointer>
#include <QVariantList>
#include <QUrl>
#include <atomic>
#include <memory>
#include <vector>

class QProcess;
class QTemporaryDir;

class ImageStore : public QQuickImageProvider {
public:
	ImageStore() : QQuickImageProvider(QQuickImageProvider::Image) {}
	QImage requestImage(const QString& id, QSize* size, const QSize& requested) override;
	void put(const QString& id, const QImage& image);
	void clear();
private:
	QMutex mutex;
	QHash<QString, QImage> images;
};

class Controller : public QObject {
	Q_OBJECT
	Q_PROPERTY(bool busy READ busy NOTIFY changed)
	Q_PROPERTY(QString status READ status NOTIFY changed)
	Q_PROPERTY(QVariantList candidates READ candidates NOTIFY changed)
	Q_PROPERTY(QVariantList layers READ layerRows NOTIFY changed)
	Q_PROPERTY(int selectedLayer READ selectedLayerIndex NOTIFY changed)
	Q_PROPERTY(QString resultUrl READ resultUrl NOTIFY changed)
	Q_PROPERTY(QString originalUrl READ originalUrl NOTIFY changed)
	Q_PROPERTY(QString compositeUrl READ compositeUrl NOTIFY changed)
	Q_PROPERTY(QString selectedSourceUrl READ selectedSourceUrl NOTIFY changed)
	Q_PROPERTY(QVariantMap selectedParameters READ selectedParameters NOTIFY changed)
	Q_PROPERTY(bool hasExportableLayers READ hasExportableLayers NOTIFY changed)
	Q_PROPERTY(int canvasWidth READ canvasWidth NOTIFY changed)
	Q_PROPERTY(int canvasHeight READ canvasHeight NOTIFY changed)
	Q_PROPERTY(QString solderMaskColor READ solderMaskColor NOTIFY changed)
public:
	explicit Controller(ImageStore* images, QObject* parent = nullptr);
	~Controller() override;
	bool busy() const { return active; }
	QString status() const { return message; }
	QVariantList candidates() const { return rows; }
	QVariantList layerRows() const { return layerItems; }
	int selectedLayerIndex() const { return selectedLayer; }
	QString resultUrl() const { return result; }
	QString originalUrl() const { return original; }
	QString compositeUrl() const { return composite; }
	QString selectedSourceUrl() const;
	QVariantMap selectedParameters() const;
	bool hasExportableLayers() const;
	int canvasWidth() const;
	int canvasHeight() const;
	QString solderMaskColor() const { return maskColor; }
	Q_INVOKABLE void compare(const QUrl& source, const QVariantMap& parameters);
	Q_INVOKABLE void preview(const QUrl& source, const QVariantMap& parameters, int method);
	Q_INVOKABLE QString localPath(const QUrl& url) const;
	Q_INVOKABLE QUrl fileUrl(const QString& path) const;
	Q_INVOKABLE QUrl outputFile(const QUrl& source, const QString& directory) const;
	Q_INVOKABLE QString sourceDirectory(const QUrl& source) const;
	Q_INVOKABLE void selectLayer(int index);
	Q_INVOKABLE void setLayerType(int index, const QString& type);
	Q_INVOKABLE void setLayerVisible(int index, bool visible);
	Q_INVOKABLE void removeLayer(int index);
	Q_INVOKABLE void moveLayer(int index, int offset);
	Q_INVOKABLE void setLayerTopLeft(int index, double x, double y);
	Q_INVOKABLE void setLayerCenter(int index, double x, double y);
	Q_INVOKABLE void setSolderMaskColor(const QString& color);
	Q_INVOKABLE void apply(int index);
	Q_INVOKABLE void cancel();
	Q_INVOKABLE void invalidate();
	Q_INVOKABLE void save(const QUrl& destination);
	Q_INVOKABLE void generatePcb(const QUrl& source, const QString& directory);
signals:
	void changed();
private:
	struct ArtworkLayer {
		int id = 0;
		QString name;
		QString sourcePath;
		QString type = QStringLiteral("enig");
		bool visible = true;
		double x = 0;
		double y = 0;
		cv::Mat sourceImage;
		QImage originalImage;
		QImage outputImage;
		binarizer::Options settings;
		int dotsPerMeterX = 0;
		int dotsPerMeterY = 0;
		bool hasPhysicalResolution = false;
	};
	void run(const QUrl& source, const QVariantMap& parameters, int singleMethod);
	void finishPcb(QProcess* process, int exitCode, bool processFailed);
	void loadSelectedLayer();
	void refreshLayerPresentation();
	QSize layerSize(const ArtworkLayer& layer) const;
	QSize canvasSize() const;
	ImageStore* images;
	bool active = false;
	QString message = QStringLiteral("请选择或拖入图片");
	QVariantList rows;
	QVariantList layerItems;
	QString result, original, composite;
	std::vector<ArtworkLayer> artworkLayers;
	int selectedLayer = -1;
	int nextLayerId = 1;
	int minimumCanvasWidth = 0;
	int minimumCanvasHeight = 0;
	QString maskColor = QStringLiteral("green");
	cv::Mat sourceImage;
	QImage output;
	binarizer::Options settings;
	std::shared_ptr<std::atomic_bool> cancelled;
	QPointer<QProcess> pcbProcess;
	std::unique_ptr<QTemporaryDir> pcbTemporaryDirectory;
	QString pcbDestination;
	QString pcbDimensionMessage;
	bool pcbCancelled = false;
	int revision = 0;
};
