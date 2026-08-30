"""PyQt desktop interface for the standalone image binarizer."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QDragEnterEvent, QDropEvent, QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from image_binarizer import (
    BinarizationOptions,
    DenoiseMethod,
    ThresholdMethod,
    binarize_image,
    read_image,
    write_image,
)


class FileDropLineEdit(QLineEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if urls:
            self.setText(urls[0].toLocalFile())
            event.acceptProposedAction()


class ValueSlider(QWidget):
    def __init__(
        self,
        minimum: int,
        maximum: int,
        value: int,
        formatter=None,
    ) -> None:
        super().__init__()
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)
        self.label = QLabel()
        self.label.setMinimumWidth(42)
        self._formatter = formatter or str
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.slider)
        layout.addWidget(self.label)
        self.slider.valueChanged.connect(self._update_label)
        self._update_label(value)

    def value(self) -> int:
        return self.slider.value()

    def _update_label(self, value: int) -> None:
        self.label.setText(self._formatter(value))


class MainWindow(QMainWindow):
    PREVIEW_DEBOUNCE_MS = 160

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("图片二值化")
        self.resize(1080, 760)
        self.setAcceptDrops(True)
        self._source_signature: tuple[str, int, int] | None = None
        self._source_image = None
        self._result_image = None
        self._output_is_automatic = True
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self.refresh_preview)
        self._build_ui()
        self._connect_signals()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        paths = QGridLayout()
        self.source_path = FileDropLineEdit()
        self.output_path = FileDropLineEdit()
        source_button = QPushButton("选择图片")
        output_button = QPushButton("选择输出")
        source_button.clicked.connect(self.choose_source)
        output_button.clicked.connect(self.choose_output)
        paths.addWidget(QLabel("输入图片"), 0, 0)
        paths.addWidget(self.source_path, 0, 1)
        paths.addWidget(source_button, 0, 2)
        paths.addWidget(QLabel("输出图片"), 1, 0)
        paths.addWidget(self.output_path, 1, 1)
        paths.addWidget(output_button, 1, 2)
        root.addLayout(paths)

        content = QHBoxLayout()
        root.addLayout(content, 1)
        controls = QWidget()
        controls.setMaximumWidth(390)
        controls_layout = QVBoxLayout(controls)
        content.addWidget(controls)

        threshold_group = QGroupBox("二值化")
        threshold_form = QFormLayout(threshold_group)
        self.threshold_method = QComboBox()
        threshold_items = (
            ("固定阈值", ThresholdMethod.FIXED),
            ("自适应阈值", ThresholdMethod.ADAPTIVE),
            ("Otsu 阈值", ThresholdMethod.OTSU),
            ("Sauvola 阈值", ThresholdMethod.SAUVOLA),
            ("Wolf 阈值", ThresholdMethod.WOLF),
            ("Nick 阈值", ThresholdMethod.NICK),
            ("Bernsen 阈值", ThresholdMethod.BERNSEN),
        )
        for label, method in threshold_items:
            self.threshold_method.addItem(label, method)
        self.threshold_method.setCurrentIndex(1)
        self.threshold = ValueSlider(0, 255, 127)
        self.block_size = QSpinBox()
        self.block_size.setRange(3, 101)
        self.block_size.setSingleStep(2)
        self.block_size.setValue(31)
        threshold_form.addRow("方法", self.threshold_method)
        threshold_form.addRow("阈值", self.threshold)
        threshold_form.addRow("局部窗口", self.block_size)
        controls_layout.addWidget(threshold_group)

        preprocess_group = QGroupBox("预处理")
        preprocess_form = QFormLayout(preprocess_group)
        self.exposure = ValueSlider(-100, 100, 0)
        self.contrast = ValueSlider(-100, 100, 0)
        self.gamma = ValueSlider(10, 300, 100, lambda value: f"{value / 100:.2f}")
        self.smooth = ValueSlider(0, 100, 0)
        self.sharpen = ValueSlider(0, 100, 0)
        preprocess_form.addRow("曝光", self.exposure)
        preprocess_form.addRow("对比度", self.contrast)
        preprocess_form.addRow("伽马", self.gamma)
        preprocess_form.addRow("平滑", self.smooth)
        preprocess_form.addRow("锐化", self.sharpen)
        controls_layout.addWidget(preprocess_group)

        denoise_group = QGroupBox("降噪与增强")
        denoise_form = QFormLayout(denoise_group)
        self.denoise_method = QComboBox()
        for label, method in (
            ("高斯降噪", DenoiseMethod.GAUSSIAN),
            ("中值滤波", DenoiseMethod.MEDIAN),
            ("双边滤波", DenoiseMethod.BILATERAL),
            ("NLMeans 降噪", DenoiseMethod.NL_MEANS),
        ):
            self.denoise_method.addItem(label, method)
        self.denoise = ValueSlider(0, 100, 0)
        self.detail = ValueSlider(0, 100, 0)
        self.edge = ValueSlider(0, 100, 0)
        self.local_contrast = ValueSlider(0, 100, 0)
        self.equalize = QCheckBox("直方图均衡化")
        self.clahe = QCheckBox("CLAHE")
        check_row = QWidget()
        check_layout = QHBoxLayout(check_row)
        check_layout.setContentsMargins(0, 0, 0, 0)
        check_layout.addWidget(self.equalize)
        check_layout.addWidget(self.clahe)
        denoise_form.addRow("方法", self.denoise_method)
        denoise_form.addRow("强度", self.denoise)
        denoise_form.addRow("均衡化", check_row)
        denoise_form.addRow("细节", self.detail)
        denoise_form.addRow("边缘", self.edge)
        denoise_form.addRow("局部对比度", self.local_contrast)
        controls_layout.addWidget(denoise_group)

        direction_group = QGroupBox("输出")
        direction_layout = QHBoxLayout(direction_group)
        self.invert = QCheckBox("反相")
        self.flip_horizontal = QCheckBox("水平翻转")
        self.flip_vertical = QCheckBox("垂直翻转")
        direction_layout.addWidget(self.invert)
        direction_layout.addWidget(self.flip_horizontal)
        direction_layout.addWidget(self.flip_vertical)
        controls_layout.addWidget(direction_group)
        controls_layout.addStretch()

        self.preview_label = QLabel("请选择或拖入图片")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(600, 500)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.preview_label)
        content.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        self.refresh_button = QPushButton("立即预览")
        self.save_button = QPushButton("保存黑白图片")
        self.refresh_button.clicked.connect(self.refresh_preview)
        self.save_button.clicked.connect(self.save_result)
        buttons.addStretch()
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.save_button)
        root.addLayout(buttons)
        self.statusBar().showMessage("就绪")

    def _connect_signals(self) -> None:
        self.source_path.textChanged.connect(self._source_changed)
        self.output_path.textEdited.connect(self._mark_output_manual)
        self.threshold_method.currentIndexChanged.connect(self.schedule_preview)
        self.block_size.valueChanged.connect(self.schedule_preview)
        self.denoise_method.currentIndexChanged.connect(self.schedule_preview)
        for control in (
            self.threshold,
            self.exposure,
            self.contrast,
            self.gamma,
            self.smooth,
            self.sharpen,
            self.denoise,
            self.detail,
            self.edge,
            self.local_contrast,
        ):
            control.slider.valueChanged.connect(self.schedule_preview)
        for checkbox in (
            self.equalize,
            self.clahe,
            self.invert,
            self.flip_horizontal,
            self.flip_vertical,
        ):
            checkbox.stateChanged.connect(self.schedule_preview)
        self.equalize.toggled.connect(self._equalize_toggled)
        self.clahe.toggled.connect(self._clahe_toggled)

    def options(self) -> BinarizationOptions:
        block_size = self.block_size.value()
        if block_size % 2 == 0:
            block_size += 1
        return BinarizationOptions(
            threshold_method=self.threshold_method.currentData(),
            threshold=self.threshold.value(),
            block_size=block_size,
            denoise_method=self.denoise_method.currentData(),
            denoise_strength=self.denoise.value(),
            exposure=self.exposure.value(),
            contrast=self.contrast.value(),
            gamma=self.gamma.value() / 100.0,
            smooth=self.smooth.value(),
            sharpen=self.sharpen.value(),
            equalize=self.equalize.isChecked(),
            clahe=self.clahe.isChecked(),
            detail_enhance=self.detail.value(),
            edge_enhance=self.edge.value(),
            local_contrast=self.local_contrast.value(),
            invert=self.invert.isChecked(),
            flip_horizontal=self.flip_horizontal.isChecked(),
            flip_vertical=self.flip_vertical.isChecked(),
        )

    def choose_source(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "选择图片",
            "",
            "图片 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;所有文件 (*)",
        )
        if filename:
            self.source_path.setText(filename)

    def choose_output(self) -> None:
        suggested = self.output_path.text() or "output.binary.png"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "保存黑白图片",
            suggested,
            "PNG 图片 (*.png);;BMP 图片 (*.bmp);;TIFF 图片 (*.tiff)",
        )
        if filename:
            self._output_is_automatic = False
            self.output_path.setText(filename)

    def _source_changed(self, text: str) -> None:
        self._source_signature = None
        self._source_image = None
        source = Path(text.strip())
        if source.is_file() and self._output_is_automatic:
            self.output_path.setText(str(source.with_name(f"{source.stem}.binary.png")))
        self.schedule_preview()

    def schedule_preview(self, *_args) -> None:
        self._result_image = None
        self._preview_timer.start(self.PREVIEW_DEBOUNCE_MS)

    def _mark_output_manual(self, _text: str) -> None:
        self._output_is_automatic = False

    def _equalize_toggled(self, checked: bool) -> None:
        if checked:
            self.clahe.setChecked(False)

    def _clahe_toggled(self, checked: bool) -> None:
        if checked:
            self.equalize.setChecked(False)

    def _load_source(self):
        source = Path(self.source_path.text().strip())
        stat = source.stat()
        signature = (str(source.resolve()), stat.st_mtime_ns, stat.st_size)
        if signature != self._source_signature:
            self._source_image = read_image(source)
            self._source_signature = signature
        return self._source_image

    def refresh_preview(self) -> None:
        if not self.source_path.text().strip():
            return
        try:
            self._result_image = binarize_image(self._load_source(), self.options())
            self._show_image(self._result_image)
            height, width = self._result_image.shape
            self.statusBar().showMessage(f"预览完成：{width} × {height}，仅包含黑白像素")
        except (FileNotFoundError, OSError, ValueError) as error:
            self._result_image = None
            self.statusBar().showMessage(str(error))

    def _show_image(self, image) -> None:
        height, width = image.shape
        qimage = QImage(
            image.data,
            width,
            height,
            image.strides[0],
            QImage.Format_Grayscale8,
        ).copy()
        pixmap = QPixmap.fromImage(qimage)
        self.preview_label.setPixmap(
            pixmap.scaled(
                self.preview_label.size(),
                Qt.KeepAspectRatio,
                Qt.FastTransformation,
            )
        )

    def save_result(self) -> None:
        try:
            if self._result_image is None:
                self.refresh_preview()
            if self._result_image is None:
                raise ValueError("没有可保存的处理结果")
            if not self.output_path.text().strip():
                self.choose_output()
            if not self.output_path.text().strip():
                return
            destination = write_image(self.output_path.text().strip(), self._result_image)
            self.statusBar().showMessage(f"已保存：{destination}")
            QMessageBox.information(self, "保存完成", str(destination))
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "保存失败", str(error))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if urls:
            self.source_path.setText(urls[0].toLocalFile())
            event.acceptProposedAction()


def main() -> int:
    application = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return application.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
