"""
华中农业大学羽毛球场馆自动抢场脚本 - 主入口

用法:
  python main.py --now          立即执行预约（可用于测试）
  python main.py                定时模式（每天15:59:55自动执行）
  python main.py --test-login   仅测试登录流程
  python main.py --test-email   测试邮件通知配置
  python main.py --inspect      打开浏览器探索页面结构（用于调试）

配置文件: config.yaml
请先将 config.yaml 中的 YOUR_STUDENT_ID 和 YOUR_PASSWORD 替换为你的学号和密码。
"""
import asyncio
import sys
import os
import yaml
import schedule
import time
from datetime import datetime
from pathlib import Path

from auth import login, restore_session, save_session
from reserve import wait_for_booking_open, reserve_slot, discover_page_structure, navigate_to_venue
from notifier import notify_success, notify_failure, set_email_config, test_email

# 工作目录设为脚本所在目录
SCRIPT_DIR = Path(__file__).parent
os.chdir(SCRIPT_DIR)


def load_config():
    """加载并验证配置文件"""
    config_path = SCRIPT_DIR / "config.yaml"
    if not config_path.exists():
        print("[错误] 找不到 config.yaml，请先创建配置文件。")

        # 创建默认配置
        default_config = {
            "credentials": {"student_id": "YOUR_STUDENT_ID", "password": "YOUR_PASSWORD"},
            "preferences": {
                "venue_name": "羽毛球",
                "time_slots": [
                    {"start": "19:00", "end": "21:00"},
                    {"start": "20:00", "end": "22:00"},
                    {"start": "16:00", "end": "18:00"},
                    {"start": "15:00", "end": "17:00"},
                    {"start": "14:00", "end": "16:00"},
                    {"start": "13:00", "end": "15:00"},
                ],
            },
            "behavior": {
                "reserve_url": "https://zhcg.hzau.edu.cn/#/reserveList?uuid=492f6b87ffda42879b152d31e9581c78",
                "schedule_time": "15:59:55",
                "headless": False,
                "max_retries": 3,
                "retry_interval": 5,
                "use_saved_session": True,
            },
            "notification": {"enabled": False, "wecom_webhook": ""},
        }
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(default_config, f, allow_unicode=True, default_flow_style=False)
        print("[提示] 已创建默认 config.yaml，请编辑填入你的学号和密码后重新运行。")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 验证必填字段
    cred = config.get("credentials", {})
    sid = str(cred.get("student_id", ""))
    pwd = str(cred.get("password", ""))

    if not sid or sid == "YOUR_STUDENT_ID":
        print("[错误] 请在 config.yaml 中填写你的学号 (student_id)")
        sys.exit(1)
    if not pwd or pwd == "YOUR_PASSWORD":
        print("[错误] 请在 config.yaml 中填写你的密码 (password)")
        sys.exit(1)

    return config


async def do_reserve(config: dict) -> bool:
    """执行一次完整的预约流程，返回是否成功"""
    cred = config["credentials"]
    pref = config["preferences"]
    behavior = config["behavior"]

    # 配置邮件通知
    email_cfg = config.get("email", {})
    if email_cfg.get("enabled", False):
        set_email_config(email_cfg)
        print("[系统] 邮件通知已启用")

    browser = None
    success = False

    try:
        # 1. 尝试恢复会话
        use_session = behavior.get("use_saved_session", True)
        if use_session:
            result = await restore_session(
                reserve_url=behavior["reserve_url"],
                headless=behavior.get("headless", False),
            )
            if result:
                browser, page = result
                print("[系统] 使用已保存的会话")
                # 保存 context 引用以便后续保存 session
                context = page.context
            else:
                browser = page = context = None

        # 2. 如果会话恢复失败，重新登录
        if browser is None:
            browser, page = await login(
                student_id=str(cred["student_id"]),
                password=str(cred["password"]),
                reserve_url=behavior["reserve_url"],
                headless=behavior.get("headless", False),
            )
            context = page.context

        # 3. 保存会话状态
        if browser and use_session:
            await save_session(page.context)

        # 4. 等待预订开放时间（--now 模式跳过等待）
        schedule_time = behavior.get("schedule_time", "15:59:55")
        if "--now" not in sys.argv:
            print(f"[系统] 等待预订开放时间: {schedule_time}")
            await wait_for_booking_open(page, schedule_time)
        else:
            print("[系统] --now 模式，跳过等待，直接执行")

        # 5. 执行预订
        success = await reserve_slot(
            page=page,
            venue_name=pref["venue_name"],
            preferred_slots=pref["time_slots"],
            reserve_url=behavior["reserve_url"],
            max_retries=behavior.get("max_retries", 3),
            retry_interval=behavior.get("retry_interval", 5),
        )

        # 6. 通知结果
        if success:
            print("\n" + "=" * 50)
            print("  >>> 预订成功！请登录系统查看详情。")
            print("=" * 50)
            notify_success("场地已预订！")
        else:
            print("\n" + "=" * 50)
            print("  [X] 未能抢到场地，请手动尝试。")
            print("=" * 50)
            notify_failure("未能抢到场地")

        # 保持浏览器打开以便查看
        await asyncio.sleep(30)

    except Exception as e:
        print(f"\n[错误] {e}")
        import traceback
        traceback.print_exc()
        notify_failure(str(e))
        await asyncio.sleep(60)
    finally:
        if browser:
            await browser.close()
            print("[系统] 浏览器已关闭")

    return success


async def test_login(config: dict):
    """测试登录流程"""
    cred = config["credentials"]
    behavior = config["behavior"]

    browser = None
    try:
        # 先尝试恢复会话
        result = await restore_session(
            reserve_url=behavior["reserve_url"],
            headless=False,
        )
        if result:
            print("[测试] 会话恢复成功！浏览器保持打开 60 秒。")
            browser, page = result
        else:
            print("[测试] 开始完整登录流程...")
            browser, page = await login(
                student_id=str(cred["student_id"]),
                password=str(cred["password"]),
                reserve_url=behavior["reserve_url"],
                headless=False,
            )
            # 保存会话
            await save_session(page.context)

        print("[测试] 登录成功！浏览器保持打开 60 秒供查看。")
        await asyncio.sleep(60)
    except Exception as e:
        print(f"[测试] 出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if browser:
            await browser.close()


async def inspect_page(config: dict):
    """打开浏览器探索页面结构（调试用）"""
    behavior = config["behavior"]

    browser = None
    try:
        result = await restore_session(
            reserve_url=behavior["reserve_url"],
            headless=False,
        )
        if result:
            browser, page = result
        else:
            cred = config["credentials"]
            browser, page = await login(
                student_id=str(cred["student_id"]),
                password=str(cred["password"]),
                reserve_url=behavior["reserve_url"],
                headless=False,
            )
            await save_session(page.context)

        # 导航到预订页面并分析
        await navigate_to_venue(
            page,
            config["preferences"]["venue_name"],
            behavior["reserve_url"],
        )
        await discover_page_structure(page)

        print("\n[检查] 浏览器保持打开。请查看 debug_reserve.html 了解页面结构。")
        print("[检查] 按 Ctrl+C 关闭浏览器。")
        await asyncio.sleep(300)
    except KeyboardInterrupt:
        print("\n[检查] 用户中断")
    finally:
        if browser:
            await browser.close()


def scheduled_job(config: dict):
    """定时任务入口"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'=' * 50}")
    print(f"[{now}] 定时任务触发！")
    print(f"{'=' * 50}")

    asyncio.run(do_reserve(config))


def main():
    print("=" * 50)
    print("  华中农业大学羽毛球场馆自动抢场脚本")
    print("  Badminton Court Auto-Booking Bot")
    print("=" * 50)
    print()

    config = load_config()
    args = sys.argv[1:]

    if "--test-email" in args:
        print("[模式] 测试邮件发送")
        email_cfg = config.get("email", {})
        if not email_cfg.get("enabled", False):
            print("[错误] 请先在 config.yaml 中启用 email.enabled 并填写配置")
            return
        set_email_config(email_cfg)
        test_email()
        return

    if "--test-login" in args:
        print("[模式] 测试登录")
        asyncio.run(test_login(config))
        return

    if "--inspect" in args:
        print("[模式] 探索页面结构")
        asyncio.run(inspect_page(config))
        return

    if "--now" in args:
        print("[模式] 立即执行预约")
        asyncio.run(do_reserve(config))
        return

    # 默认：定时模式
    schedule_time = config["behavior"].get("schedule_time", "15:59:55")
    print(f"[模式] 定时预约")
    print(f"  每天 {schedule_time} 自动执行")
    print(f"  目标场馆: {config['preferences']['venue_name']}")
    print(f"  时段偏好: {', '.join(f'{s['start']}-{s['end']}' for s in config['preferences']['time_slots'][:3])}...")
    print()
    print("[提示] 脚本将保持运行，请勿关闭此窗口。")
    print("[提示] 按 Ctrl+C 可停止。")
    print()

    schedule.every().day.at(schedule_time).do(scheduled_job, config=config)

    next_run = schedule.next_run()
    if next_run:
        print(f"  下次执行时间: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[系统] 已停止。")


if __name__ == "__main__":
    main()

