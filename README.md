# 华中农业大学羽毛球场馆自动抢场脚本

每天下午 4 点自动预约第二天羽毛球场地的 Python 脚本。

## 功能

- 自动登录智慧狮山 CAS 统一认证（学号+密码）
- 会话保持，一次登录后无需重复验证
- 自动关闭须知弹窗
- 按偏好时段自动匹配并预约连续 2 小时场地
- 预约失败自动刷新重试、切换备选场地
- 预约成功后邮件通知，5 分钟内通过企业微信手动付款
- 预约失败也发送邮件提醒

## 环境要求

- Windows 10/11
- Microsoft Edge 浏览器
- Python 3.10+

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 安装 Playwright 浏览器
playwright install msedge

# 3. 复制并编辑配置文件
copy config.yaml.example config.yaml

# 4. 填写 config.yaml 中的学号、密码和邮箱配置

# 5. 测试登录
python main.py --test-login

# 6. 测试邮件
python main.py --test-email

# 7. 定时运行（每天 15:59:55 自动抢场）
python main.py

# 或直接双击 启动抢场.bat
```

## 配置文件说明

编辑 `config.yaml`：

```yaml
credentials:
  student_id: "你的学号"
  password: "你的密码"

preferences:
  venue_name: "羽毛球"
  time_slots:           # 按优先级排列，脚本逐个尝试
    - start: "19:00"
      end: "21:00"
    - start: "20:00"
      end: "22:00"
    # ...

email:
  enabled: true         # 启用邮件通知
  smtp_server: "smtp.qq.com"
  smtp_port: 465
  sender: "你的QQ邮箱@qq.com"
  password: "QQ邮箱SMTP授权码"   # 不是QQ密码！
  recipients:
    - "接收通知的邮箱@qq.com"
```

QQ 邮箱授权码获取：设置 → 账户 → POP3/SMTP 服务 → 开启 → 生成授权码。

## 命令行参数

| 命令 | 说明 |
|------|------|
| `python main.py` | 定时模式，每天 15:59:55 自动执行 |
| `python main.py --now` | 立即执行一次预约（测试用） |
| `python main.py --test-login` | 仅测试登录流程 |
| `python main.py --test-email` | 测试邮件通知配置 |

## 工作原理

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ 恢复会话  │ -> │ 导航场馆  │ -> │ 关闭弹窗  │ -> │ 等待 4PM │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
                                                      │
┌──────────┐    ┌──────────┐    ┌──────────┐          │
│ 邮件通知  │ <- │ 提交预约  │ <- │ 匹配时段  │ <────────┘
└──────────┘    └──────────┘    └──────────┘
```

## 注意事项

- 每天只能预约连续 2 小时，同一用户最多一个有效预约
- 场地锁定后有 5 分钟付款窗口，需在手机上通过企业微信完成付款
- 脚本依赖 Edge 浏览器，请勿卸载
- `config.yaml` 包含敏感信息，已加入 `.gitignore`，请勿上传到公开仓库
- 使用前建议先用 `--now` 和 `--test-email` 验证配置

## 文件结构

```
badminton/
├── main.py                # 入口，定时调度 & 命令行
├── auth.py                # CAS 登录 & 会话管理
├── reserve.py             # 场馆选择 & 时段匹配 & 预约提交
├── notifier.py            # 桌面通知 & 邮件通知
├── config.yaml            # 配置文件（不提交）
├── config.yaml.example    # 配置模板
├── requirements.txt       # Python 依赖
├── .gitignore
├── 启动抢场.bat            # Windows 双击启动
└── README.md
```

## License

MIT