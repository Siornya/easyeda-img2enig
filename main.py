"""PyQt desktop interface for the standalone image binarizer."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
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
    QStatusBar,
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
from img2enig import convert as convert_to_epro2


class FileDropLineEdit(QLineEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, a0: QDragEnterEvent | None) -> None:
        if a0 is None:
            return
        mime_data = a0.mimeData()
        if mime_data is not None and mime_data.hasUrls():
            a0.acceptProposedAction()

    def dropEvent(self, a0: QDropEvent | None) -> None:
        if a0 is None:
            return
        mime_data = a0.mimeData()
        if mime_data is None:
            return
        urls = mime_data.urls()
        if urls:
            self.setText(urls[0].toLocalFile())
            a0.acceptProposedAction()


class ValueSlider(QWidget):
    def __init__(
        self,
        minimum: int,
        maximum: int,
        value: int,
        formatter=None,
    ) -> None:
        super().__init__()
        self.slider = QSlider(Qt.Orientation.Horizontal)
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
        self._showing_original = False
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
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
        output_button = QPushButton("选择目录")
        source_button.clicked.connect(self.choose_source)
        output_button.clicked.connect(self.choose_output)
        paths.addWidget(QLabel("输入图片"), 0, 0)
        paths.addWidget(self.source_path, 0, 1)
        paths.addWidget(source_button, 0, 2)
        paths.addWidget(QLabel("输出路径"), 1, 0)
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
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(600, 500)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.preview_label)
        content.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        self.compare_button = QPushButton("查看原图")
        self.save_button = QPushButton("保存黑白图片")
        self.pcb_button = QPushButton("生成PCB文件")
        self.compare_button.clicked.connect(self.toggle_original)
        self.save_button.clicked.connect(self.save_result)
        self.pcb_button.clicked.connect(self.generate_pcb)
        buttons.addStretch()
        buttons.addWidget(self.compare_button)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.pcb_button)
        root.addLayout(buttons)
        self.status_bar.showMessage("就绪")

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
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择输出路径",
            self.output_path.text().strip(),
        )
        if directory:
            self._output_is_automatic = False
            self.output_path.setText(directory)

    def _source_changed(self, text: str) -> None:
        self._source_signature = None
        self._source_image = None
        source = Path(text.strip())
        if source.is_file() and self._output_is_automatic:
            self.output_path.setText(str(source.parent))
        self.schedule_preview()

    def schedule_preview(self, *_args) -> None:
        self._result_image = None
        self._preview_timer.start(self.PREVIEW_DEBOUNCE_MS)

    def _mark_output_manual(self, _text: str) -> None:
        self._output_is_automatic = False

    def _output_directory(self) -> Path:
        path_text = self.output_path.text().strip()
        if not path_text:
            source = Path(self.source_path.text().strip())
            if not source.is_file():
                raise ValueError("请先选择输入图片")
            output_directory = source.parent
            self.output_path.setText(str(output_directory))
        else:
            output_directory = Path(path_text)
        if output_directory.exists() and not output_directory.is_dir():
            raise ValueError("输出路径必须是目录")
        return output_directory

    def _output_file(self, suffix: str) -> Path:
        source = Path(self.source_path.text().strip())
        if not source.is_file():
            raise ValueError("请先选择输入图片")
        return self._output_directory() / f"{source.stem}{suffix}"

    def _equalize_toggled(self, checked: bool) -> None:
        if checked:
            self.clahe.setChecked(False)

    def _clahe_toggled(self, checked: bool) -> None:
        if checked:
            self.equalize.setChecked(False)

    def _load_source(self) -> np.ndarray:
        source = Path(self.source_path.text().strip())
        stat = source.stat()
        signature = (str(source.resolve()), stat.st_mtime_ns, stat.st_size)
        if signature != self._source_signature:
            self._source_image = read_image(source)
            self._source_signature = signature
        if self._source_image is None:
            raise ValueError("无法加载源图片")
        return self._source_image

    def refresh_preview(self) -> None:
        if not self.source_path.text().strip():
            return
        try:
            source_image = self._load_source()
            self._result_image = binarize_image(source_image, self.options())
            height, width = self._result_image.shape
            if self._showing_original:
                self._show_image(source_image)
                self.status_bar.showMessage(
                    f"正在显示原图；处理结果已更新：{width} × {height}"
                )
            else:
                self._show_image(self._result_image)
                self.status_bar.showMessage(
                    f"预览完成：{width} × {height}，仅包含黑白像素"
                )
        except (FileNotFoundError, OSError, ValueError) as error:
            self._result_image = None
            self.status_bar.showMessage(str(error))

    def _show_image(self, image: np.ndarray) -> None:
        if image.ndim == 2:
            display = image
            image_format = QImage.Format_Grayscale8
            bytes_per_pixel = 1
        elif image.ndim == 3 and image.shape[2] == 3:
            display = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            image_format = QImage.Format_RGB888
            bytes_per_pixel = 3
        elif image.ndim == 3 and image.shape[2] == 4:
            color = image[:, :, :3].astype("float32")
            alpha = image[:, :, 3:4].astype("float32") / 255.0
            composited = (color * alpha + 255.0 * (1.0 - alpha)).clip(0, 255)
            display = cv2.cvtColor(composited.astype("uint8"), cv2.COLOR_BGR2RGB)
            image_format = QImage.Format_RGB888
            bytes_per_pixel = 3
        else:
            raise ValueError("无法预览该图片的通道格式")
        height, width = display.shape[:2]
        image_bytes = display.tobytes(order="C")
        qimage = QImage(
            image_bytes,
            width,
            height,
            width * bytes_per_pixel,
            image_format,
        ).copy()
        pixmap = QPixmap.fromImage(qimage)
        self.preview_label.setPixmap(
            pixmap.scaled(
                self.preview_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        )

    def toggle_original(self) -> None:
        if not self.source_path.text().strip():
            self.status_bar.showMessage("请先选择图片")
            return
        try:
            self._showing_original = not self._showing_original
            if self._showing_original:
                self._show_image(self._load_source())
                self.compare_button.setText("查看处理结果")
                self.status_bar.showMessage("正在显示原图")
            else:
                if self._result_image is None:
                    self.refresh_preview()
                else:
                    self._show_image(self._result_image)
                    self.status_bar.showMessage("正在显示处理结果")
                self.compare_button.setText("查看原图")
        except (FileNotFoundError, OSError, ValueError) as error:
            self._showing_original = False
            self.compare_button.setText("查看原图")
            self.status_bar.showMessage(str(error))

    def save_result(self) -> None:
        try:
            if self._result_image is None:
                self.refresh_preview()
            if self._result_image is None:
                raise ValueError("没有可保存的处理结果")
            destination = write_image(
                self._output_file(".binary.png"),
                self._result_image,
            )
            self.status_bar.showMessage(f"已保存：{destination}")
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "保存失败", str(error))

    def generate_pcb(self) -> None:
        try:
            self.status_bar.showMessage("正在生成PCB文件…")
            result = self.generate_pcb_to(self._output_file(".epro2"))
            output = result["output"]
            self.status_bar.showMessage(f"已生成PCB文件：{output}")
        except (FileNotFoundError, OSError, ValueError) as error:
            QMessageBox.critical(self, "PCB文件生成失败", str(error))

    def generate_pcb_to(self, destination: str | Path) -> dict:
        if self._result_image is None:
            self.refresh_preview()
        if self._result_image is None:
            raise ValueError("没有可用的二值化结果")
        source = Path(self.source_path.text().strip())
        with tempfile.TemporaryDirectory(prefix="img2enig-") as directory:
            binary_path = Path(directory) / "binary.png"
            write_image(binary_path, self._result_image)
            return convert_to_epro2(
                source=binary_path,
                output=destination,
                width_mm=50.0,
                height_mm=None,
                side="top",
                margin_mm=1.0,
                include_outline=True,
                project_name=source.stem or "img2enig",
            )

    def dragEnterEvent(self, a0: QDragEnterEvent | None) -> None:
        if a0 is None:
            return
        mime_data = a0.mimeData()
        if mime_data is not None and mime_data.hasUrls():
            a0.acceptProposedAction()

    def dropEvent(self, a0: QDropEvent | None) -> None:
        if a0 is None:
            return
        mime_data = a0.mimeData()
        if mime_data is None:
            return
        urls = mime_data.urls()
        if urls:
            self.source_path.setText(urls[0].toLocalFile())
            a0.acceptProposedAction()


def main() -> int:
    application = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return application.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
