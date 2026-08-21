# 淘宝芭芭农场自动任务助手

基于 **ADB + uiautomator2** 的安卓手机自动化脚本，自动进入淘宝「芭芭农场」的「集肥料」任务页面，识别并点击任务按钮，循环完成任务、领取肥料。

## 功能特性

- **自动启动淘宝**：支持指定 Activity 启动，失败自动回退普通启动，并支持 Android 多用户（多开）环境。
- **自动静音**：应用启动成功后自动将媒体音量调至 0（Android 11+ 使用 `cmd media_session`，旧系统自动降级），避免任务声音打扰。
- **双通道任务识别**：
  - **UI 识别**：通过无障碍节点查找 `去完成 / 去浏览 / 去领取` 按钮，刚进入任务页面时优先使用。
  - **OCR 识别**：UI 识别不到（WebView/Canvas 渲染、按钮不暴露在节点树中）时，下滑到页面底部后用 **RapidOCR** 识别按钮文字，再配合任务名定位点击坐标。
- **自动下滑查找任务**：UI 连续找不到按钮时自动下滑页面，直到页面底部或找到可点击按钮。
- **任务过滤与跳过**：通过 `skip_keywords` 跳过指定任务（如支付宝、快手、补贴类等），通过 `have_clicked` 记录同一任务最多执行 2 次。
- **指定关键词任务**：通过 `ocr_keywords` 配置，优先查找并执行你指定的任务（如「逛精选好物」）。
- **浏览闭环**：点击任务后自动完成搜索/浏览商品等操作（`task_loop`），完成后自动返回任务页面。
- **全局弹窗 Watcher**：自动点击广告、弹窗、「跳过」「刷新」「立即施肥」等按钮，减少人工干预。
- **验证码拦截处理**：检测到「验证码拦截」页面时自动尝试滑动验证。
- **多设备选择**：连接多台设备时自动列出设备（品牌/型号/系统版本）供选择。
- **纯 Python 图像处理**：模板匹配等图像算法使用 numpy/PIL 实现，无需安装 OpenCV（cv2）。

## 环境要求

- **Windows**（脚本含 `.bat` 启动文件，其他系统可直接 `python` 运行）
- **Python 3.9+**
- **Android 手机**（开启 USB 调试，且电脑已安装 adb 并加入 PATH）
- 手机与电脑通过 USB 连接（或 adb 可访问的网络设备）

## 安装

```bash
# 1. 安装 Python 依赖
pip install -r requirements.txt

# 2. 安装 uiautomator2 到手机（首次连接手机时执行一次）
python -m uiautomator2 init
```

依赖清单（`requirements.txt`）：

| 依赖 | 版本 | 用途 |
| --- | --- | --- |
| uiautomator2 | 3.5.2 | ADB UI 自动化 |
| uiautodev | 0.14.0 | uiautomator2 配套工具 |
| rapidocr | >=3.9.0 | OCR 文字识别（PP-OCR 模型） |
| onnxruntime | - | RapidOCR 推理引擎 |
| ddddocr | 1.5.6 | 备用 OCR |

> 若希望离线使用 RapidOCR，可将 `*_det.onnx / *_rec.onnx / *_cls.onnx` 模型放入项目根目录 `models/rapidocr/` 文件夹，脚本会自动优先加载本地模型。

## 使用方法

### 方式一：双击启动（Windows）

双击 `启动淘宝任务.bat`，脚本会自动切换到项目目录并运行主程序。

> 提示：如果 adb 不在系统 PATH 中，可编辑该 `.bat` 文件，把 `set "PATH=D:\devkitPro\ADB;%PATH%"` 中的路径改为你本机 adb 所在目录。

### 方式二：命令行运行

```bash
python 淘宝芭芭农场.py
```

### 运行流程

1. 连接手机并开启 USB 调试，确认 `adb devices` 能识别到设备。
2. 运行脚本，选择设备（多设备时输入序号）。
3. 脚本自动：启动淘宝 → 静音 → 进入芭芭农场 → 点击「集肥料」进入任务页面 → 循环查找并完成任务。
4. 结束后打印完成的任务总数与总耗时，并关闭手机自动旋转。

## 配置说明

### 跳过任务关键词（`淘宝芭芭农场.py`）

```python
skip_keywords = [
    '尖货补贴', '淘宝特价', '买限时', '支付宝', '快手',
    '邀请', '大众点评', '蛋仔', '微博', '闲鱼', '补贴',
]
```

任务名包含以上任一关键词时自动跳过（不点击）。

### 指定 OCR 目标任务（`淘宝芭芭农场.py`）

```python
ocr_keywords = [
    '逛精选好物', '搜一搜你喜欢的商品', '品牌x农场狂补周'
]
```

当 UI 识别不到按钮时，会下滑到页面底部，用 OCR 优先查找包含这些关键词的任务并执行。

### 多用户（多开）配置（`utils.py`）

```python
# None = 自动检测并交互选择；"0" = 机主；"999" = MultiApp（多开）
DEFAULT_USER_ID = "0"
```

### 任务执行上限

同一任务最多执行 2 次（`have_clicked` 计数），避免重复刷同一任务。

## 项目结构

```
Tb-Baba-Farm-Auto/
├── 淘宝芭芭农场.py        # 主脚本（自动化流程）
├── utils.py               # 工具库（设备连接/静音/OCR/滑动/图像匹配等）
├── 启动淘宝任务.bat       # Windows 一键启动脚本
├── requirements.txt       # Python 依赖
├── img/                   # 模板匹配图片
├── test/                  # 测试用例
│   ├── test_volume_mute.py    # 媒体音量静音/恢复测试
│   └── __init__.py
├── task/                  # 需求与开发记录
│   └── task.md
└── 识别图片测试.py        # OCR 图片识别独立测试脚本
```

## 测试

```bash
# 音量静音/恢复测试（需连接手机）
python test/test_volume_mute.py

# 或使用 unittest 方式
python -m unittest test.test_volume_mute -v
```

## 常见问题

| 问题 | 解决方法 |
| --- | --- |
| `未检测到任何连接的安卓设备` | 确认手机开启 USB 调试、`adb devices` 可看到设备 |
| OCR 识别不到按钮 | 确认 `rapidocr` 已正确安装；首次运行会下载模型，需联网；或放入本地模型到 `models/rapidocr/` |
| 任务页面按钮点击无反应 | 任务页为 WebView/Canvas 渲染时，脚本会自动切换到 OCR 通道点击坐标 |
| 静音不生效 | Android 8+ 的 `settings put` 多无效，脚本已内置 `cmd media_session` + 按键逐级调节的多策略兜底 |

## 免责声明

本脚本仅供个人学习与自动化研究使用，请遵守淘宝平台的服务协议与相关法律法规，勿用于批量刷取奖励、影响平台正常运营等行为。使用本脚本产生的一切后果由使用者自行承担。

## License

[Apache License 2.0](LICENSE)
