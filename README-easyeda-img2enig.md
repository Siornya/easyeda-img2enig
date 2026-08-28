# easyeda-img2enig

`easyeda-img2enig.py` 将已经处理好的纯黑白图片转换成嘉立创 EDA 专业版沉金图案工程。

它只负责生成沉金制造图层，不负责图片二值化、降噪、阈值、反色、镜像、丝印或图形
界面。原始图片应先由图片处理项目输出为只包含黑色和白色像素的图片。

## 工作原理

程序将黑色区域视为需要露金的完整面积：

1. 读取纯黑白图片。
2. 将连续的黑色像素无损合并成填充矩形。
3. 在顶层或底层铜层生成实心 `FILL` 图形。
4. 在对应阻焊层生成相同图形，形成阻焊开窗。
5. 制板下单时选择沉金表面处理，使开窗处的铜面形成金色表面。

黑色区域会完整填充，不是只绘制边缘轮廓。白色区域不会生成铜箔或阻焊开窗。

## 依赖

- Python 3.9 或更高版本
- NumPy
- OpenCV

在当前项目中安装依赖：

```bash
python3 -m pip install -r requirements.txt
```

## 基本用法

```bash
python3 easyeda-img2enig.py 已二值化图片.png
```

默认行为：

- 在输入图片旁生成同名 `.epro2`
- 图案宽度为 50 mm
- 保持原图宽高比例
- 图案放在顶面
- 图案周围留出 1 mm 板边
- 自动生成矩形板框

## 指定输出和尺寸

```bash
python3 easyeda-img2enig.py 已二值化图片.png \
    -o 沉金图案.epro2 \
    --width-mm 40
```

如需强制指定高度：

```bash
python3 easyeda-img2enig.py 已二值化图片.png \
    -o 沉金图案.epro2 \
    --width-mm 40 \
    --height-mm 30
```

## 选择板面

顶面沉金：

```bash
python3 easyeda-img2enig.py 已二值化图片.png --side top
```

生成的填充图层为：

- `1`：顶层铜
- `5`：顶层阻焊开窗

底面沉金：

```bash
python3 easyeda-img2enig.py 已二值化图片.png --side bottom
```

生成的填充图层为：

- `2`：底层铜
- `6`：底层阻焊开窗

## 板边设置

设置图案与板框之间的留白：

```bash
python3 easyeda-img2enig.py 已二值化图片.png --margin-mm 2
```

不生成板框：

```bash
python3 easyeda-img2enig.py 已二值化图片.png --no-outline
```

## 检查工程

```bash
python3 easyeda-img2enig.py 沉金图案.epro2 --inspect
```

检查结果会列出工程文档、记录数量和实际 `FILL` 图层。顶面应为 `[1, 5]`，底面应为
`[2, 6]`。

## 输入要求

单色输入必须只包含像素值 `0` 和 `255`。如果图片包含灰色、抗锯齿或 JPEG 压缩产生
的中间色，程序会拒绝转换。请先在图片处理项目中完成二值化，并优先保存为 PNG。

透明图片会先与白色背景合成；半透明边缘可能产生灰色像素并触发输入检查。

## 输出格式

当前只生成经过结构验证的 `.epro2`：

- `project2.json`
- 一个包含 `BOARD`、`PCB`、`CONFIG` 文档的 `.epru` 日志

`.eprj2` 是 SQLite 离线工程数据库，当前没有生成该格式。

## 制造注意事项

- 沉金不是彩色打印，而是裸露铜面经过化学镍金处理。
- PCB 下单时必须选择沉金表面处理。
- 当前铜图形和阻焊开窗使用完全相同的尺寸；正式生产前应根据板厂能力检查阻焊偏位
  和是否需要扩大开窗。
- 过小的孤立区域、细线和间距可能低于制造能力。
- 生成后应在 EDA 中检查铜层、阻焊层、DRC、2D/3D 和 Gerber 预览。

## 完整示例

```bash
python3 easyeda-img2enig.py img/1.转化后.png \
    -o output.epro2 \
    --side top \
    --width-mm 40 \
    --margin-mm 1

python3 easyeda-img2enig.py output.epro2 --inspect
```
