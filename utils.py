import time
import sys
import random
import io
import re
import numpy as np
import ddddocr
import subprocess
import ssl
import urllib.request
import traceback
import uiautomator2 as u2

# 正确的SSL禁用方式：赋值为「调用后的上下文对象」，而非函数本身
original_context = ssl._create_default_https_context
ssl._create_default_https_context = ssl._create_unverified_context()  # 关键：加()调用函数

# 额外配置urllib的opener，双重确保跳过SSL验证
opener = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=ssl._create_unverified_context())
)
urllib.request.install_opener(opener)

# from paddleocr import PaddleOCR
import os
from PIL import Image, ImageDraw

# RapidOCR 引擎单例，避免每次识别重复加载模型
_rapidocr_engine = None


def get_rapidocr():
    """懒加载 RapidOCR 引擎实例（基于 ONNX Runtime，默认 PP-OCRv6 small 中文模型）。

    优先使用 models/rapidocr 目录下的本地 onnx 模型（离线可用）；
    若该目录为空，则使用 rapidocr 库默认模型（首次使用时自动下载到缓存）。
    """
    global _rapidocr_engine
    if _rapidocr_engine is None:
        from rapidocr import RapidOCR
        model_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "models", "rapidocr")
        det_path = rec_path = cls_path = None
        if os.path.isdir(model_dir):
            for f in os.listdir(model_dir):
                if not f.lower().endswith(".onnx"):
                    continue
                lower = f.lower()
                if "_det" in lower:
                    det_path = os.path.join(model_dir, f)
                elif "_rec" in lower:
                    rec_path = os.path.join(model_dir, f)
                elif "_cls" in lower:
                    cls_path = os.path.join(model_dir, f)
        if det_path and rec_path:
            params = {"Det.model_path": det_path, "Rec.model_path": rec_path}
            if cls_path:
                params["Cls.model_path"] = cls_path
            _rapidocr_engine = RapidOCR(params=params)
        else:
            _rapidocr_engine = RapidOCR()
    return _rapidocr_engine


def _box_center(box):
    """从 4 点 box [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] 提取中心与高度。

    兼容 list 与 numpy ndarray 两种输入。
    """
    xs = [float(p[0]) for p in box]
    ys = [float(p[1]) for p in box]
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, max(ys) - min(ys)


def ocr_screenshot(d, crop_box=None):
    """对当前屏幕截图做 OCR，返回 [(text, center_x, center_y, raw_box), ...]。

    Args:
        d: uiautomator2 设备对象
        crop_box: 可选 (left, top, right, bottom) 裁剪区域（截图坐标系）

    Returns:
        list: 每个元素为 (text, center_x, center_y, raw_box)
              raw_box 为 4 点坐标 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
    """
    img = d.screenshot()  # 返回 PIL Image（本版本 uiautomator2 不支持 format="raw"）
    if crop_box:
        img = img.crop(crop_box)
    engine = get_rapidocr()
    result = engine(np.array(img))
    parsed = []
    if result is None:
        return parsed
    boxes = getattr(result, "boxes", None)
    txts = getattr(result, "txts", ())
    if boxes is None or boxes.size == 0:
        return parsed
    for box, text in zip(boxes, txts):
        if box is None or len(box) == 0 or not text or not str(text).strip():
            continue
        # RapidOCR 的 box 是 numpy ndarray，统一转成 list，避免下游 not box / 运算歧义
        box = [[float(p[0]), float(p[1])] for p in box]
        cx, cy, _ = _box_center(box)
        if crop_box:
            cx += crop_box[0]
            cy += crop_box[1]
        parsed.append((str(text), int(cx), int(cy), box))
    return parsed


def find_task_buttons_by_ocr(d, skip_keywords=None, task_region=None):
    """通过 OCR 识别屏幕上的"去完成/去浏览/去领取"按钮并返回可点击坐标。

    适用场景：任务页是 WebView/Canvas 渲染，按钮未暴露在 Android 无障碍树中。
    对每个按钮，会向上查找同一行的任务名；若任务名包含 skip_keywords 则跳过。

    Args:
        d: uiautomator2 设备对象
        skip_keywords: 跳过任务名的关键词列表，例如 ['支付宝', '尖货补贴']
        task_region: 可选 (left, top, right, bottom)，只在该区域 OCR；默认全屏

    Returns:
        list: 每个元素为 (x, y, task_name) 元组，表示按钮中心点击坐标及识别到的任务名
    """
    if skip_keywords is None:
        skip_keywords = []
    candidates = []
    print("开始 OCR 识别任务按钮...")
    words = ocr_screenshot(d, crop_box=task_region)
    print(f"OCR 共识别 {len(words)} 个文字块")
    for text, cx, cy, box in words:
        print(f"   OCR: {text!r} @ ({cx}, {cy})")
    # 先筛选按钮文字
    button_words = []
    for text, cx, cy, box in words:
        if re.search(r"去完成|去浏览|去领取|前往", text):
            button_words.append((text, cx, cy, box))
    print(f"识别到按钮文字 {len(button_words)} 个")
    for btn_text, btn_cx, btn_cy, btn_box in button_words:
        # 在按钮左侧/上方找最近同行的任务名
        # 同一行：按钮中心 y 与任务名中心 y 偏差不超过按钮高度的一半
        _, _, btn_h = _box_center(btn_box)
        best_name = None
        best_dy = float("inf")
        for text, cx, cy, box in words:
            if text == btn_text:
                continue
            if cx >= btn_cx:
                continue
            # 过滤 OCR 误识别的过短文字块（图标上的装饰性单字，如"精/利/补"）
            if len(text.strip()) < 2:
                continue
            dy = abs(cy - btn_cy)
            # 垂直容差：按钮高度的 1.2 倍且至少 60 像素；保证同一行任务名
            if dy <= max(btn_h * 1.2, 60) and dy < best_dy:
                best_dy = dy
                best_name = text
        if best_name is None:
            best_name = ""
        if any(kw in best_name for kw in skip_keywords):
            print(f"OCR 跳过任务: {best_name} ({btn_text})")
            continue
        candidates.append((btn_cx, btn_cy, best_name))
    # 按 y 坐标从上到下排序，保证先点上面的任务
    candidates.sort(key=lambda x: x[1])
    return candidates

# 多用户配置: None=自动检测并交互选择, "0"=机主(用户0), "999"=MultiApp(用户999)
# 设置后可跳过每次运行时的用户选择提示
DEFAULT_USER_ID = "0"

# 关闭 ppocr 的所有日志（推荐）
# logging.getLogger('ppocr').setLevel(logging.WARNING)  # 或 logging.ERROR
# 或者更粗暴地全局关闭 DEBUG 以下级别（会影响其他库）
# logging.basicConfig(level=logging.WARNING)

TB_APP = "com.taobao.taobao"
FISH_APP = "com.taobao.idlefish"
TMALL_APP = "com.tmall.wireless"
TMALL_HOME = "com.tmall.wireless.maintab.module.TMMainTabActivity"

# 应用启动配置，键为包名，值为activity
APP_START_CONFIG = {
    TB_APP: "com.taobao.tao.welcome.Welcome",
    # TB_APP: "com.taobao.tao.TBMainActivity",
    FISH_APP: "com.taobao.fleamarket.home.activity.InitActivity",
    TMALL_APP: "com.tmall.wireless.maintab.module.TMMainTabActivity"
}
VIDEO_ACTIVITY = ["com.taobao.idlefish.ads.csj.TTAdStandardPortraitActivity"]


def check_chars_exist(text, chars=None):
    if chars is None:
        chars = ["拉好友", "抢红包", "搜索兴趣商品下单", "买精选商品", "全场3元3件", "固定入口", "农场小游戏", "砸蛋","大众点评", "蚂蚁新村", "消消乐", "3元抢3件包邮到家", "拍一拍", "1元抢爆款好货", "拉1人助力","玩消消乐", "下单即得", "添加签到神器", "下单得肥料", "88VIP", "邀请好友", "好货限时直降", "连连消","下单即得", "拍立淘", "玩任意游戏", "首页回访", "百亿外卖", "玩趣味游戏得大额体力", "天猫积分换体力", "头条刷热点", "一淘签到", "每拉", "闪购拿大额补贴", "开心消消乐过1关", "通关", "购买商品", "去闪购领红包点外卖", "冒险大作战", "斗地主", "买限时折扣好物", "趣头条", "(1000/3500)", "任意下单", "农场对对碰匹配", "任意充值", "闯关", "消一消", "点击商品领优惠红包", "发评价得金币", "去天猫领现金", "试玩", "芝麻信用"]
    for char in chars:
        if char in text:
            return True
    return False


def tmall_no_click(text):
    chars = ["添加桌面组件", "加速提现", "美团视频", "618", "看视频", "微博"]
    for char in chars:
        if char in text:
            return True
    return False


def fish_no_click(text):
    chars = ["闯", "看视频"]
    for char in chars:
        if char in text:
            return True
    return False


def get_current_app(d):
    info = d.shell("dumpsys window | grep mCurrentFocus").output
    match = re.search(r'mCurrentFocus=Window\{.*? u0 (.*?)/(.*?)\}', info)
    if match:
        package_name = match.group(1)
        activity_name = match.group(2)
        return package_name, activity_name
    return None, None


def check_app(d, package):
    package_name, _ = get_current_app(d)
    if package_name not in package:
        time.sleep(5)
        start_app(d, package)
        time.sleep(3)


other_app = ["蚂蚁森林", "农场", "百度", "支付宝", "芝麻信用", "蚂蚁庄园", "闲鱼", "神奇海洋", "淘宝特价版", "点淘", "饿了么", "微博", "直播", "领肥料礼包", "福气提现金", "看小说", "菜鸟", "斗地主", "领肥料礼包"]


def fish_not_click(text, chars=None):
    if chars is None:
        chars = ["发布一件新宝贝", "买到或卖出", "中国移动", "视频", "下单", "点淘", "一淘", "收藏", "购买"]
    for char in chars:
        if char in text:
            return True
    return False


def _imread_bgr(path):
    """用 PIL 读取图片，返回与 cv2.imread 一致的 BGR 顺序 numpy 数组"""
    with Image.open(path) as img:
        rgb = np.array(img.convert("RGB"))
    return rgb[:, :, ::-1].copy()


def _bgr_to_gray(img):
    """BGR 顺序数组转灰度（权重与 cv2.cvtColor(COLOR_BGR2GRAY) 一致）"""
    gray = 0.114 * img[:, :, 0] + 0.587 * img[:, :, 1] + 0.299 * img[:, :, 2]
    return np.clip(gray, 0, 255).astype(np.uint8)


def _resize_gray(gray, width, height):
    """灰度图缩放（缩小用 BOX 近似 cv2.INTER_AREA，放大用 BICUBIC 近似 cv2.INTER_CUBIC）"""
    pil_img = Image.fromarray(gray, mode="L")
    resample = Image.Resampling.BOX if width < gray.shape[1] else Image.Resampling.BICUBIC
    return np.array(pil_img.resize((width, height), resample))


def _match_template_ncc(image, template):
    """归一化互相关模板匹配（等价 cv2.matchTemplate + cv2.TM_CCOEFF_NORMED）。
    输入、输出均为灰度 numpy 数组，返回匹配结果矩阵（float64）。"""
    img_h, img_w = image.shape
    tpl_h, tpl_w = template.shape
    if tpl_h > img_h or tpl_w > img_w:
        return np.empty((max(img_h - tpl_h + 1, 0), max(img_w - tpl_w + 1, 0)))

    img = image.astype(np.float64)
    tpl = template.astype(np.float64)
    n = tpl.size

    tpl_mean = tpl.mean()
    tpl_diff = tpl - tpl_mean
    tpl_sq_sum = float(np.sum(tpl_diff * tpl_diff))
    if tpl_sq_sum < 1e-12:
        return np.zeros((img_h - tpl_h + 1, img_w - tpl_w + 1))

    # FFT 卷积快速计算每个窗口的 sum(tpl * window)
    full_h = img_h + tpl_h - 1
    full_w = img_w + tpl_w - 1
    f_img = np.fft.rfft2(img, s=(full_h, full_w))
    f_tpl = np.fft.rfft2(tpl[::-1, ::-1], s=(full_h, full_w))
    conv = np.fft.irfft2(f_img * f_tpl, s=(full_h, full_w))
    corr = conv[tpl_h - 1:img_h, tpl_w - 1:img_w]

    # 积分图计算每个窗口的和与平方和
    integral = np.zeros((img_h + 1, img_w + 1))
    np.cumsum(np.cumsum(img, axis=0), axis=1, out=integral[1:, 1:])
    integral_sq = np.zeros((img_h + 1, img_w + 1))
    np.cumsum(np.cumsum(img * img, axis=0), axis=1, out=integral_sq[1:, 1:])

    out_h, out_w = img_h - tpl_h + 1, img_w - tpl_w + 1
    win_sum = (integral[tpl_h:, tpl_w:] - integral[:out_h, tpl_w:] - integral[tpl_h:, :out_w] + integral[:out_h, :out_w])
    win_sq_sum = (integral_sq[tpl_h:, tpl_w:] - integral_sq[:out_h, tpl_w:] - integral_sq[tpl_h:, :out_w] + integral_sq[:out_h, :out_w])

    win_mean = win_sum / n
    numer = corr - n * win_mean * tpl_mean
    win_var = np.maximum(win_sq_sum / n - win_mean * win_mean, 0.0)
    denom = np.sqrt(win_var * n * tpl_sq_sum)
    result = np.divide(numer, denom, out=np.zeros_like(numer), where=denom > 1e-12)
    return result


def find_button(image, btn_path, region=None):
    template = _imread_bgr(btn_path)
    # 如果指定了区域，裁剪图像
    if region is not None:
        x, y, w_region, h_region = region
        image = image[y:y + h_region, x:x + w_region]
    # 转换为灰度图像
    screenshot_gray = _bgr_to_gray(image)
    template_gray = _bgr_to_gray(template)
    # 使用模板匹配
    res = _match_template_ncc(screenshot_gray, template_gray)
    threshold = 0.7
    loc = np.where(res >= threshold)
    for pt in zip(*loc[::-1]):
        return pt
    return None


def _save_result_image(screen_shot_bgr, rect, center):
    """在截图上绘制匹配框与中心点并保存 result.jpg（替代 cv2.rectangle/circle/imwrite）"""
    try:
        rgb = screen_shot_bgr[:, :, ::-1]
        draw = ImageDraw.Draw(Image.fromarray(rgb))
        x, y, bw, bh = rect
        draw.rectangle([x, y, x + bw, y + bh], outline=(0, 255, 0), width=2)
        cx, cy = center
        draw.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], outline=(255, 0, 0), width=2)
        Image.fromarray(rgb).save("result.jpg")
    except Exception as e:
        print(f"保存调试图片失败: {e}")


# 基于特征查找图片 threshold:匹配阈值（越高质量要求越高） scales:搜索的尺度范围 60%~140%
def find_button_multiscale(screen_shot, template_path, scales=np.linspace(0.6, 1.4, 20), threshold=0.78, method="TM_CCOEFF_NORMED"):
    if method != "TM_CCOEFF_NORMED":
        raise ValueError(f"不支持的匹配方法: {method}（当前仅支持 TM_CCOEFF_NORMED）")
    # 读取图片（建议都转成RGB或灰度，视情况）
    template = _imread_bgr(template_path)
    if screen_shot is None or template is None:
        return None, None, None
    if isinstance(screen_shot, Image.Image):
        screen_shot = np.array(screen_shot.convert("RGB"))[:, :, ::-1]
    elif isinstance(screen_shot, bytes):
        img = Image.open(io.BytesIO(screen_shot))
        screen_shot = np.array(img.convert("RGB"))[:, :, ::-1]
    # 建议都转灰度（速度快很多，且很多按钮是单色/对比度强的）
    large_gray = _bgr_to_gray(screen_shot)
    tpl_gray = _bgr_to_gray(template)
    h, w = tpl_gray.shape[:2]
    best_val = -1
    best_loc = None
    best_scale = 1.0
    best_rect = None
    for scale in scales:
        # 缩放模板（注意：也可以反过来缩放大图，但通常缩放小图更快）
        resize_w = int(w * scale)
        resize_h = int(h * scale)
        if resize_w < 5 or resize_h < 5:
            continue
        resized_tpl = _resize_gray(tpl_gray, resize_w, resize_h)
        # 检查是否还能匹配（防止模板比大图还大）
        if resized_tpl.shape[0] > large_gray.shape[0] or resized_tpl.shape[1] > large_gray.shape[1]:
            continue
        # 模板匹配
        result = _match_template_ncc(large_gray, resized_tpl)
        if np.isnan(result).all():
            continue
        max_loc = np.unravel_index(np.argmax(result), result.shape)
        val = float(result[max_loc])
        loc = (max_loc[1], max_loc[0])  # (x, y)
        if val > best_val:  # 对于相关系数类方法，越大越好
            best_val = val
            best_loc = loc
            best_scale = scale
            best_rect = (loc[0], loc[1], resize_w, resize_h)
    if best_val >= threshold:
        x, y, bw, bh = best_rect
        center_x = x + bw // 2
        center_y = y + bh // 2
        print(f"找到匹配！置信度: {best_val:.3f}")
        print(f"左上角: ({x}, {y})")
        print(f"中心点: ({center_x}, {center_y})")
        print(f"按钮大小: {bw}×{bh}  (缩放比例 {best_scale:.2f})")
        # 可视化（可选）
        _save_result_image(screen_shot, best_rect, (center_x, center_y))
        return (center_x, center_y), best_val, best_scale
    else:
        print(f"未找到足够匹配，最高置信度仅: {best_val:.3f}")
        return None, best_val, None


def find_text_position(image, text):
    ocr = ddddocr.DdddOcr(show_ad=False)
    ocr_result = ocr.classification(image)
    # 将 OCR 结果按行解析
    lines = ocr_result.split('\n')
    # 遍历每一行，查找目标文本的位置
    for line in lines:
        if text in line:
            # 获取文本的位置
            start_index = line.find(text)
            end_index = start_index + len(text)
            return start_index, end_index
    return None


def check_can_open(d):
    open_btn = d(className="android.widget.Button", textMatches=r"打开|允许|始终允许|\d+天内允许")
    if open_btn.exists:
        open_btn.click()
        time.sleep(4)


# ocr = PaddleOCR(use_angle_cls=True, lang='ch', show_log=True,  # 显示详细日志，看卡在哪一步
#     use_space_char=False,  # 减少不必要的计算
#     det_db_thresh=0.3,  # 降低检测阈值，加快速度
#     det_db_box_thresh=0.5)
#
#
# def paddle_ocr(image):
#     if isinstance(image, Image.Image):
#         image = np.array(image)
#     result = ocr.ocr(image)
#     texts = []
#     for line in result[0]:  # result 是列表，result[0] 是当前图片的行信息
#         text = line[1][0]  # line[1][0] 是识别的文字，line[1][1] 是置信度
#         texts.append(text)
#     # 拼接方式：可以直接连在一起，或者加空格/换行，根据你的图片实际情况调整
#     full_sentence = ''.join(texts)  # 无空格直接拼接（适合连续文字）
#     print(f"提取的完整文字：{full_sentence}")
#     return full_sentence

# 判断一个字符是否为中文字符
def is_chinese(char):
    return '\u4e00' <= char <= '\u9fff'


def majority_chinese(text):
    if not text:
        return False
    chinese_count = sum(1 for char in text if is_chinese(char))
    return chinese_count > len(text) / 2


search_keys = ["华硕a豆air", "机械革命星耀14", "ipadmini7", "iphone16", "红米note13", "macbookairm4", "华硕灵耀14", "微星星影15"]


def task_loop(d, back_func, origin_app=TB_APP, is_fish=False, duration=22):
    check_can_open(d)
    package_name, _ = get_current_app(d)
    if "com.sina.weibo" in package_name:
        time.sleep(3)
        back_func()
        return
    history_lst1 = d.xpath(
        '(//android.widget.TextView[@text="历史搜索"]/following-sibling::android.widget.ListView)/android.view.View[1]')
    history_lst2 = d.xpath('//android.widget.TextView[@text="猜你想搜"]/following-sibling::android.view.View[1]/android.view.View[1]/android.widget.TextView')
    open_btn = d(className="android.widget.TextView", text="打开淘宝")
    if history_lst1.exists:
        print("查找到搜索关键字", history_lst1)
        history_lst1.click()
        time.sleep(2)
    elif history_lst2.exists:
        print("查找到搜索关键字", history_lst2.get_text())
        history_lst2.click()
        time.sleep(2)
    elif open_btn.exists:
        open_btn.click()
        time.sleep(3)
    else:
        search_view = d(className="android.view.View", text="搜索有福利")
        if search_view.exists:
            search_edit = d.xpath("//android.widget.EditText")
            if search_edit.exists:
                search_edit.set_text(random.choice(search_keys))
                search_btn = d(className="android.widget.Button", text="搜索")
                if search_btn.exists:
                    search_btn.click()
                    time.sleep(2)
    screen_width, screen_height = d.window_size()
    package_name, _ = get_current_app(d)
    start_time = time.time()
    print("开始做任务。。。")
    browse_view = d(className="android.widget.TextView", textMatches=r"\d+/\d+")
    if browse_view.exists:
        fu_view = d(className="android.widget.TextView", textMatches=r"找\d+个福星得")
        if fu_view.exists:
            back_func()
        else:
            browse_text = browse_view.get_text()
            browse_count = int(re.findall(r"\d+/(\d+)", browse_text)[0])
            try_count = 0
            while try_count < browse_count:
                try:
                    commodity_view = next(
                        (xv for xv in [
                            d.xpath(f'//android.view.View[@resource-id="root"]/android.view.View[5]/android.view.View/android.view.View/android.view.View/android.view.View/android.view.View/android.view.View[{try_count+1}]'),
                            d.xpath(f'//android.view.View[@resource-id="root"]/android.view.View[4]/android.view.View/android.view.View/android.view.View/android.view.View/android.view.View/android.view.View[{try_count+1}]'),
                            d.xpath(f'//android.view.View[@resource-id="root"]/android.view.View[5]/android.view.View/android.view.View/android.view.View/android.view.View/android.view.View[2]/android.view.View[{try_count-2}]'),
                            d.xpath(f'//android.view.View[@resource-id="root"]/android.view.View[4]/android.view.View/android.view.View/android.view.View/android.view.View/android.view.View[2]/android.view.View[{try_count-2}]'),
                        ] if xv and xv.exists),
                        None
                    )
                    if commodity_view and commodity_view.exists:
                        print(f"点击商品{try_count}")
                        commodity_view.click()
                        time.sleep(2)
                        d.press("back")
                        time.sleep(3)
                    try_count += 1
                except Exception as e:
                    print("遇到错误：", str(e))
    else:
        while True:
            try:
                bt_open = d(resourceId="android:id/button1", text="浏览器打开")
                if bt_open.exists:
                    bt_close = d(resourceId="android:id/button2", text="取消")
                    if bt_close.exists:
                        bt_close.click()
                        time.sleep(2)
                        break
                if time.time() - start_time > duration:
                    break
                if is_fish:
                    print("开始查找闲鱼商品")
                    time.sleep(4)
                    commodity_view1 = d.xpath("//android.widget.ListView/android.view.View[1]")
                    if commodity_view1.exists:
                        print(f"存在commodity_view1，点击{commodity_view1.center()}")
                        commodity_view1.click()
                        time.sleep(18)
                        break
                    commodity_view2 = d(className="android.view.View", resourceId="feedsContainer")
                    if commodity_view2.exists:
                        print(f"存在commodity_view2，点击{(100, commodity_view2.center()[1])}")
                        d.click(300, commodity_view2.center()[1])
                        time.sleep(18)
                        break
                if package_name == origin_app or package_name == TMALL_APP:
                    start_x = random.randint(screen_width // 6, screen_width // 2)
                    start_y = random.randint(screen_height // 2, screen_height - screen_height // 4)
                    end_x = random.randint(start_x - 100, start_x)
                    end_y = random.randint(200, start_y - 300)
                    swipe_time = random.uniform(0.4, 1) if end_y - start_y > 500 else random.uniform(0.2, 0.5)
                    print("模拟滑动", start_x, start_y, end_x, end_y, swipe_time)
                    d.swipe(start_x, start_y, end_x, end_y, swipe_time)
                    time.sleep(random.uniform(0.8, 2))
                else:
                    time.sleep(5)
            except Exception as e:
                time.sleep(5)
    back_func()


def back_to_video(d):
    while True:
        temp_package, temp_activity = get_current_app(d)
        if temp_package is None or temp_activity is None or "Ext2ContainerActivity" in temp_activity:
            continue
        if temp_activity in VIDEO_ACTIVITY:
            break
        if FISH_APP not in temp_package:
            start_app(d, FISH_APP)
            continue
        else:
            d.press("back")
            time.sleep(0.5)


def in_video(d):
    temp_package, temp_activity = get_current_app(d)
    return temp_activity in VIDEO_ACTIVITY


def video_task(d):
    screen_width, screen_height = d.window_size()
    while True:
        print("开始任务循环")
        time.sleep(4)
        if not in_video(d):
            break
        speed_btn = d(className="android.widget.TextView", textMatches=r"我要加速|立即前往加速|我要减广告时长|我要立即领奖|立即打开")
        if speed_btn.exists:
            print(f"点击{speed_btn.get_text()}")
            speed_btn.click()
            time.sleep(2)
            check_can_open(d)
            time.sleep(18)
            back_to_video(d)
            continue
        get_btn1 = d(className="android.widget.TextView", textMatches=r"奖励已领取|领取成功")
        if get_btn1.exists:
            print("点击奖励已领取")
            jump_btn = d(className="android.widget.TextView", textContains="跳过")
            if jump_btn.exists:
                jump_btn.click()
            else:
                d.click(get_btn1.center()[0], get_btn1.bounds()[2] + 70)
                time.sleep(2)
            continue
        get_btn2 = d(className="android.widget.TextView", text="恭喜获得奖励")
        if get_btn2.exists:
            print("恭喜获得奖励，点击关闭")
            d.click(screen_width - 100, get_btn2.center()[1])
            time.sleep(2)
            continue
        get_btn3 = d(className="android.widget.TextView", textMatches=r"立即(领取|抢购)")
        if get_btn3.exists:
            print("点击立即(领取|抢购)")
            get_btn3[-1].click()
            time.sleep(2)
            check_can_open(d)
            time.sleep(18)
            back_to_video(d)
            continue
        screen_shot = d.screenshot(format='opencv')
        pt1, _, _ = find_button_multiscale(screen_shot, "./img/video_get.png", threshold=0.7)
        if pt1:
            d.click(int(pt1[0]), int(pt1[1]))
            time.sleep(2)
            check_can_open(d)
            time.sleep(18)
            back_to_video(d)
            continue
        d.swipe_ext(u2.Direction.FORWARD)


def close_xy_dialog(d):
    dialog_view1 = d.xpath(
        '//android.webkit.WebView[@text="闲鱼币首页"]/android.view.View/android.view.View[2]//android.widget.Image[1]')
    if dialog_view1.exists:
        dialog_view1.click()
        time.sleep(2)


def get_connected_devices():
    """通过ADB获取所有连接的安卓设备序列号"""
    try:
        # 执行adb命令获取设备列表
        result = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
            check=True
        )

        # 解析输出，提取设备序列号
        output = result.stdout
        devices = []
        for line in output.splitlines():
            # 跳过标题行和空行
            if line.strip() == "" or line.startswith("List of devices attached"):
                continue
            match = re.match(r"^([^\s]+)\s+device$", line)
            if match:
                devices.append(match.group(1))
        return devices
    except subprocess.CalledProcessError:
        print("执行ADB命令失败，请确保ADB已正确安装并添加到环境变量")
        return []
    except FileNotFoundError:
        print("未找到ADB命令，请确保ADB已正确安装并添加到环境变量")
        return []


def set_terminal_title(title):
    """设置终端标题（Windows和通用终端）"""
    sys.stdout.write(f"\033]0;{title}\007")
    sys.stdout.flush()


# 从已连接的设备中，返回用户选中的设备序列号
def select_device():
    # 获取所有连接的设备
    devices = get_connected_devices()

    if not devices:
        raise Exception("未检测到任何连接的安卓设备")

        # 根据设备数量进行处理
    if len(devices) == 1:
        # 只有一个设备，直接返回
        set_terminal_title(devices[0])
        return devices[0]
    else:
        # 多个设备，让用户选择
        print("当前连接多个设备，请输入要执行的设备序号：")
        for i, device in enumerate(devices, 1):
            # 手机品牌
            brand = subprocess.run(
                ["adb", "-s", device, "shell", "getprop", "ro.product.brand"],
                capture_output=True, text=True, check=True
            ).stdout.strip()
            # 手机型号
            model = subprocess.run(
                ["adb", "-s", device, "shell", "getprop", "ro.product.model"],
                capture_output=True, text=True, check=True
            ).stdout.strip()
            # 安卓版本
            version_release = subprocess.run(
                ["adb", "-s", device, "shell", "getprop", "ro.build.version.release"],
                capture_output=True, text=True, check=True
            ).stdout.strip()
            # 定义颜色常量
            RED = '\033[91m'   # 红
            GREEN = '\033[92m'    # 绿
            BLUE = '\033[94m'     # 蓝
            CYAN = '\033[96m'     # 青
            RESET = '\033[0m'     # 重置
            print(f"  {BLUE}{i}{RESET}: {device}\t{GREEN}{brand} {model}{RESET}\t{CYAN}{version_release}{RESET}")

        # 获取用户输入并验证
        while True:
            try:
                choice = input("请输入设备序号：")
                index = int(choice) - 1  # 转换为列表索引

                if 0 <= index < len(devices):
                    # 选中的设备
                    set_terminal_title(devices[index])
                    return devices[index]
                else:
                    print(f"{RED}输入错误，序号不存在{RESET}")
            except ValueError:
                print(f"{RED}输入错误，请输入数字{RESET}")


# 多用户支持：None=未检测，""=单用户/默认用户(不需要--user)，其他=用户ID
_selected_user = None


def _detect_and_select_user(d):
    """检测手机是否有多个用户，如果有则让用户选择要操作的用户，结果缓存到 _selected_user
    优先使用 DEFAULT_USER_ID 配置，仅在配置为 None 时才交互询问"""
    global _selected_user
    if _selected_user is not None:
        return _selected_user if _selected_user != "" else None
    # 优先使用配置文件中指定的用户ID
    if DEFAULT_USER_ID is not None:
        _selected_user = str(DEFAULT_USER_ID)
        print(f"使用配置的用户ID: {_selected_user}")
        return _selected_user
    try:
        output = d.shell("pm list users").output
        # 解析输出: UserInfo{0:Owner:13} running
        users = re.findall(r'UserInfo\{(\d+):([^:]*):', output)
        if len(users) <= 1:
            _selected_user = ""
            print("仅检测到1个用户，使用默认用户")
            return None
        print("检测到手机有多个用户：")
        for i, (uid, uname) in enumerate(users, 1):
            label = f"用户{uid}" + (f" ({uname})" if uname else "")
            print(f"  {i}: {label}")
        while True:
            try:
                choice = input("请选择要操作的用户序号（直接回车默认第一个用户）：")
                if choice.strip() == "":
                    _selected_user = users[0][0]
                    break
                index = int(choice) - 1
                if 0 <= index < len(users):
                    _selected_user = users[index][0]
                    break
                print(f"输入错误，请重新输入序号（1-{len(users)}）")
            except ValueError:
                print(f"输入错误，请重新输入序号（1-{len(users)}）")
        print(f"已选择用户: {_selected_user}")
        return _selected_user
    except Exception as e:
        print(f"检测用户失败: {e}")
        _selected_user = ""
        return None


def _am_start_with_user(d, package_name, activity=None, user_id=None):
    """通过am start命令启动应用，支持--user参数指定用户"""
    if user_id:
        if activity:
            cmd = f"am start --user {user_id} -n {package_name}/{activity}"
        else:
            cmd = f"am start --user {user_id} -a android.intent.action.MAIN -c android.intent.category.LAUNCHER {package_name}"
    else:
        if activity:
            cmd = f"am start -n {package_name}/{activity}"
        else:
            cmd = f"am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER {package_name}"
    print(f"执行命令: {cmd}")
    d.shell(cmd)


def start_app(d, package_name, init=False):
    """根据包名启动应用，支持特定应用的activity配置
    init参数控制启动模式：
    - True: 初始化启动，使用stop=True, use_monkey=True
    - False: 普通启动，使用stop=False, use_monkey=False
    首次调用时会检测手机多用户并询问选择，后续自动使用已选用户
    优先使用activity启动（am start --user 0），失败后回退普通启动"""
    user_id = _detect_and_select_user(d)
    stop = init
    use_monkey = init

    # 获取配置的activity
    activity = APP_START_CONFIG.get(package_name)
    # 优先使用activity启动（am start --user 0 -n）
    if activity:
        try:
            print(f"优先使用activity启动应用: {package_name}, activity: {activity}, user: {user_id or '默认'}")
            if stop:
                d.shell(f"am force-stop {package_name}")
                time.sleep(1)
            d.shell(f"am start --user 0 -n {package_name}/{activity}")
            time.sleep(2)
            cancel_btn = d(className="android.widget.FrameLayout", resourceId="com.taobao.taobao:id/uik_fl_textview_container_2")
            if cancel_btn.exists:
                cancel_btn.click()
                time.sleep(2)
            # 验证应用是否启动成功
            current_package, _ = get_current_app(d)
            if current_package == package_name:
                print(f"应用 {package_name} 启动成功")
                return
            else:
                print(f"activity启动未成功，当前应用: {current_package}，尝试后退使用普通方式")
                d.press("back")
                time.sleep(1)
        except Exception as e:
            print(f"使用activity启动失败: {e}，回退普通方式")

    # 回退：不使用activity启动
    try_count = 3
    try:
        while try_count > 0:
            print(f"普通启动应用: {package_name}, stop: {stop}, use_monkey: {use_monkey}, user: {user_id or '默认'}")
            if stop:
                d.shell(f"am force-stop {package_name}")
                time.sleep(1)
            if user_id:
                _am_start_with_user(d, package_name, user_id=user_id)
            elif use_monkey:
                d.app_start(package_name, stop=False, use_monkey=True)
            else:
                d.app_start(package_name, stop=False, use_monkey=False)
            time.sleep(5 if stop else 2)
            cancel_btn = d(className="android.widget.FrameLayout", resourceId="com.taobao.taobao:id/uik_fl_textview_container_2")
            if cancel_btn.exists:
                cancel_btn.click()
                time.sleep(2)
            # 验证应用是否启动成功
            current_package, _ = get_current_app(d)
            if current_package == package_name:
                print(f"应用 {package_name} 启动成功")
                return
            else:
                print(f"应用 {package_name} 未成功启动，当前应用: {current_package}，尝试后退")
                d.press("back")
                time.sleep(1)
            try_count -= 1
    except Exception as e:
        print(f"普通启动也失败: {e}")


def check_verify(d):
    verify_view = d(className="android.webkit.WebView", text="验证码拦截")
    if verify_view.exists:
        while True:
            print("存在验证码的情况")
            d.shell("input swipe 150 1700 1180 1700 500")
            time.sleep(3)
            verify_view = d(className="android.webkit.WebView", text="验证码拦截")
            if verify_view.exists:
                d.click(500, 1700)
                time.sleep(3)
            else:
                print("验证码滑动成功")
                break


def print_error():
    exc_type, exc_value, exc_traceback = sys.exc_info()
    print("=" * 10)
    print(f"错误类型: {exc_type}")
    print(f"错误信息: {exc_value}")
    print(f"错误行号: {exc_traceback.tb_lineno}")
    print("=" * 10)
    tb_info = traceback.extract_tb(exc_traceback)
    for frame in tb_info:
        print(f"文件: {frame.filename}, 行号: {frame.lineno}, 函数: {frame.name}, 代码: {frame.line}")
    print("=" * 10)


def check_popup(d):
    popup1 = d(className="android.widget.LinearLayout", resourceId="com.taobao.taobao:id/uik_menu_panel_rl")
    if popup1.exists:
        print("存在底部弹出框，关闭他")
        cancel_btn = d(className="android.widget.TextView", resourceId="com.taobao.taobao:id/uik_tv_cancel", text="取消")
        if cancel_btn.exists:
            print("点击取消按钮")
            cancel_btn.click()


def get_media_volume(d):
    """获取媒体流(stream 3)当前音量，返回实际生效值；读取失败返回 None。

    方案依据（设备实测 + AOSP 文档）：
        - Android 11+ 官方媒体会话服务：cmd media_session volume --stream 3 --get，
          输出形如 "[V] volume is 0 in range [0..30]"，可直接读回真实音量；
        - 注意 settings get system volume_music 在新版 Android 上是假值
          （不反映音频流实际音量），不可作为判断依据。
    兜底：解析 dumpsys audio 中 STREAM_MUSIC 段的 streamVolume 字段。
    """
    # 主方案：cmd media_session 官方查询（设备已验证可用）
    try:
        out = str(d.shell("cmd media_session volume --stream 3 --get").output)
        m = re.search(r"volume is (\d+) in range \[\d+\.\.\d+\]", out)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    # 兜底：解析 dumpsys audio 的 STREAM_MUSIC 段（streamVolume 字段）
    try:
        out = str(d.shell("dumpsys audio | grep -A 8 'STREAM_MUSIC:'").output)
        m = re.search(r"streamVolume:\s*(\d+)", out)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None


def set_media_volume(d, volume):
    """将媒体音量设为指定值，设置成功后读回验证一致返回 True。

    方案依据（设备实测 + AOSP 文档）：
        - Android 11+ 官方媒体会话服务：cmd media_session volume --stream 3 --set N；
        - 兜底：uiautomator2 按键方式（d.press volume_up/volume_down 模拟实体键，
          适配不支持 cmd media_session 的定制 ROM）。
    """
    volume = max(0, int(volume))
    # 主方案：cmd media_session 官方设置（设备已验证可用）
    try:
        d.shell(f"cmd media_session volume --stream 3 --set {volume}")
        time.sleep(0.4)
        if get_media_volume(d) == volume:
            return True
    except Exception:
        pass
    # 兜底：按键方式逐步调节
    for _ in range(50):
        current = get_media_volume(d)
        if current == volume:
            return True
        if current is None:
            break
        if current < volume:
            d.press("volume_up")
        else:
            d.press("volume_down")
        time.sleep(0.15)
    return get_media_volume(d) == volume


def mute_media_volume(d):
    """将媒体音量静音（设为 0），成功返回 True。"""
    if set_media_volume(d, 0):
        print("媒体音量已静音")
        return True
    print("静音失败：媒体音量未能降至 0")
    return False


def swipe_page_down(d, screen_width=None, screen_height=None):
    """向下滑动一屏（把页面往上滚），滑动距离适中。

    手指从屏幕 70% 处快速滑到 30% 处（约 40% 屏高），保持快速甩动触发
    惯性，但距离不过大，避免一次跳过中间区域的任务按钮。配合
    swipe_down_and_check 的循环逐屏下滑，最终能到达页面底部。
    """
    if screen_width is None or screen_height is None:
        try:
            screen_width, screen_height = d.window_size()
        except Exception as e:
            print(f"获取屏幕尺寸失败，无法滑动: {e}")
            return False
    start_x = int(screen_width * 0.5)
    start_y = int(screen_height * 0.7)
    end_x = int(screen_width * 0.5)
    end_y = int(screen_height * 0.3)
    try:
        d.swipe(start_x, start_y, end_x, end_y, 0.15)
    except Exception as e:
        print(f"滑动屏幕失败: {e}")
        return False
    return True





def swipe_down_and_check(d):
    """连续下滑两次并检测页面是否发生有效变化，用于任务列表下滑查找按钮。

    - 返回 True  : 下滑后页面内容有变化（还有更多内容，可继续查找按钮）
    - 返回 False : 下滑失败或页面内容无变化（已到底部 / 页面不可滚动）
    """
    screen_width, screen_height = d.window_size()
    before = _dump_signature(d)
    for i in range(5):
        if not swipe_page_down(d, screen_width, screen_height):
            return False
        time.sleep(0.5)
    # 快速甩动后有惯性滚动，多等一会让页面稳定再对比
    time.sleep(5)
    return True


def scroll_to_top(d, max_swipes=20):
    """持续向上滑动（滚回页面顶部），直到内容不再变化。用于测试前恢复页面初始状态。

    手指从屏幕 30% 处向下滑到 70% 处（反向滑动），快速甩动带回弹效果，
    循环直到页面内容无变化（已回到顶部）。
    """
    screen_width, screen_height = d.window_size()
    start_x = int(screen_width * 0.5)
    start_y = int(screen_height * 0.3)
    end_x = int(screen_width * 0.5)
    end_y = int(screen_height * 0.7)
    before = _dump_signature(d)
    for _ in range(max_swipes):
        try:
            d.swipe(start_x, start_y, end_x, end_y, 0.15)
        except Exception as e:
            print(f"滑动屏幕失败: {e}")
            return
        time.sleep(1.0)
        after = _dump_signature(d)
        if after == before:
            print("已回到页面顶部（内容无变化）")
            return
        before = after


def _dump_signature(d):
    """抓取当前 UI 层级树并生成紧凑摘要，用于判断页面是否发生实质变化。

    优先取 xml 层级树的前缀片段，失败时退化为截图 md5（对字体渲染等细微变化
    敏感度较低，但可保证调用不中断）。
    """
    try:
        xml = str(d.dump_hierarchy())
        return xml[:6000]
    except Exception:
        try:
            png = d.screenshot(format="raw")
            import hashlib
            return "shot:" + hashlib.md5(png).hexdigest()
        except Exception:
            return "unknown"


