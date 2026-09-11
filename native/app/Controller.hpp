#pragma once
#include "Binarizer.hpp"
#include <QObject>
#include <QQuickImageProvider>
#include <QMutex>
#include <QHash>
#include <QVariantList>
#include <QUrl>
#include <atomic>
#include <memory>

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
	Q_PROPERTY(QString resultUrl READ resultUrl NOTIFY changed)
	Q_PROPERTY(QString originalUrl READ originalUrl NOTIFY changed)
public:
	explicit Controller(ImageStore* images, QObject* parent = nullptr);
	~Controller() override;
	bool busy() const { return active; }
	QString status() const { return message; }
	QVariantList candidates() const { return rows; }
	QString resultUrl() const { return result; }
	QString originalUrl() const { return original; }
	Q_INVOKABLE void compare(const QUrl& source, const QVariantMap& parameters);
	Q_INVOKABLE void preview(const QUrl& source, const QVariantMap& parameters, int method);
	Q_INVOKABLE QString localPath(const QUrl& url) const;
	Q_INVOKABLE QUrl fileUrl(const QString& path) const;
	Q_INVOKABLE QUrl outputFile(const QUrl& source, const QString& directory) const;
	Q_INVOKABLE QString sourceDirectory(const QUrl& source) const;
	Q_INVOKABLE void apply(int index);
	Q_INVOKABLE void cancel();
	Q_INVOKABLE void invalidate();
	Q_INVOKABLE void save(const QUrl& destination);
signals:
	void changed();
private:
	void run(const QUrl& source, const QVariantMap& parameters, int singleMethod);
	ImageStore* images;
	bool active = false;
	QString message = QStringLiteral("请选择或拖入图片");
	QVariantList rows;
	QString result, original;
	cv::Mat sourceImage;
	QImage output;
	binarizer::Options settings;
	std::shared_ptr<std::atomic_bool> cancelled;
	int revision = 0;
};
