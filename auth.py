"""
华中农业大学 CAS 统一认证登录模块
"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright, Page, Browser, BrowserContext

ROOT = Path(__file__).parent


async def launch_browser(headless: bool = False):
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=headless,
        channel="msedge",
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    context = await browser.new_context(
        viewport={"width": 1280, "height": 800},
        locale="zh-CN",
    )
    page = await context.new_page()
    return pw, browser, context, page


async def login(
    student_id: str,
    password: str,
    reserve_url: str,
    headless: bool = False,
) -> tuple:
    """完整登录流程，返回 (browser, page)"""
    pw, browser, context, page = await launch_browser(headless)

    try:
        print("[登录] 访问预订页面...")
        await page.goto(reserve_url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(4)

        url = page.url
        print(f"[登录] 当前 URL: {url[:120]}")

        # ========================================
        # 情况1：直接在 CAS 登录页面
        # ========================================
        if "cas-paas" in url or "cas/login" in url.lower():
            print("[登录] 已在 CAS 登录页面")
            await handle_cas_login(page, student_id, password)

        # ========================================
        # 情况2：在 Vue SPA 主页，有登录对话框
        # ========================================
        elif "#/home" in url or "/home" in url:
            print("[登录] 在 Vue 主页，处理登录对话框...")
            await handle_vue_dialog_and_redirect(page)
            await asyncio.sleep(4)

            # 检查跳转结果
            pages = context.pages
            cas_page = None
            for p in pages:
                if "cas" in p.url.lower():
                    cas_page = p
                    break

            if cas_page:
                page = cas_page
                print(f"[登录] 跳转到 CAS: {page.url[:80]}...")
            elif "cas" not in page.url.lower():
                # 尝试从对话框获取CAS URL并直接跳转
                print("[登录] 未跳转到 CAS，尝试获取URL直接导航...")
                cas_url = await get_cas_url_from_dialog(page)
                if cas_url:
                    await page.goto(cas_url, wait_until="networkidle", timeout=15000)
                    await asyncio.sleep(3)

            await page.screenshot(path=str(ROOT / "debug_cas_arrived.png"))
            await handle_cas_login(page, student_id, password)

        # ========================================
        # 情况3：已经在预订系统中
        # ========================================
        elif "reserveList" in url:
            print("[登录] 已在预订页面，无需登录")
            return browser, page

        else:
            print(f"[登录] 未知状态: {url[:120]}")
            await page.goto(
                "https://cas-paas.hzau.edu.cn/cas/login",
                wait_until="networkidle",
                timeout=15000,
            )
            await asyncio.sleep(3)
            await handle_cas_login(page, student_id, password)

        # 等待登录结果
        print("[登录] 等待登录完成...")
        await asyncio.sleep(5)

        # 检查是否还停留在 CAS 页面
        if "cas" in page.url.lower():
            error = await page.query_selector('.error, .el-message--error, [class*="error"]')
            if error:
                error_text = await error.text_content()
                print(f"[登录] 登录错误: {error_text.strip()}")
                await page.screenshot(path=str(ROOT / "debug_login_error.png"))
                raise Exception(f"登录失败: {error_text.strip()}")

            # 尝试处理验证码
            await handle_captcha_if_needed(page, student_id, password)

        # 确认登录成功
        await asyncio.sleep(3)
        current_url = page.url
        print(f"[登录] 最终 URL: {current_url[:120]}")

        if "zhcg" not in current_url and "cas" in current_url.lower():
            raise Exception("登录未完成，仍停留在 CAS 页面")

        # 导航到预订页面
        if "reserveList" not in current_url:
            print(f"[登录] 导航到预订页面...")
            await page.goto(reserve_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(3)

        await page.screenshot(path=str(ROOT / "debug_after_login.png"))
        print("[登录] 登录完成！")
        return browser, page

    except Exception as e:
        try:
            await page.screenshot(path=str(ROOT / "debug_error.png"))
        except Exception:
            pass
        print(f"[登录] 出错: {e}")
        raise


async def handle_vue_dialog_and_redirect(page: Page):
    """处理 Vue SPA 登录对话框并跳转到 CAS"""
    # 确保校内登录 tab 激活
    try:
        tab = await page.query_selector('.el-tabs__item:has-text("校内登录")')
        if tab:
            await tab.click()
            await asyncio.sleep(0.5)
    except Exception:
        pass

    # 选择校内 radio（用 JS click 避免 span 拦截）
    try:
        radio_inputs = await page.query_selector_all("input[type='radio']")
        for radio in radio_inputs:
            value = await radio.get_attribute("value")
            if value and "authcenter/toLoginPage" in value and "authcenter1" not in value:
                await radio.evaluate("el => el.click()")
                await asyncio.sleep(0.5)
                print("[对话框] 已选择校内登录")
                break
    except Exception as e:
        print(f"[对话框] radio 选择: {e}")

    # 点击"统一身份认证登录"
    try:
        btn = await page.query_selector('button:has-text("统一身份认证登录")')
        if not btn:
            btn = await page.query_selector(".el-button--primary")
        if btn:
            print("[对话框] 点击统一身份认证登录...")
            await btn.click()
            await asyncio.sleep(2)
    except Exception as e:
        print(f"[对话框] 按钮点击: {e}")

    # 检测滑块验证码
    try:
        mask = await page.wait_for_selector(".mask:not([style*='display: none'])", timeout=3000)
        if mask:
            print("[验证码] 检测到滑块验证码，正在处理...")
            await solve_slider(page)
    except Exception:
        print("[验证码] 未检测到滑块验证码")


async def get_cas_url_from_dialog(page: Page) -> str | None:
    """从对话框获取 CAS URL"""
    try:
        radio_inputs = await page.query_selector_all("input[type='radio']")
        for radio in radio_inputs:
            value = await radio.get_attribute("value")
            if value and "authcenter/toLoginPage" in value and "authcenter1" not in value:
                return value
    except Exception:
        pass
    return None


async def handle_cas_login(page: Page, student_id: str, password: str):
    """填写 CAS 登录表单并提交"""
    print("[CAS] 等待登录表单渲染...")
    await asyncio.sleep(2)
    await page.wait_for_load_state("networkidle")

    # CAS 页面使用 Element UI 渲染可见输入框，fm1/fm2 是隐藏的
    # 需要操作可见的 .el-input__inner 输入框，Vue 组件会自动同步到隐藏表单
    username_input = None
    for sel in [
        'input.el-input__inner[type="text"]',
        '.el-form.login-form input[type="text"]',
        'input[type="text"]:not([readonly])',
    ]:
        try:
            el = await page.wait_for_selector(sel, state="visible", timeout=8000)
            if el:
                username_input = el
                placeholder = await el.get_attribute("placeholder") or ""
                print(f"[CAS] 用户名输入框: {sel} (placeholder={placeholder[:30]})")
                break
        except Exception:
            continue

    if not username_input:
        await page.screenshot(path=str(ROOT / "debug_cas_no_form.png"))
        raise Exception("无法定位 CAS 用户名输入框")

    print(f"[CAS] 填写学号: {student_id}")
    await username_input.click()
    await asyncio.sleep(0.2)
    await username_input.fill(str(student_id))
    await asyncio.sleep(0.3)

    # 填写密码
    password_input = None
    for sel in [
        'input.el-input__inner[type="password"]',
        '.el-form.login-form input[type="password"]',
        'input[type="password"]',
    ]:
        try:
            el = await page.wait_for_selector(sel, state="visible", timeout=5000)
            if el:
                password_input = el
                print(f"[CAS] 密码输入框: {sel}")
                break
        except Exception:
            continue

    if not password_input:
        raise Exception("无法定位 CAS 密码输入框")

    print("[CAS] 填写密码...")
    await password_input.click()
    await asyncio.sleep(0.2)
    await password_input.fill(str(password))
    await asyncio.sleep(0.3)

    # 提交登录 - 优先点击可见的登录按钮（触发 Vue 加密和提交流程）
    print("[CAS] 提交登录...")
    btn = await page.query_selector(
        'button.login-btn, '
        'button.el-button--primary:has-text("登录"), '
        'button[type="submit"]'
    )
    if btn:
        text = (await btn.text_content() or "").strip()
        print(f"[CAS] 点击登录按钮: {text}")
        await btn.click()
    else:
        # 回退：直接调用页面自带的登录函数
        print("[CAS] 未找到登录按钮，尝试调用 _passwordLogin()...")
        try:
            await page.evaluate("_passwordLogin()")
        except Exception:
            await password_input.press("Enter")

    print("[CAS] 已提交登录表单")


async def solve_slider(page: Page):
    """解决滑块验证码"""
    import random
    slider = await page.query_selector(".verify-move-block")
    if not slider:
        return

    box = await slider.bounding_box()
    if not box:
        return

    start_x = box["x"] + box["width"] / 2
    start_y = box["y"] + box["height"] / 2
    distance = random.randint(160, 220)

    # 生成人类拖动轨迹
    track = []
    current = 0
    v = 0
    while current < distance * 0.6:
        v += random.uniform(2, 5)
        current += v
        track.append({"x": min(current, distance), "y": random.uniform(-3, 3)})
    while current < distance:
        v -= random.uniform(1.5, 3)
        if v <= 0:
            v = random.uniform(0.5, 1.5)
        current += v
        if current < distance:
            track.append({"x": min(current, distance), "y": random.uniform(-2, 2)})
    track.append({"x": distance, "y": random.uniform(-1, 1)})

    await page.mouse.move(start_x, start_y)
    await page.mouse.down()
    for step in track:
        await page.mouse.move(start_x + step["x"], start_y + step["y"], steps=1)
        await asyncio.sleep(random.uniform(0.002, 0.008))
    await asyncio.sleep(random.uniform(0.05, 0.15))
    await page.mouse.up()

    print("[验证码] 滑动完成，等待结果...")
    await asyncio.sleep(3)


async def handle_captcha_if_needed(page: Page, student_id: str, password: str):
    """处理图片验证码"""
    captcha_img = await page.query_selector("#captcha_img")
    if not captcha_img:
        return

    print("[验证码] 需要图片验证码...")
    await asyncio.sleep(1)

    try:
        img_bytes = await captcha_img.screenshot()
        with open(str(ROOT / "captcha_img.png"), "wb") as f:
            f.write(img_bytes)

        captcha_text = ""
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(img_bytes))
            gray = img.convert("L")
            binary = gray.point(lambda x: 255 if x > 128 else 0, "1")
            try:
                import pytesseract
                captcha_text = pytesseract.image_to_string(
                    binary, config="--psm 7 -c tessedit_char_whitelist=0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                ).strip().replace(" ", "")
            except ImportError:
                pass
        except Exception:
            pass

        print(f"[验证码] 识别: '{captcha_text}'")
        if captcha_text and len(captcha_text) >= 2:
            captcha_input = await page.query_selector("#captcha, #fm1 #captcha")
            if captcha_input:
                await captcha_input.fill(captcha_text)
                await asyncio.sleep(0.3)
                await page.evaluate("""() => {
                    if (typeof _passwordLogin === 'function') _passwordLogin();
                    else if (typeof submitFm1 === 'function') submitFm1();
                    else document.getElementById('fm1').submit();
                }""")
    except Exception as e:
        print(f"[验证码] 失败: {e}")


# --- 会话管理 ---

async def restore_session(reserve_url: str, headless: bool = False, storage_state_path: str = None) -> tuple | None:
    if storage_state_path is None:
        storage_state_path = str(ROOT / "session.json")
    if not Path(storage_state_path).exists():
        return None

    print("[会话] 尝试恢复登录状态...")
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=headless, channel="msedge",
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    try:
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800}, locale="zh-CN",
            storage_state=storage_state_path,
        )
        page = await context.new_page()
        await page.goto(reserve_url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(3)

        if "cas" in page.url.lower() and "login" in page.url.lower():
            print("[会话] 已过期")
            await browser.close()
            return None

        dialog = await page.query_selector('.el-dialog__wrapper:not([style*="display: none"])')
        if dialog and await dialog.is_visible():
            print("[会话] 需要重新登录")
            await browser.close()
            return None

        print("[会话] 登录状态有效！")
        return browser, page
    except Exception as e:
        print(f"[会话] 恢复失败: {e}")
        await browser.close()
        return None


async def save_session(context: BrowserContext):
    path = str(ROOT / "session.json")
    await context.storage_state(path=path)
    print("[会话] 已保存")
    print("[会话] 已保存登录状态")
