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
	title: "Nasti PCB Designer"
	font.pixelSize: 15
	property url sourceFile
	property bool automaticOutput: true
	property bool showingOriginal: false
	property bool pendingPreview: false
	property bool selectingLayer: false
	readonly property bool darkMode: Application.styleHints.colorScheme === Qt.Dark
	property string displayedResult: ""
	property var currentLayer: {
		for (const layer of controller.layers)
			if (layer.selected) return layer
		return null
	}
	readonly property color pageColor: darkMode ? "#1f2329" : "#f0f1f3"
	readonly property color surfaceColor: darkMode ? "#292e36" : "#f5f6f8"
	readonly property color raisedColor: darkMode ? "#323842" : "#ffffff"
	readonly property color borderColor: darkMode ? "#4d5663" : "#c5c9ce"
	readonly property color textColor: darkMode ? "#e8ebef" : "#20242a"
	readonly property color mutedTextColor: darkMode ? "#aeb6c2" : "#666c74"
	readonly property color trackColor: darkMode ? "#505966" : "#cfd4da"
	readonly property color buttonColor: darkMode ? "#343b45" : "#eef0f2"
	readonly property color buttonHoverColor: darkMode ? "#404956" : "#f8f9fa"
	readonly property color buttonDownColor: darkMode ? "#2b3139" : "#d8dce1"
	readonly property color disabledColor: darkMode ? "#292e35" : "#e6e8eb"
	readonly property color disabledTextColor: darkMode ? "#737b86" : "#90959c"
	readonly property color selectedColor: darkMode ? "#263e5c" : "#e7f1ff"
	color: pageColor
	palette.window: pageColor
	palette.windowText: textColor
	palette.base: darkMode ? "#242930" : "#ffffff"
	palette.alternateBase: surfaceColor
	palette.text: textColor
	palette.button: buttonColor
	palette.buttonText: textColor
	palette.highlight: "#2f80d8"
	palette.highlightedText: "#ffffff"
	palette.mid: borderColor
	palette.placeholderText: mutedTextColor

	function parameters() {
		return { method: method.currentIndex, threshold: threshold.value, blockSize: block.value,
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
	function chooseLayer(index) {
		selectingLayer = true
		controller.selectLayer(index)
		applySelectedParameters()
		sourceFile = controller.selectedSourceUrl
		displayedResult = controller.compositeUrl
		showingOriginal = false
		selectingLayer = false
	}
	function switchSide(side) {
		selectingLayer = true
		controller.setActiveSide(side)
		sourceFile = controller.selectedSourceUrl
		displayedResult = controller.compositeUrl
		showingOriginal = false
		applySelectedParameters()
		selectingLayer = false
	}
	function applySelectedParameters() {
		const values = controller.selectedParameters
		if (values.method === undefined) return
		method.currentIndex = values.method
		threshold.value = values.threshold
		block.value = values.blockSize
		adaptiveC.value = values.adaptiveC
		localK.value = Math.round(values.localK * 100)
		exposure.value = values.exposure
		contrast.value = values.contrast
		gamma.value = Math.round(values.gamma * 100)
		denoise.currentIndex = values.denoiseMethod
		strength.value = values.denoiseStrength
		smooth.value = values.smooth
		sharpen.value = values.sharpen
		detail.value = values.detail
		edge.value = values.edge
		localContrast.value = values.localContrast
		equalize.checked = values.equalize
		clahe.checked = values.clahe
		invert.checked = values.invert
		horizontal.checked = values.flipHorizontal
		vertical.checked = values.flipVertical
	}
	function syncCoordinates() {
		if (!currentLayer) {
			leftX.text = ""
			topY.text = ""
			centerX.text = ""
			centerY.text = ""
			return
		}
		leftX.text = Number(currentLayer.leftX).toFixed(2)
		topY.text = Number(currentLayer.topY).toFixed(2)
		centerX.text = Number(currentLayer.centerX).toFixed(2)
		centerY.text = Number(currentLayer.centerY).toFixed(2)
	}
	function showComparison() {
		previewTimer.stop()
		pendingPreview = false
		comparison.applied = false
		comparison.open()
		controller.compare(sourceFile, parameters())
	}
	function setLayerMaterial(layerIndex, materialIndex) {
		controller.setLayerType(layerIndex, materialIndex === 0 ? "enig" : "silk")
	}
	onSourceFileChanged: {
		if (automaticOutput && !controller.hasExportableLayers && sourceFile.toString().length)
			outputPath.text = controller.sourceDirectory(sourceFile)
		displayedResult = ""
		if (!selectingLayer) requestPreview()
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
			if (!window.pendingPreview)
				window.displayedResult = controller.compositeUrl
			if (!controller.busy && controller.selectedSourceUrl !== window.sourceFile.toString()) {
				window.selectingLayer = true
				window.sourceFile = controller.selectedSourceUrl
				window.applySelectedParameters()
				window.selectingLayer = false
			}
			window.syncCoordinates()
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
				color: window.trackColor
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
				color: slider.pressed ? (window.darkMode ? "#334d6d" : "#eaf3ff") : window.raisedColor
				border.width: 1
				border.color: slider.hovered ? "#2f80ed" : window.borderColor
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
			color: window.textColor
		}
		background: Rectangle {
			y: 22
			width: groupControl.width
			height: groupControl.height - y
			radius: 8
			color: window.surfaceColor
			border.width: 1
			border.color: window.borderColor
		}
	}
	component RoundedFrame: Frame {
		padding: 9
		background: Rectangle {
			radius: 9
			color: window.surfaceColor
			border.width: 1
			border.color: window.borderColor
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
			color: !buttonControl.enabled ? window.disabledTextColor : buttonControl.accent ? "white" : window.textColor
			horizontalAlignment: Text.AlignHCenter
			verticalAlignment: Text.AlignVCenter
			elide: Text.ElideRight
		}
		background: Rectangle {
			radius: 7
			border.width: 1
			border.color: !buttonControl.enabled ? window.borderColor : buttonControl.accent ? "#246ac1" : buttonControl.hovered ? (window.darkMode ? "#687483" : "#8b939c") : window.borderColor
			color: {
				if (!buttonControl.enabled) return window.disabledColor
				if (buttonControl.accent) return buttonControl.down ? "#2368ba" : buttonControl.hovered ? "#3c8bea" : "#2f80d8"
				return buttonControl.down ? window.buttonDownColor : buttonControl.hovered ? window.buttonHoverColor : window.buttonColor
			}
		}
	}
	component CoordField: TextField {
		implicitHeight: 30
		horizontalAlignment: Text.AlignRight
		selectByMouse: true
		enabled: !controller.busy && controller.selectedLayer >= 0
		validator: DoubleValidator { bottom: 0; decimals: 2; notation: DoubleValidator.StandardNotation }
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
			color: window.raisedColor
			border.width: 1
			border.color: window.borderColor
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
								objectName: "methodSelector"
								Layout.fillWidth: true
								model: ["固定阈值", "自适应阈值", "Otsu 阈值", "Triangle 阈值", "Li 阈值", "Sauvola 阈值", "Wolf 阈值", "Bernsen 阈值"]
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
			RoundedFrame {
				Layout.preferredWidth: 250
				Layout.fillHeight: true
				ColumnLayout {
					anchors.fill: parent
					spacing: 8
					Rectangle {
						Layout.fillWidth: true
						Layout.preferredHeight: 36
						radius: 8
						color: window.borderColor
						Rectangle {
							anchors.fill: parent
							anchors.margins: 1
							radius: 7
							clip: true
							color: window.buttonColor
							RowLayout {
								anchors.fill: parent
								spacing: 0
								Button {
									id: frontSideButton
									Layout.fillWidth: true
									Layout.fillHeight: true
									padding: 0
									hoverEnabled: true
									enabled: !controller.busy
									Accessible.name: "正面"
									onClicked: window.switchSide("front")
									contentItem: Text {
										text: "正面"
										font.pixelSize: frontSideButton.font.pixelSize
										font.bold: controller.activeSide === "front"
										color: controller.activeSide === "front" ? "white" : window.textColor
										horizontalAlignment: Text.AlignHCenter
										verticalAlignment: Text.AlignVCenter
									}
									background: Rectangle {
										color: controller.activeSide === "front" ? "#2f80d8"
											: frontSideButton.down ? window.buttonDownColor
											: frontSideButton.hovered ? window.buttonHoverColor : window.buttonColor
									}
								}
								Rectangle {
									Layout.preferredWidth: 1
									Layout.fillHeight: true
									color: window.borderColor
								}
								Button {
									id: backSideButton
									Layout.fillWidth: true
									Layout.fillHeight: true
									padding: 0
									hoverEnabled: true
									enabled: !controller.busy
									Accessible.name: "背面"
									onClicked: window.switchSide("back")
									contentItem: Text {
										text: "背面"
										font.pixelSize: backSideButton.font.pixelSize
										font.bold: controller.activeSide === "back"
										color: controller.activeSide === "back" ? "white" : window.textColor
										horizontalAlignment: Text.AlignHCenter
										verticalAlignment: Text.AlignVCenter
									}
									background: Rectangle {
										color: controller.activeSide === "back" ? "#2f80d8"
											: backSideButton.down ? window.buttonDownColor
											: backSideButton.hovered ? window.buttonHoverColor : window.buttonColor
									}
								}
							}
						}
					}
					Rectangle {
						Layout.fillWidth: true
						Layout.preferredHeight: 112
						radius: 8
						color: window.raisedColor
						border.width: 1
						border.color: window.borderColor
						GridLayout {
							anchors.fill: parent
							anchors.margins: 8
							columns: 4
							columnSpacing: 5
							rowSpacing: 6
							Label { text: "左上 X" }
							CoordField {
								id: leftX
								Layout.fillWidth: true
								onEditingFinished: controller.setLayerTopLeft(controller.selectedLayer, Number(text), Number(topY.text))
							}
							Label { text: "Y" }
							CoordField {
								id: topY
								Layout.fillWidth: true
								onEditingFinished: controller.setLayerTopLeft(controller.selectedLayer, Number(leftX.text), Number(text))
							}
							Label { text: "中心 X" }
							CoordField {
								id: centerX
								Layout.fillWidth: true
								onEditingFinished: controller.setLayerCenter(controller.selectedLayer, Number(text), Number(centerY.text))
							}
							Label { text: "Y" }
							CoordField {
								id: centerY
								Layout.fillWidth: true
								onEditingFinished: controller.setLayerCenter(controller.selectedLayer, Number(centerX.text), Number(text))
							}
							Label {
								Layout.columnSpan: 4
								Layout.fillWidth: true
								text: window.currentLayer ? "当前图层 " + currentLayer.width + " × " + currentLayer.height + " px" : "请选择图层"
								font.pixelSize: 12
								color: window.mutedTextColor
							}
						}
					}
					RowLayout {
						Layout.fillWidth: true
						AppButton { text: "添加图层"; Layout.fillWidth: true; enabled: !controller.busy; onClicked: openDialog.open() }
						AppButton { text: "删除图层"; Layout.fillWidth: true; enabled: !controller.busy && controller.selectedLayer >= 0; onClicked: controller.removeLayer(controller.selectedLayer) }
					}
					Rectangle {
						Layout.fillWidth: true
						Layout.fillHeight: true
						radius: 8
						color: window.surfaceColor
						border.width: 1
						border.color: window.borderColor
						ListView {
							id: layerList
							anchors.fill: parent
							anchors.margins: 7
							clip: true
							spacing: 7
							model: controller.layers
							delegate: Rectangle {
								required property var modelData
								width: layerList.width
								height: 104
								radius: 8
								color: modelData.selected ? window.selectedColor : window.raisedColor
								border.width: 1
								border.color: modelData.selected ? "#2f80d8" : window.borderColor
								ColumnLayout {
									anchors.fill: parent
									anchors.margins: 7
									spacing: 4
									RowLayout {
										Layout.fillWidth: true
										Image {
											Layout.preferredWidth: 42
											Layout.preferredHeight: 42
											source: modelData.thumbnail
											fillMode: Image.PreserveAspectFit
											smooth: false
											cache: false
											MouseArea { anchors.fill: parent; onClicked: window.chooseLayer(modelData.layerIndex) }
										}
										ColumnLayout {
											Layout.fillWidth: true
											Label {
												Layout.fillWidth: true
												text: modelData.name
												font.bold: modelData.selected
												elide: Text.ElideMiddle
												MouseArea { anchors.fill: parent; onClicked: window.chooseLayer(modelData.layerIndex) }
											}
											CheckBox {
												text: "显示"
												checked: modelData.visible
												enabled: !controller.busy
												onToggled: controller.setLayerVisible(modelData.layerIndex, checked)
											}
										}
									}
									RowLayout {
										Layout.fillWidth: true
										ComboBox {
											Layout.fillWidth: true
											model: ["沉金", "丝印"]
											currentIndex: modelData.type === "enig" ? 0 : 1
											enabled: !controller.busy
											onActivated: window.setLayerMaterial(modelData.layerIndex, currentIndex)
										}
										AppButton { text: "↑"; implicitWidth: 30; enabled: !controller.busy && modelData.canMoveUp; onClicked: controller.moveLayer(modelData.layerIndex, -1) }
										AppButton { text: "↓"; implicitWidth: 30; enabled: !controller.busy && modelData.canMoveDown; onClicked: controller.moveLayer(modelData.layerIndex, 1) }
									}
								}
							}
						}
						Label {
							anchors.centerIn: parent
							visible: controller.layers.length === 0
							text: "添加图片后在这里管理图层"
							color: window.mutedTextColor
							wrapMode: Text.WordWrap
							width: parent.width - 20
							horizontalAlignment: Text.AlignHCenter
						}
					}
					Rectangle {
						Layout.fillWidth: true
						Layout.preferredHeight: 122
						radius: 8
						color: window.raisedColor
						border.width: 1
						border.color: window.borderColor
						GridLayout {
							anchors.fill: parent
							anchors.margins: 9
							columns: 2
							Label { text: "总体 X 大小" }
							Label { text: controller.canvasWidth + " px"; font.bold: true; Layout.alignment: Qt.AlignRight }
							Label { text: "总体 Y 大小" }
							Label { text: controller.canvasHeight + " px"; font.bold: true; Layout.alignment: Qt.AlignRight }
							Label { text: "阻焊颜色" }
							ComboBox {
								Layout.fillWidth: true
								model: ["绿", "红", "黄", "蓝", "白", "哑黑"]
								currentIndex: ["green", "red", "yellow", "blue", "white", "black"]
									.indexOf(controller.solderMaskColor)
								enabled: !controller.busy
								onActivated: controller.setSolderMaskColor(
									["green", "red", "yellow", "blue", "white", "black"][currentIndex])
							}
						}
					}
				}
			}
		}
		RowLayout {
			Layout.fillWidth: true
			Label { text: "输出目录" }
			TextField {
				id: outputPath
				Layout.fillWidth: true
				Layout.minimumWidth: 180
				selectByMouse: true
				onTextEdited: window.automaticOutput = false
			}
			AppButton { text: "选择目录"; onClicked: folderDialog.open() }
			AppButton { text: "取消计算"; visible: controller.busy; onClicked: { window.pendingPreview = false; previewTimer.stop(); controller.cancel() } }
			AppButton { text: window.showingOriginal ? "查看处理结果" : "查看原图"; enabled: window.sourceFile.toString().length > 0; onClicked: window.showingOriginal = !window.showingOriginal }
			AppButton {
				text: "保存黑白图片"
				enabled: !controller.busy && !window.pendingPreview && controller.resultUrl.length > 0
				onClicked: { saveDialog.selectedFile = controller.outputFile(window.sourceFile, outputPath.text); saveDialog.open() }
			}
			AppButton {
				text: "生成PCB文件"
				enabled: !controller.busy && !window.pendingPreview && controller.hasExportableLayers
				onClicked: controller.generatePcb(window.sourceFile, outputPath.text)
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
		width: Math.min(window.width - 30, 1220)
		height: Math.min(window.height - 30, 770)
		onClosed: if (!applied) window.requestPreview()
		background: Rectangle {
			radius: 10
			color: window.raisedColor
			border.width: 1
			border.color: window.borderColor
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
			Label { text: "调整参数后点击重新比较。选择方案后，返回主界面查看完整分辨率结果。"; Layout.fillWidth: true; wrapMode: Text.WordWrap }
			RoundedFrame {
				Layout.fillWidth: true
				RowLayout {
					anchors.fill: parent
					spacing: 8
					Label { text: "阈值" }
					SpinBox {
						from: 0
						to: 255
						value: Math.round(threshold.value)
						editable: true
						onValueModified: threshold.value = value
					}
					Label { text: "局部窗口" }
					SpinBox {
						from: 3
						to: 101
						stepSize: 2
						value: Math.round(block.value)
						editable: true
						onValueModified: {
							if (value % 2 === 0) value += value < to ? 1 : -1
							block.value = value
						}
					}
					Label { text: "自适应 C" }
					SpinBox {
						from: -100
						to: 100
						value: Math.round(adaptiveC.value)
						editable: true
						onValueModified: adaptiveC.value = value
					}
					Label { text: "局部 k × 100" }
					SpinBox {
						from: -100
						to: 100
						value: Math.round(localK.value)
						editable: true
						onValueModified: localK.value = value
					}
					Item { Layout.fillWidth: true }
					AppButton {
						text: "重新比较"
						accent: true
						enabled: !controller.busy
						onClicked: controller.compare(window.sourceFile, window.parameters())
					}
				}
			}
			Label { text: controller.status; visible: controller.busy || controller.candidates.length === 0; Layout.fillWidth: true; wrapMode: Text.WordWrap }
			ScrollView {
				id: comparisonScroll
				Layout.fillWidth: true
				Layout.fillHeight: true
				clip: true
				GridLayout {
					width: comparisonScroll.availableWidth
					columns: comparisonScroll.availableWidth >= 820 ? 2 : 1
					Repeater {
						model: controller.candidates
						RoundedFrame {
							required property var modelData
							required property int index
							Layout.fillWidth: true
							Layout.preferredWidth: comparisonScroll.availableWidth >= 820 ? 500 : comparisonScroll.availableWidth
							ColumnLayout {
								anchors.fill: parent
								Label { text: modelData.name; font.bold: true }
								Image { source: modelData.image; Layout.fillWidth: true; Layout.preferredHeight: 250; fillMode: Image.PreserveAspectFit; smooth: false; cache: false }
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
