#include "Controller.hpp"
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QThreadPool>
#include <QTimer>
#include <QQuickWindow>
#include <QQuickStyle>

int main(int argc, char* argv[]) {
	QGuiApplication app(argc, argv);
	QGuiApplication::setApplicationName("Image Binarizer");
	QQuickStyle::setStyle("Fusion");
	auto* images = new ImageStore;
	Controller controller(images);
	QQmlApplicationEngine engine;
	engine.addImageProvider("results", images);
	engine.rootContext()->setContextProperty("controller", &controller);
	engine.loadFromModule("Binarizer", "Main");
	if (engine.rootObjects().isEmpty()) return 1;
	const auto arguments = app.arguments();
	const int comparisonSmoke = arguments.indexOf("--smoke-comparison-screenshot");
	const int input = arguments.indexOf("--input");
	if (input >= 0 && input + 1 < arguments.size()) {
		const auto source = QUrl::fromLocalFile(arguments[input + 1]);
		engine.rootObjects().first()->setProperty("sourceFile", source);
		if (comparisonSmoke < 0)
			QTimer::singleShot(0, &controller, [&controller, source] { controller.compare(source, {}); });
		else
			QTimer::singleShot(0, engine.rootObjects().first(), [root = engine.rootObjects().first()] {
				QMetaObject::invokeMethod(root, "showComparison");
			});
	}
	// Test the actual packaged QML scene as well as the C++ controller.
	const int smoke = arguments.indexOf("--smoke-screenshot");
	if (smoke >= 0 && smoke + 1 < arguments.size()) {
		QTimer::singleShot(15000, &app, [&app] { app.exit(2); });
		QObject::connect(&controller, &Controller::changed, &app, [&] {
			if (controller.busy() || controller.candidates().size() != 7) return;
			if (controller.resultUrl().isEmpty()) controller.apply(2);
			else QTimer::singleShot(250, &app, [&] {
				auto* window = qobject_cast<QQuickWindow*>(engine.rootObjects().first());
				const bool saved = window && window->grabWindow().save(arguments[smoke + 1]);
				app.exit(saved ? 0 : 3);
			});
		});
	}
	if (comparisonSmoke >= 0 && comparisonSmoke + 1 < arguments.size()) {
		QTimer::singleShot(15000, &app, [&app] { app.exit(2); });
		QObject::connect(&controller, &Controller::changed, &app, [&] {
			if (controller.busy() || controller.candidates().size() != 7) return;
			QTimer::singleShot(250, &app, [&] {
				auto* window = qobject_cast<QQuickWindow*>(engine.rootObjects().first());
				const bool saved = window && window->grabWindow().save(arguments[comparisonSmoke + 1]);
				app.exit(saved ? 0 : 3);
			});
		});
	}
	const int code = app.exec();
	controller.cancel();
	QThreadPool::globalInstance()->waitForDone();
	return code;
}
