"""
华中农业大学羽毛球场馆预订模块
处理预订页面的场馆选择、日期选择、时段匹配和预订确认
"""
import asyncio
import re
from datetime import datetime, date, timedelta
from pathlib import Path
from playwright.async_api import Page

ROOT = Path(__file__).parent



async def _wait_for_page_ready(page: Page, timeout: int = 30) -> bool:
    """等待页面内容加载完成，如果超时或页面空白则返回 False"""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            # 检查关键元素是否存在
            date_items = await page.query_selector_all('.date-item')
            site_items = await page.query_selector_all('.sites-item')
            if len(date_items) > 0 or len(site_items) > 0:
                return True
        except Exception:
            pass
        await asyncio.sleep(1)
    return False


async def dismiss_notice_dialog(page: Page) -> bool:
    """
    检测并关闭预约页面的须知弹窗。
    进入预约界面时可能弹出须知/公告对话框，需要点击确认后才能操作。
    支持 Element UI dialog、message-box 以及通用弹窗。
    """
    dialog_selectors = [
        '.el-dialog__wrapper:not([style*="display: none"])',
        '.el-message-box__wrapper:not([style*="display: none"])',
        '[class*="dialog"]:not([style*="display: none"])',
    ]

    for sel in dialog_selectors:
        try:
            dialog = await page.query_selector(sel)
            if dialog:
                is_visible = await dialog.is_visible()
                if not is_visible:
                    continue

                text = await dialog.text_content()
                text_lower = text.lower() if text else ""

                notice_keywords = ["须知", "公告", "注意", "提示", "确认", "知道了", "同意", "确定"]
                if not any(kw in text for kw in notice_keywords):
                    continue

                print("[弹窗] 检测到须知弹窗...")

                confirm_selectors = [
                    'button:has-text("知道了")',
                    'button:has-text("确认")',
                    'button:has-text("确定")',
                    'button:has-text("同意")',
                    '.el-dialog__footer button.el-button--primary',
                    '.el-message-box__btns button.el-button--primary',
                    'button.el-button--primary',
                ]
                for btn_sel in confirm_selectors:
                    try:
                        btn = await dialog.query_selector(btn_sel)
                        if btn:
                            btn_text = (await btn.text_content() or "").strip()
                            print(f"[弹窗] 点击: {btn_text}")
                            await btn.click()
                            await asyncio.sleep(2)
                            return True
                    except Exception:
                        continue

                close_btn = await dialog.query_selector('.el-dialog__close, .el-message-box__close, [class*="close"]')
                if close_btn:
                    print("[弹窗] 点击关闭按钮")
                    await close_btn.click()
                    await asyncio.sleep(2)
                    return True

                print("[弹窗] 尝试 Escape 关闭")
                await page.keyboard.press("Escape")
                await asyncio.sleep(2)
                return True
        except Exception as e:
            print(f"[弹窗] 处理异常: {e}")
            continue

    return False


async def navigate_to_venue(page: Page, venue_name: str, reserve_url: str) -> bool:
    """
    导航到目标场馆的预订页面。
    优先恢复已有会话，点击左侧场馆列表中的目标场馆。
    返回 True 表示已到达目标场馆页面。
    """
    current_url = page.url

    if "reserveList" not in current_url and "reserve" not in current_url.lower():
        print(f"[预订] 导航到预订页面: {reserve_url}")
        await page.goto(reserve_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)

    await page.wait_for_load_state("networkidle", timeout=30000)
    await asyncio.sleep(5)

    print(f"[预订] 当前 URL: {page.url[:100]}")

    # 处理须知弹窗（最多尝试3次，因为可能有多个弹窗）
    for _ in range(3):
        dismissed = await dismiss_notice_dialog(page)
        if not dismissed:
            break
        await asyncio.sleep(1)

    try:
        venue_lists = await page.query_selector_all('.list')
        target_list = None
        for lst in venue_lists:
            text = await lst.text_content()
            text = text.strip()
            if venue_name in text:
                cls = await lst.get_attribute("class") or ""
                if "active1" in cls:
                    print(f"[预订] 已在目标场馆: {text}")
                    return True
                target_list = lst
                print(f"[预订] 找到目标场馆: {text}")
                break

        if target_list:
            await target_list.click()
            await asyncio.sleep(3)
            await page.wait_for_selector('.sites-item', state="visible", timeout=10000)
            print("[预订] 场馆切换成功，场地网格已加载")
            return True
    except Exception as e:
        print(f"[预订] 场馆选择异常: {e}")

    sites = await page.query_selector_all('.sites-item')
    if sites:
        print(f"[预订] 找到 {len(sites)} 个场地，已就绪")
        return True

    print("[预订] 未能定位到场地列表，将刷新重试")
    return False


async def _navigate_with_retry(page: Page, venue_name: str, reserve_url: str, max_retries: int = 3) -> bool:
    """带重试的场馆导航，高峰期页面可能加载空白"""
    for attempt in range(max_retries):
        if attempt > 0:
            print(f"[预订] 页面加载重试 {attempt + 1}/{max_retries}...")
            await asyncio.sleep(3)
            try:
                await page.reload(wait_until="domcontentloaded", timeout=60000)
            except Exception:
                await page.goto(reserve_url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(5)

        ok = await _navigate_with_retry(page, venue_name, reserve_url)
        if ok:
            return True

    return False


async def select_date(page: Page, target_date_str: str = None) -> bool:
    """
    点击目标日期标签（默认明天）。
    日期格式: div.date-item, 文本 "周X  05.31"
    active 标签有 class date-item-active, 不可选的有 class disabled
    """
    if target_date_str is None:
        tomorrow = date.today() + timedelta(days=1)
        target_date_str = tomorrow.strftime("%Y-%m-%d")

    print(f"[预订] 目标日期: {target_date_str}")

    try:
        dt = datetime.strptime(target_date_str, "%Y-%m-%d")
        date_dot = f"{dt.month:02d}.{dt.day:02d}"
    except Exception:
        print("[预订] 日期解析失败")
        return False

    date_items = await page.query_selector_all('.date-item:not(.disabled)')
    print(f"[预订] 找到 {len(date_items)} 个可选日期标签")

    for item in date_items:
        raw = await item.text_content(); text = raw.strip().replace('\u00a0', ' ').replace('\xa0', ' ')
        cls = await item.get_attribute("class") or ""
        if "date-item-active" in cls and date_dot in text:
            print(f"[预订] 目标日期已选中: [{text}]")
            return True

        if date_dot in text:
            print(f"[预订] 点击日期: [{text}]")
            await item.click()
            await asyncio.sleep(5)
            try:
                await page.wait_for_selector('.sites-item', state="visible", timeout=30000)
            except Exception:
                pass
            await asyncio.sleep(1)
            print("[预订] 日期选择成功")
            return True

    print(f"[预订] 未找到匹配日期标签: {date_dot}")
    return False


async def discover_page_structure(page: Page) -> dict:
    """保存页面结构和截图，用于调试"""
    print("[发现] 分析页面结构...")
    await page.screenshot(path=str(ROOT / "debug_reserve_full.png"))
    html = await page.content()
    with open(ROOT / "debug_reserve.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("[发现] 页面 HTML 和截图已保存")
    return {}


async def find_available_slots(page: Page, preferred_slots: list) -> list:
    """
    在场地网格中查找匹配 preferred_slots 的可预订时段。
    注意: 需要找到连续两个匹配的一小时时段（每人最多 2 小时）
    """
    available_slots = []

    try:
        await page.wait_for_selector('.sites-item', state="visible", timeout=10000)
    except Exception:
        print("[预订] 场地网格未加载")
        return available_slots

    site_items = await page.query_selector_all('.sites-item')
    print(f"[预订] 扫描 {len(site_items)} 个场地...")

    for site in site_items:
        try:
            court_label = await site.query_selector('i')
            if not court_label:
                continue
            court_name = (await court_label.text_content()).strip()
        except Exception:
            continue

        time_divs = await site.query_selector_all('.time')
        court_available = []

        for td in time_divs:
            try:
                cls = await td.get_attribute("class") or ""
                if "time-disabled" in cls:
                    continue

                time_text = (await td.text_content()).strip()
                match = re.match(r"(\d{2}:\d{2})~(\d{2}:\d{2})", time_text)
                if not match:
                    continue

                start, end = match.group(1), match.group(2)
                court_available.append({
                    "court_name": court_name,
                    "time_text": time_text,
                    "start": start,
                    "end": end,
                    "time_element": td,
                    "court_element": site,
                })
            except Exception:
                continue

        if court_available:
            print(f"[预订] 场地 {court_name} 有 {len(court_available)} 个可用时段")

        for pref in preferred_slots:
            pref_start = pref["start"]
            pref_end = pref["end"]

            h1 = int(pref_start.split(":")[0])
            h2 = int(pref_end.split(":")[0])
            m1 = pref_start.split(":")[1]

            slot1_start = f"{h1:02d}:{m1}"
            slot1_end = f"{h1+1:02d}:{m1}"
            slot2_start = f"{h1+1:02d}:{m1}"
            slot2_end = f"{h2:02d}:{m1}"

            s1 = None
            s2 = None
            for s in court_available:
                if s["start"] == slot1_start and s["end"] == slot1_end:
                    s1 = s
                if s["start"] == slot2_start and s["end"] == slot2_end:
                    s2 = s

            if s1 and s2:
                print(f"[预订] 场地 {court_name} 匹配 {pref_start}-{pref_end}: "
                      f"{s1['time_text']} + {s2['time_text']}")
                available_slots.append({
                    "court_name": court_name,
                    "time_text": f"{pref_start}~{pref_end}",
                    "start": pref_start,
                    "end": pref_end,
                    "time_element": s1["time_element"],
                    "court_element": s1["court_element"],
                    "slot1": s1,
                    "slot2": s2,
                })

    pref_order = {f"{p['start']}-{p['end']}": i
                  for i, p in enumerate(preferred_slots)}
    available_slots.sort(key=lambda s: pref_order.get(
        f"{s['start']}-{s['end']}", 999))

    return available_slots


async def click_slot_and_book(page: Page, slot: dict) -> bool:
    """点击时段并提交预约"""
    try:
        slot1 = slot.get("slot1")
        slot2 = slot.get("slot2")

        if not slot1 or not slot2:
            print("[预订] 缺少时段信息")
            return False

        print(f"[预订] 点击第一个时段: {slot1['time_text']}")
        await slot1["time_element"].click()
        await asyncio.sleep(1)

        print(f"[预订] 点击第二个时段: {slot2['time_text']}")
        await slot2["time_element"].click()
        await asyncio.sleep(1)

        await page.screenshot(path=str(ROOT / "debug_selected_slots.png"))
    except Exception as e:
        print(f"[预订] 点击时段失败: {e}")
        return False

    return await confirm_booking(page)


async def confirm_booking(page: Page) -> bool:
    """
    点击底部预约按钮，处理须知确认对话框，判断是否成功锁定场地。

    流程: 点击预约 -> 确认须知弹窗 -> 检测是否跳转支付页/成功提示
    返回 True 表示场地已锁定，False 表示失败。
    """
    await asyncio.sleep(0.5)

    # 1. 找到预约按钮
    btn_selectors = [
        '.footer-container .btn:not(.btn-disabled)',
        '.btn:not(.btn-disabled):has-text("预约")',
        '.btn-box .btn:not(.btn-disabled)',
        '[class*="footer"] .btn:not(.btn-disabled)',
    ]

    reserve_btn = None
    for sel in btn_selectors:
        try:
            btn = await page.query_selector(sel)
            if btn:
                text = (await btn.text_content() or "").strip()
                if "预约" in text:
                    reserve_btn = btn
                    print(f"[预订] 找到预约按钮: {text}")
                    break
        except Exception:
            continue

    if not reserve_btn:
        print("[预订] 未找到可用的预约按钮")
        await page.screenshot(path=str(ROOT / "debug_no_reserve_btn.png"))
        return False

    await reserve_btn.click()
    await asyncio.sleep(5)

    # 2. 处理须知确认弹窗（与预约按钮点击后弹出）
    dialog_selectors = [
        '.el-dialog__wrapper:not([style*="display: none"])',
        '.el-message-box__wrapper:not([style*="display: none"])',
        '[class*="dialog"]:not([style*="display: none"])',
    ]

    dialog_shown = False
    for sel in dialog_selectors:
        try:
            dialog = await page.query_selector(sel)
            if dialog:
                dialog_shown = True
                break
        except Exception:
            continue

    if dialog_shown:
        confirm_selectors = [
            '.el-dialog__footer button.el-button--primary',
            '.el-message-box__btns button.el-button--primary',
            'button:has-text("确定")',
            'button:has-text("确认")',
            'button:has-text("提交")',
        ]
        for sel in confirm_selectors:
            try:
                btn = await page.query_selector(sel)
                if btn:
                    text = (await btn.text_content() or "").strip()
                    print(f"[预订] 确认须知: {text}")
                    await btn.click()
                    await asyncio.sleep(5)
                    break
            except Exception:
                continue

    # 高峰期可能响应慢，多等一会儿
    await asyncio.sleep(5)
    await page.screenshot(path=str(ROOT / "debug_booking_result.png"))

    # 3. 判断结果 —— 多种成功信号
    success_indicators = [
        # 成功提示消息
        '.el-message--success',
        '.el-message .el-message--success',
        # 页面文本
        'text=预约成功',
        'text=预订成功',
        # URL 跳转到支付/订单页
    ]

    for indicator in success_indicators:
        try:
            el = await page.query_selector(indicator)
            if el:
                print("[预订] 预订成功！场地已锁定。")
                return True
        except Exception:
            continue

    # 检查是否跳转到了支付相关页面
    current_url = page.url
    if "pay" in current_url.lower() or "order" in current_url.lower():
        print(f"[预订] 已跳转支付页面: {current_url[:100]}")
        return True

    # 4. 检测失败信号
    error_indicators = [
        '.el-message--error',
        'text=已被预约',
        'text=预约失败',
        'text=已满',
        'text=不可预约',
    ]
    for indicator in error_indicators:
        try:
            el = await page.query_selector(indicator)
            if el:
                text = (await el.text_content() or "").strip()
                print(f"[预订] 预约失败: {text}")
                return False
        except Exception:
            continue

    # 5. 无法确定 —— 检查是否还在预约页面
    if "reserveList" in current_url:
        print("[预订] 仍在预约页面，可能预约失败")
        return False

    print("[预订] 无法判断结果（请查看截图 debug_booking_result.png）")
    return False


async def reserve_slot(
    page: Page,
    venue_name: str,
    preferred_slots: list,
    reserve_url: str = "",
    max_retries: int = 3,
    retry_interval: int = 5,
):
    """
    主预订流程:
    1. 导航到目标场馆页面
    2. 选择明天的日期
    3. 查找可用时段
    4. 按偏好匹配并预订

    返回: (True, slot_info_dict) 表示成功, False 表示失败
    slot_info_dict 包含 court_name 和 time_text
    """
    ok = await _navigate_with_retry(page, venue_name, reserve_url)
    if not ok:
        print("[预订] 无法定位到目标场馆")
        return False

    for attempt in range(max_retries):
        print(f"\n[预订] === 第 {attempt + 1}/{max_retries} 次尝试 ===")

        if attempt > 0:
            print(f"[预订] 等待 {retry_interval} 秒后重试...")
            await asyncio.sleep(retry_interval)
            await page.reload(wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(5)
            # 再次处理可能出现的须知弹窗
            await dismiss_notice_dialog(page)
            await _navigate_with_retry(page, venue_name, reserve_url)

        await select_date(page)
        if attempt == 0:
            await discover_page_structure(page)
        available = await find_available_slots(page, preferred_slots)

        if not available:
            print("[预订] 未找到匹配的可预订时段")
            # 如果有场地但在首选时段中没有，尝试刷新
            if attempt < max_retries - 1:
                print("[预订] 刷新页面重试...")
            continue

        print(f"[预订] 找到 {len(available)} 个匹配时段")
        matched = available[0]
        print(f"[预订] 最佳匹配: {matched['court_name']} - {matched['time_text']}")

        success = await click_slot_and_book(page, matched)
        if success:
            return True, {
                "court_name": matched["court_name"],
                "time_text": matched["time_text"],
            }

        # 预约失败时（如场地被他人抢先），刷新后继续尝试下一个匹配时段
        if len(available) > 1:
            print(f"[预订] 当前时段预约失败，尝试下一个匹配...")
            remaining = available[1:]
            for alt in remaining:
                print(f"[预订] 尝试备选: {alt['court_name']} - {alt['time_text']}")
                alt_success = await click_slot_and_book(page, alt)
                if alt_success:
                    return True, {
                        "court_name": alt["court_name"],
                        "time_text": alt["time_text"],
                    }
                print("[预订] 备选也失败，刷新重试...")
                await page.reload(wait_until="networkidle")
                await asyncio.sleep(2)
                await dismiss_notice_dialog(page)
                await navigate_to_venue(page, venue_name, reserve_url)
                await select_date(page)
                break  # 跳出备选循环，进入下一次重试

    print("[预订] 所有尝试均失败")
    return False


async def wait_for_booking_open(page: Page, target_time_str: str = "16:00:00") -> None:
    """
    等待到达预订开放时间（每天16:00开放第二天的预订）。
    提前 5 秒开始高频轮询。
    """
    target_h, target_m, target_s = map(int, target_time_str.split(":"))

    while True:
        now = datetime.now()
        target = now.replace(hour=target_h, minute=target_m, second=target_s, microsecond=0)

        if now >= target:
            print("[预订] 预订时间已到！")
            break

        wait_seconds = (target - now).total_seconds()
        if wait_seconds > 30:
            print(f"[预订] 距离开放还有 {wait_seconds:.0f} 秒...")
            await asyncio.sleep(10)
        elif wait_seconds > 5:
            print(f"[预订] 距离开放还有 {wait_seconds:.0f} 秒...")
            await asyncio.sleep(1)
        else:
            await asyncio.sleep(0.1)

    for reload_attempt in range(5):
        try:
            await page.reload(wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(5)
            # 验证页面是否加载成功
            site_items = await page.query_selector_all('.sites-item')
            if len(site_items) > 0:
                print("[预订] 页面已刷新，准备抢场！")
                break
            print(f"[预订] 刷新后页面空白，重试 {reload_attempt + 1}/5...")
        except Exception as e:
            print(f"[预订] 刷新失败 ({e})，重试 {reload_attempt + 1}/5...")
            await asyncio.sleep(3)
    else:
        print("[预订] 多次刷新仍无法加载，继续尝试...")


