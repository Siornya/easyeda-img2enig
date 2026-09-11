import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

ApplicationWindow {
	id: window
	visible: true
	width: 1280
	height: 800
	minimumWidth: 1080
	minimumHeight: 740
	title: "图片二值化"
	font.pixelSize: 15
	property url sourceFile
	property bool automaticOutput: true
	property bool showingOriginal: false
	property bool pendingPreview: false
	property string displayedResult: ""

	function parameters() {
		return { threshold: threshold.value, blockSize: block.value,
			adaptiveC: adaptiveC.value, localK: localK.value / 100,
			exposure: exposure.value, contrast: contrast.value, gamma: gamma.value / 100,
			denoiseMethod: denoise.currentIndex, denoiseStrength: strength.value,
			smooth: smooth.value, sharpen: sharpen.value, detail: detail.value,
			edge: edge.value, localContrast: localContrast.value,
			equalize: equalize.checked, clahe: clahe.checked, invert: invert.checked,
			flipHorizontal: horizontal.checked, flipVertical: vertical.checked }
	}
	function requestPreview() {
		if (!sourceFile.toString().length) return
		pendingPreview = true
		if (controller.busy) controller.cancel()
		previewTimer.restart()
	}
	function showComparison() {
		previewTimer.stop()
		pendingPreview = false
		comparison.applied = false
		comparison.open()
		controller.compare(sourceFile, parameters())
	}
	onSourceFileChanged: {
		sourcePath.text = controller.localPath(sourceFile)
		if (automaticOutput) outputPath.text = controller.sourceDirectory(sourceFile)
		displayedResult = ""
		requestPreview()
	}
	Timer {
		id: previewTimer
		interval: 160
		onTriggered: {
			if (!controller.busy && window.pendingPreview) {
				window.pendingPreview = false
				controller.preview(window.sourceFile, window.parameters(), method.currentIndex)
			}
		}
	}
	Connections {
		target: controller
		function onChanged() {
			if (window.pendingPreview && !controller.busy) previewTimer.restart()
			if (!window.pendingPreview) window.displayedResult = controller.resultUrl
		}
	}
	component ValueSlider: RowLayout {
		property alias value: slider.value
		property alias from: slider.from
		property alias to: slider.to
		property bool decimal: false
		Layout.fillWidth: true
		spacing: 6
		Slider {
			id: slider
			from: 0
			to: 100
			stepSize: 1
			implicitHeight: 26
			Layout.fillWidth: true
			onMoved: window.requestPreview()
			background: Rectangle {
				x: slider.leftPadding
				y: slider.topPadding + slider.availableHeight / 2 - height / 2
				width: slider.availableWidth
				height: 4
				radius: 2
				color: "#cfd4da"
				Rectangle {
					width: slider.visualPosition * parent.width
					height: parent.height
					radius: parent.radius
					color: "#2f80ed"
				}
			}
			handle: Rectangle {
				x: slider.leftPadding + slider.visualPosition * (slider.availableWidth - width)
				y: slider.topPadding + slider.availableHeight / 2 - height / 2
				implicitWidth: 16
				implicitHeight: 16
				radius: 8
				color: slider.pressed ? "#eaf3ff" : "white"
				border.width: 1
				border.color: slider.hovered ? "#2f80ed" : "#9299a2"
			}
		}
		Label {
			text: parent.decimal ? (slider.value / 100).toFixed(2) : Math.round(slider.value)
			Layout.preferredWidth: 40
		}
	}
	component ControlsGroup: GroupBox {
		id: groupControl
		Layout.fillWidth: true
		leftPadding: 12
		rightPadding: 12
		bottomPadding: 7
		topPadding: 31
		label: Label {
			x: 11
			y: 0
			text: groupControl.title
			font.bold: true
			color: "#292d33"
		}
		background: Rectangle {
			y: 22
			width: groupControl.width
			height: groupControl.height - y
			radius: 8
			color: "#f5f6f8"
			border.width: 1
			border.color: "#c5c9ce"
		}
	}
	component RoundedFrame: Frame {
		padding: 9
		background: Rectangle {
			radius: 9
			color: "#f5f6f8"
			border.width: 1
			border.color: "#c5c9ce"
		}
	}
	component AppButton: Button {
		id: buttonControl
		property bool accent: false
		hoverEnabled: true
		implicitHeight: 30
		leftPadding: 13
		rightPadding: 13
		contentItem: Text {
			text: buttonControl.text
			font: buttonControl.font
			color: !buttonControl.enabled ? "#90959c" : buttonControl.accent ? "white" : "#20242a"
			horizontalAlignment: Text.AlignHCenter
			verticalAlignment: Text.AlignVCenter
			elide: Text.ElideRight
		}
		background: Rectangle {
			radius: 7
			border.width: 1
			border.color: !buttonControl.enabled ? "#c9cdd2" : buttonControl.accent ? "#246ac1" : buttonControl.hovered ? "#8b939c" : "#aeb4bb"
			color: {
				if (!buttonControl.enabled) return "#e6e8eb"
				if (buttonControl.accent) return buttonControl.down ? "#2368ba" : buttonControl.hovered ? "#3c8bea" : "#2f80d8"
				return buttonControl.down ? "#d8dce1" : buttonControl.hovered ? "#f8f9fa" : "#eef0f2"
			}
		}
	}
	FileDialog {
		id: openDialog
		title: "选择图片"
		nameFilters: ["图片 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)", "所有文件 (*)"]
		onAccepted: window.sourceFile = selectedFile
	}
	FolderDialog {
		id: folderDialog
		title: "选择输出路径"
		onAccepted: {
			window.automaticOutput = false
			outputPath.text = controller.localPath(selectedFolder)
		}
	}
	FileDialog {
		id: saveDialog
		title: "保存黑白图片"
		fileMode: FileDialog.SaveFile
		nameFilters: ["PNG 图片 (*.png)"]
		defaultSuffix: "png"
		onAccepted: controller.save(selectedFile)
	}
	Dialog {
		id: advanced
		title: "局部算法参数"
		anchors.centerIn: parent
		modal: true
		standardButtons: Dialog.Close
		background: Rectangle {
			radius: 10
			color: "#f7f8fa"
			border.width: 1
			border.color: "#bfc4ca"
		}
		GridLayout {
			columns: 2
			Label { text: "自适应 C" }
			SpinBox { id: adaptiveC; from: -100; to: 100; value: 5; editable: true; onValueModified: window.requestPreview() }
			Label { text: "局部 k × 100" }
			SpinBox { id: localK; from: -100; to: 100; value: 20; editable: true; onValueModified: window.requestPreview() }
		}
	}
	ColumnLayout {
		anchors.fill: parent
		anchors.margins: 10
		spacing: 8
		GridLayout {
			columns: 3
			Layout.fillWidth: true
				Label { text: "当前图片" }
			TextField {
				id: sourcePath
				Layout.fillWidth: true
				selectByMouse: true
				onEditingFinished: if (text !== controller.localPath(window.sourceFile)) window.sourceFile = controller.fileUrl(text)
			}
				AppButton { text: "选择图片"; onClicked: openDialog.open() }
			Label { text: "输出路径" }
			TextField { id: outputPath; Layout.fillWidth: true; selectByMouse: true; onTextEdited: window.automaticOutput = false }
			AppButton { text: "选择目录"; onClicked: folderDialog.open() }
		}
		RowLayout {
			Layout.fillWidth: true
			Layout.fillHeight: true
			spacing: 16
			ScrollView {
				id: controlsScroll
				Layout.preferredWidth: 350
				Layout.fillHeight: true
				clip: true
				ColumnLayout {
					width: controlsScroll.availableWidth
					spacing: 8
					ControlsGroup {
						title: "二值化"
						GridLayout {
							anchors.fill: parent
							columns: 2
							rowSpacing: 2
							Label { text: "方法" }
							ComboBox {
								id: method
								Layout.fillWidth: true
								model: ["固定阈值", "自适应阈值", "Otsu 阈值", "Sauvola 阈值", "Wolf 阈值", "Nick 阈值", "Bernsen 阈值"]
								currentIndex: 1
								onActivated: window.requestPreview()
							}
							Label { text: "阈值" }
							ValueSlider { id: threshold; to: 255; value: 127 }
							Label { text: "局部窗口" }
							RowLayout {
								SpinBox { id: block; Layout.fillWidth: true; from: 3; to: 101; stepSize: 2; value: 31; editable: true; onValueModified: { if (value % 2 === 0) value += 1; window.requestPreview() } }
								AppButton { text: "…"; implicitWidth: 34; onClicked: advanced.open(); ToolTip.visible: hovered; ToolTip.text: "局部算法参数" }
							}
							AppButton {
								text: "Try All · 多算法对比"
								accent: true
								Layout.columnSpan: 2
								Layout.fillWidth: true
								enabled: !controller.busy && !window.pendingPreview && window.sourceFile.toString().length > 0
								onClicked: window.showComparison()
							}
						}
					}
					ControlsGroup {
						title: "预处理"
						GridLayout {
							anchors.fill: parent
							columns: 2
							rowSpacing: 2
							Label { text: "曝光" }
							ValueSlider { id: exposure; from: -100 }
							Label { text: "对比度" }
							ValueSlider { id: contrast; from: -100 }
							Label { text: "伽马" }
							ValueSlider { id: gamma; from: 10; to: 300; value: 100; decimal: true }
							Label { text: "平滑" }
							ValueSlider { id: smooth }
							Label { text: "锐化" }
							ValueSlider { id: sharpen }
						}
					}
					ControlsGroup {
						title: "降噪与增强"
						GridLayout {
							anchors.fill: parent
							columns: 2
							rowSpacing: 2
							Label { text: "方法" }
							ComboBox { id: denoise; Layout.fillWidth: true; model: ["高斯降噪", "中值滤波", "双边滤波", "NLMeans 降噪"]; onActivated: window.requestPreview() }
							Label { text: "强度" }
							ValueSlider { id: strength }
							Label { text: "均衡化" }
							RowLayout {
								CheckBox { id: equalize; text: "直方图均衡化"; onClicked: { if (checked) clahe.checked = false; window.requestPreview() } }
								CheckBox { id: clahe; text: "CLAHE"; onClicked: { if (checked) equalize.checked = false; window.requestPreview() } }
							}
							Label { text: "细节" }
							ValueSlider { id: detail }
							Label { text: "边缘" }
							ValueSlider { id: edge }
							Label { text: "局部对比度" }
							ValueSlider { id: localContrast }
						}
					}
					ControlsGroup {
						title: "输出"
						RowLayout {
							anchors.fill: parent
							CheckBox { id: invert; text: "反相"; onClicked: window.requestPreview() }
							CheckBox { id: horizontal; text: "水平翻转"; onClicked: window.requestPreview() }
							CheckBox { id: vertical; text: "垂直翻转"; onClicked: window.requestPreview() }
						}
					}
				}
			}
			RoundedFrame {
				Layout.fillWidth: true
				Layout.fillHeight: true
				Image {
					anchors.fill: parent
					source: window.showingOriginal ? window.sourceFile : window.displayedResult
					fillMode: Image.PreserveAspectFit
					smooth: window.showingOriginal
					cache: false
				}
				Label { anchors.centerIn: parent; text: "请选择或拖入图片"; visible: !window.sourceFile.toString().length }
				DropArea { anchors.fill: parent; onDropped: drop => { if (drop.hasUrls) window.sourceFile = drop.urls[0] } }
			}
		}
		RowLayout {
			Layout.fillWidth: true
			Item { Layout.fillWidth: true }
			AppButton { text: "取消计算"; visible: controller.busy; onClicked: { window.pendingPreview = false; previewTimer.stop(); controller.cancel() } }
			AppButton { text: window.showingOriginal ? "查看处理结果" : "查看原图"; enabled: window.sourceFile.toString().length > 0; onClicked: window.showingOriginal = !window.showingOriginal }
			AppButton {
				text: "保存黑白图片"
				enabled: !controller.busy && !window.pendingPreview && controller.resultUrl.length > 0
				onClicked: { saveDialog.selectedFile = controller.outputFile(window.sourceFile, outputPath.text); saveDialog.open() }
			}
		}
		Label { text: window.pendingPreview ? "正在更新预览…" : controller.status; Layout.fillWidth: true; elide: Text.ElideRight; font.pixelSize: 13 }
	}
	Dialog {
		id: comparison
		objectName: "comparisonDialog"
		property bool applied: false
		title: "Try All · 多算法对比"
		modal: true
		anchors.centerIn: parent
		width: Math.min(window.width - 40, 1000)
		height: Math.min(window.height - 40, 750)
		onClosed: if (!applied) window.requestPreview()
		background: Rectangle {
			radius: 10
			color: "#f7f8fa"
			border.width: 1
			border.color: "#bfc4ca"
		}
		footer: DialogButtonBox {
			AppButton {
				text: "关闭"
				DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
			}
			onRejected: comparison.close()
		}
		ColumnLayout {
			anchors.fill: parent
			Label { text: "使用当前预处理设置。选择方案后，返回主界面查看完整分辨率结果。"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
			Label { text: controller.status; visible: controller.busy || controller.candidates.length === 0; Layout.fillWidth: true; wrapMode: Text.WordWrap }
			ScrollView {
				id: comparisonScroll
				Layout.fillWidth: true
				Layout.fillHeight: true
				clip: true
				GridLayout {
					width: comparisonScroll.availableWidth
					columns: 3
					Repeater {
						model: controller.candidates
						RoundedFrame {
							required property var modelData
							required property int index
							Layout.fillWidth: true
							Layout.preferredWidth: 240
							ColumnLayout {
								anchors.fill: parent
								Label { text: modelData.name; font.bold: true }
								Image { source: modelData.image; Layout.fillWidth: true; Layout.preferredHeight: 130; fillMode: Image.PreserveAspectFit; smooth: false; cache: false }
								Label { text: modelData.parameters; font.pixelSize: 12; Layout.fillWidth: true; wrapMode: Text.WordWrap }
								Label { text: modelData.error; visible: text.length > 0; Layout.fillWidth: true; wrapMode: Text.WordWrap }
								AppButton { text: "应用 " + modelData.name; accent: true; enabled: !controller.busy && modelData.error.length === 0; onClicked: { method.currentIndex = index; window.showingOriginal = false; comparison.applied = true; comparison.close(); controller.apply(index) } }
							}
						}
					}
				}
			}
		}
	}
}
