"""
通知模块：支持 Windows 桌面通知、企业微信机器人推送和邮件通知
"""
import json
import smtplib
import subprocess
import urllib.request
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path


_email_config = None


def set_email_config(config: dict):
    global _email_config
    _email_config = config


def _send_email(subject: str, body: str):
    if not _email_config:
        return
    smtp_server = _email_config.get("smtp_server", "")
    smtp_port = _email_config.get("smtp_port", 465)
    sender = _email_config.get("sender", "")
    password = _email_config.get("password", "")
    recipients = _email_config.get("recipients", [])
    if not smtp_server or not sender or not password or not recipients:
        print("[邮件] 邮件配置不完整，跳过发送")
        return
    try:
        msg = MIMEMultipart()
        msg["From"] = sender
        rcpts = ", ".join(recipients) if isinstance(recipients, list) else recipients
        msg["To"] = rcpts
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)
            server.starttls()
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())
        server.quit()
        print(f"[邮件] 已发送到: {recipients}")
    except Exception as e:
        print(f"[邮件] 发送失败: {e}")


def _send_windows_toast(title: str, message: str):
    try:
        ps_script = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null\n"
            "$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)\n"
            '$textNodes = $template.GetElementsByTagName("text")\n'
            f'$textNodes.Item(0).AppendChild($template.CreateTextNode("{title}")) > $null\n'
            f'$textNodes.Item(1).AppendChild($template.CreateTextNode("{message}")) > $null\n'
            '$toast = [Windows.UI.Notifications.ToastNotification]::new($template)\n'
            '[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("badminton-bot").Show($toast)'
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, timeout=10)
    except Exception:
        pass


def _send_wecom_webhook(webhook_url: str, content: str):
    try:
        data = json.dumps({"msgtype": "text", "text": {"content": content}}).encode("utf-8")
        req = urllib.request.Request(webhook_url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"[通知] 企业微信推送失败: {e}")


def notify(title: str, message: str, webhook_url: str = ""):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_msg = f"[{now}] {message}"
    print(full_msg)
    _send_windows_toast(title, message)
    if webhook_url:
        _send_wecom_webhook(webhook_url, full_msg)


def notify_success(court_name: str = "", time_slot: str = ""):
    slot_desc = f"{court_name} {time_slot}" if court_name else time_slot or "场地已锁定"
    notify(
        title="[OK] 羽毛球场预订成功",
        message=f"{slot_desc}，请5分钟内在企业微信中完成付款！",
    )
    body_lines = [
        "场地已锁定！",
        "",
        f"场地: {court_name}",
        f"时段: {time_slot}",
        "",
        "请在5分钟内打开企业微信完成付款，超时场地将被释放。",
        "",
        "-- 自动抢场脚本",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    ]
    _send_email(
        subject="[OK] 羽毛球场预订成功 - 请尽快付款",
        body="\n".join(body_lines),
    )


def notify_failure(reason: str = ""):
    notify(
        title="[FAIL] 羽毛球场预订失败",
        message=f"未能抢到场地。{reason}",
    )
    body_lines = [
        "未能抢到场地。",
        "",
        f"原因: {reason or '目标时段已无可用场地'}",
        "",
        "建议手动登录系统查看。",
        "",
        "-- 自动抢场脚本",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    ]
    _send_email(
        subject="[FAIL] 羽毛球场预订失败",
        body="\n".join(body_lines),
    )


def notify_login_error(reason: str = ""):
    notify(
        title="[WARN] 登录失败",
        message=f"请检查账号密码或网络。{reason}",
    )


def test_email():
    if not _email_config:
        print("[测试] 未配置邮件，请在 config.yaml 中设置 email 部分")
        return False
    print(f"[测试] 邮件配置: server={_email_config.get('smtp_server')}, sender={_email_config.get('sender')}")
    try:
        body_lines = [
            "这是自动抢场脚本的测试邮件。",
            "",
            f"发送时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        _send_email(
            subject="[测试] 羽毛球场自动抢场脚本 - 邮件测试",
            body="\n".join(body_lines),
        )
        print("[测试] 邮件发送成功！请检查收件箱。")
        return True
    except Exception as e:
        print(f"[测试] 邮件发送失败: {e}")
        return False
