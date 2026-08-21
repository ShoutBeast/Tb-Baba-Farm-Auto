import time

import uiautomator2 as u2

from utils import (
    APP_START_CONFIG,
    TB_APP,
    check_chars_exist,
    check_popup,
    check_verify,
    find_task_buttons_by_ocr,
    get_current_app,
    mute_media_volume,
    ocr_screenshot,
    print_error,
    select_device,
    start_app,
    swipe_down_and_check,
    task_loop,
)

skip_keywords = [
    '尖货补贴',
    '淘宝特价',
    '买限时',
    '支付宝',
    '快手',
    '邀请',
    '大众点评',
    '蛋仔',
    '微博',
    '闲鱼',
    '补贴',
]

ocr_keywords = [
    '逛精选好物','搜一搜你喜欢的商品','品牌x农场狂补周'
]

unclick_btn = []
have_clicked = {}
is_end = False
error_count = 0
d: u2.Device | None = None
screen_width = 0
screen_height = 0


def check_in_task():
    """检查当前是否处于芭芭农场任务页面。"""
    assert d is not None, "设备尚未连接，请先调用 main()"
    package_name, activity_name = get_current_app(d)
    if package_name != "com.taobao.taobao":
        return False
    if (
        activity_name is not None
        and "com.taobao.themis.container.app.TMSActivity" in activity_name
    ):
        if d(className="android.webkit.WebView", text="芭芭农场").exists:
            if d(className="android.widget.TextView", text="肥料明细").exists:
                return True
            else:
                find_fertilizer_btn()
                return True
    return False


def back_to_task():
    """从任务子页面返回任务列表页面。"""
    assert d is not None, "设备尚未连接，请先调用 main()"
    print("开始返回任务页面")
    while True:
        try:
            temp_package, temp_activity = get_current_app(d)
            if (
                temp_package is None
                or temp_activity is None
                or "Ext2ContainerActivity" in temp_activity
            ):
                continue
            print(f"{temp_package}--{temp_activity}")
            check_popup(d)
            if TB_APP not in temp_package:
                print(f"回到原始APP,{TB_APP}")
                start_app(d, TB_APP)
                jump_btn = d(
                    resourceId="com.taobao.taobao:id/tv_close",
                    text="跳过",
                )
                if jump_btn.exists:
                    jump_btn.click()
                    time.sleep(2)
            else:
                if check_in_task():
                    print("当前是任务列表画面，不能继续返回")
                    break
                else:
                    if APP_START_CONFIG[TB_APP] in temp_activity:
                        print("当前是淘宝首页，进入芭芭农场页面")
                        find_farm_btn()
                        find_fertilizer_btn()
                        break
                    else:
                        close_btn1 = d.xpath(
                            "//android.widget.FrameLayout[@resource-id='com.alipay.multiplatform.phone.xriver_integration:id/frameLayout_rightButton1']"
                            "/android.widget.LinearLayout"
                            "/android.widget.RelativeLayout"
                            "/android.widget.RelativeLayout"
                            "/android.widget.FrameLayout[2]"
                        )
                        if close_btn1.exists:
                            print("点击关闭小程序按钮")
                            close_btn1.click()
                            time.sleep(1)
                            continue
                        close_btn2 = d(
                            className="android.widget.TextView",
                            resourceId="com.taobao.taobao:id/back_home_btn",
                        )
                        if close_btn2.exists:
                            print("点击关闭小程序按钮")
                            close_btn2.click()
                            time.sleep(1)
                            continue
                        cancel_btn = d(
                            className="android.widget.FrameLayout",
                            resourceId="com.taobao.taobao:id/uik_fl_textview_container_2",
                        )
                        if cancel_btn.exists:
                            print("点击下部弹窗的取消按钮")
                            cancel_btn.click()
                            time.sleep(2)
                            continue
                        task_view = d.xpath(
                            '//android.widget.TextView[contains(@text, "限时下单任务")]'
                        )
                        if task_view.exists:
                            close_btn2 = d.xpath(
                                '//android.widget.TextView[contains(@text, "限时下单任务")]'
                                "/preceding-sibling::android.view.View[1]"
                            )
                            if close_btn2.exists:
                                print("点击关闭限时下单任务按钮")
                                close_btn2.click()
                                time.sleep(1)
                                continue
                        print("点击后退")
                        d.press("back")
                        time.sleep(0.3)
        except Exception:
            print_error()
            time.sleep(2)


def find_farm_btn():
    """查找并点击芭芭农场入口按钮，直到进入集肥料页面。"""
    assert d is not None, "设备尚未连接，请先调用 main()"
    print("开始查找芭芭农场按钮")
    while True:
        farm_btn = d(
            className="android.widget.FrameLayout",
            description="芭芭农场",
        )
        if farm_btn.exists(timeout=5):
            farm_btn.click()
            time.sleep(12)
        temp_btn = d(className="android.widget.Button", textContains="集肥料")
        new_ui = d(
            resourceId="game-canvas-fuguo",
            className="android.widget.Image",
        )
        if temp_btn.exists or new_ui.exists:
            break


def find_fertilizer_btn():
    """查找集肥料按钮并进入任务页面。"""
    assert d is not None, "设备尚未连接，请先调用 main()"
    get_btn1 = d(resourceId="_GXX2RN", className="android.widget.Button")
    if get_btn1.exists:
        print("领取肥料")
        get_btn1.click()
        time.sleep(3)
    print("开始查找集肥料按钮...")
    while True:
        fertilize_btn = d(className="android.widget.Button", textContains="集肥料")
        if fertilize_btn.click_exists(timeout=2):
            print("点击集肥料按钮")
            time.sleep(12)
            if check_in_task():
                break
        else:
            new_ui = d(
                resourceId="game-canvas-fuguo",
                className="android.widget.Image",
            )
            if new_ui.exists:
                new_ui_height = new_ui.bounds()[3] - new_ui.bounds()[1]
                d.click(150, new_ui.bounds()[3] - new_ui_height // 4 - 100)
                time.sleep(3)
                print(
                    f"点击靠近的集肥料按钮, {screen_width * 0.7}, "
                    f"{new_ui.bounds()[3] - 50}"
                )
                d.click(screen_width * 0.7, new_ui.bounds()[3] - 50)
                time.sleep(12)
                if check_in_task():
                    break
    print("进入任务页面")


def run_ocr_target_task():
    """下滑任务页面到底部，用 OCR 查找指定关键词的任务并执行。

    流程：
    1. 持续向下滑动，直到任务页面到达最底部；
    2. 用 RapidOCR 识别"去完成/去浏览/去领取"按钮及其任务名，
       优先按按钮-任务名配对结果匹配 ocr_keywords；
    3. 若配对未命中，直接用 OCR 全部文字块做包含匹配
       （兼容任务名被 OCR 拆分/截断为片段的情况）；
    4. 点击目标任务并完成浏览闭环，返回任务页面后重新滑到底部继续查找，
       直到目标任务全部执行过或未再找到为止。
    """
    assert d is not None, "设备尚未连接，请先调用 main()"
    print("====== 开始 OCR 查找指定任务 ======")
    while True:
        # 1. 滑动到任务页面最底部
        print("向下滑动任务页面到最底部...")
        swipe_down_and_check(d)
        print("已到达页面底部，开始 OCR 识别")
        # 2. 查找目标任务按钮
        target = _find_target_task_button()
        if target is None:
            print("未找到指定关键词任务，结束 OCR 查找")
            break
        # 3. 点击目标任务并完成浏览闭环
        x, y, task_name = target
        have_clicked[task_name] = have_clicked.get(task_name, 0) + 1
        print("点击目标任务", task_name)
        d.click(x, y)
        time.sleep(4)
        if "微博" in task_name:
            time.sleep(4)
            back_to_task()
        else:
            task_loop(d, back_to_task)
        back_to_task()


def _find_target_task_button():
    """查找 ocr_keywords 指定的目标任务按钮。

    通道一：按 find_task_buttons_by_ocr 配对的 (x, y, task_name) 匹配；
    通道二：配对未命中时，直接用 OCR 全部文字块做包含匹配，
    再定位任务名同行的按钮。

    返回 (x, y, task_name) 或 None。
    """
    assert d is not None, "设备尚未连接，请先调用 main()"
    # 通道一：按钮-任务名配对结果
    for x, y, task_name in find_task_buttons_by_ocr(
        d, skip_keywords=skip_keywords
    ):
        if not any(kw in task_name for kw in ocr_keywords):
            continue
        if have_clicked.get(task_name, 0) >= 2:
            print(f"任务 {task_name} 已执行过 2 次，跳过")
            continue
        return (x, y, task_name)
    # 通道二：全文字块包含匹配（兼容任务名被拆分/截断）
    return _find_target_by_raw_words()


def _find_target_by_raw_words():
    """直接用 OCR 全部文字块做包含匹配，定位任务名同行右侧的按钮。

    返回 (x, y, task_name) 或 None。
    """
    assert d is not None, "设备尚未连接，请先调用 main()"
    print("OCR 配对未命中，改用全部文字块包含匹配")
    words = ocr_screenshot(d)
    # 1. 找到命中 ocr_keywords 的任务名文字块
    name_block = None
    for text, cx, cy, _ in words:
        if any(kw in text for kw in ocr_keywords):
            name_block = (text, cx, cy)
            break
    if name_block is None:
        return None
    text, cx, cy = name_block
    if have_clicked.get(text, 0) >= 2:
        print(f"任务 {text} 已执行过 2 次，跳过")
        return None
    # 2. 在任务名同一行右侧定位"去完成/去浏览/去领取/前往"按钮
    row_tolerance = max(60, int(screen_height * 0.05))
    for btn_text, btn_cx, btn_cy, _ in words:
        if not any(k in btn_text for k in ("去完成", "去浏览", "去领取", "前往")):
            continue
        if btn_cx <= cx:
            continue
        if abs(btn_cy - cy) > row_tolerance:
            continue
        return (btn_cx, btn_cy, text)
    return None


def setup_watchers():
    """注册全局弹窗/广告自动点击 watcher。"""
    assert d is not None, "设备尚未连接，请先调用 main()"
    d.watcher.when(
        "O1CN012qVB9n1tvZ8ATEQGu_!!6000000005964-2-tps-144-144"
    ).click()
    d.watcher.when(
        xpath="//android.app.Dialog//android.widget.Button[contains(text(), '-tps-')]"
    ).click()
    d.watcher.when(
        xpath="//android.app.Dialog//android.widget.Button[@text='关闭']"
    ).click()
    d.watcher.when(
        xpath="//android.widget.FrameLayout"
        "[@resource-id='com.taobao.taobao:id/poplayer_native_state_center_layout_frame_id']"
        "//android.widget.ImageView[@content-desc='关闭按钮']"
    ).click()
    # d.watcher.when(xpath="//android.widget.TextView[@package='com.eg.android.AlipayGphone']").click()
    d.watcher.when(
        "O1CN01sORayC1hBVsDQRZoO_!!6000000004239-2-tps-426-128.png_"
    ).click()
    d.watcher.when(
        xpath='//android.widget.Button[@text="提醒我明天领"]'
        '/following-sibling::android.widget.Button[1]'
    ).click()
    d.watcher.when("跳过").click()
    d.watcher.when("点击刷新").click()
    d.watcher.when("刷新").click()
    d.watcher.when("点击重试").click()
    d.watcher.when("立即施肥").click()
    # d.watcher.when("关闭").click()
    d.watcher.start()


def main():
    """芭芭农场自动做任务主流程。"""
    global d, screen_width, screen_height

    time1 = time.time()
    selected_device = select_device()
    d = u2.connect(selected_device)
    print(f"已成功连接设备：{selected_device}")
    start_app(d, TB_APP, init=True)
    print("应用启动成功，将媒体音量静音")
    mute_media_volume(d)
    screen_width, screen_height = d.window_size()
    time.sleep(5)
    # https://dl.ncat1.app/

    setup_watchers()
    find_farm_btn()
    find_fertilizer_btn()
    finish_count = 0
    error_count = 0
    while True:
        try:
            print("开始查找按钮")
            check_verify(d)
            time.sleep(4)
            sign_btn = d(className="android.widget.Button", text="去签到")
            if sign_btn.exists:
                sign_btn.click()
                time.sleep(2)
            to_btn = d(
                className="android.widget.Button",
                textMatches="去完成|去浏览",
            )
            if to_btn.exists:
                need_click_view = None
                need_click_index = 0
                task_name = None
                for index in range(len(to_btn)):
                    view = to_btn[index]
                    text_div = view.sibling(
                        className="android.view.View", instance=0
                    ).child(
                        className="android.widget.TextView", instance=0
                    )
                    if text_div.exists:
                        if check_chars_exist(text_div.get_text()):
                            if view not in unclick_btn:
                                unclick_btn.append(view)
                            continue
                        task_name = text_div.get_text()
                        if task_name in have_clicked:
                            if have_clicked[task_name] >= 2:
                                continue
                        need_click_index = index
                        need_click_view = view
                        break
                if need_click_view:
                    assert task_name is not None, "任务名缺失"
                    # skip_keywords = ['尖货补贴', '淘宝特价', '买限时']
                    if any(kw in task_name for kw in skip_keywords):
                        print(f"跳过任务: {task_name}")
                        have_clicked[task_name] = 2
                        continue
                    print("点击按钮", task_name)
                    if have_clicked.get(task_name) is None:
                        have_clicked[task_name] = 1
                    else:
                        have_clicked[task_name] += 1
                    need_click_view.click()
                    time.sleep(4)
                    if "微博" in task_name:
                        time.sleep(4)
                        back_to_task()
                    else:
                        task_loop(d, back_to_task)
                    finish_count += 1
                else:
                    error_count += 1
                    print("未找到可点击按钮", error_count)
                    if error_count >= 2:
                        run_ocr_target_task()
                        break
            else:
                error_count += 1
                print("未找到可点击按钮", error_count)
                back_to_task()
                if error_count >= 2:
                    run_ocr_target_task()
                    break
        except Exception as e:
            print(e)
            back_to_task()
            continue
    d.watcher.remove()
    print(f"共自动化完成{finish_count}个任务")
    d.shell("settings put system accelerometer_rotation 0")
    print("关闭手机自动旋转")
    time2 = time.time()
    minutes, seconds = divmod(int(time2 - time1), 60)  # 同时计算分钟和秒
    print(f"共耗时: {minutes} 分钟 {seconds} 秒")


if __name__ == "__main__":
    main()
