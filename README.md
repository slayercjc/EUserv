# EUserv 免费 VPS 自动续期

GitHub Actions 每天北京时间 **09:23** 检查指定合同。使用同一个浏览器会话完成免费套餐选择、Gmail PIN 验证和合同结束日期回读。调度可能延迟，不能保证准点。

**当前状态：初版脚本，尚未使用真实账户完成端到端验证。** 登录字段已参考公开登录页；登录后页面依据用户截图实现，首次运行可能需要调整元素定位或日期字段。遇到无法识别的页面会失败退出，不会盲点提交。

## 1. 配置 GitHub Secrets

进入仓库 **Settings → Secrets and variables → Actions → Secrets → New repository secret**，逐一新增：

| Name | 填写内容 |
| --- | --- |
| `EUSERV_USERNAME` | EUserv 登录邮箱或 Customer ID |
| `EUSERV_PASSWORD` | EUserv 登录密码 |
| `EUSERV_CONTRACT_ID` | 要续期的合同号，只填数字 |
| `GMAIL_ADDRESS` | 接收 PIN 的完整 Gmail 地址 |
| `GMAIL_APP_PASSWORD` | Google 生成的 16 位应用专用密码，不是 Gmail 登录密码 |
| `EUSERV_PIN_SENDER` | 展开 PIN 邮件发件人详情，复制完整发件邮箱地址；不是显示名称，也不是邮箱正文里的支持链接 |

Gmail 应用密码：先启用两步验证，再到 https://myaccount.google.com/apppasswords 创建。若账号没有这个选项，需要使用其他认证方案，本版本不支持 OAuth。

脚本只读 INBOX，不删除邮件，也不标记已读。请让 EUserv PIN 邮件进入收件箱，避免被过滤归档或进入垃圾箱。应用密码本身权限较广，应只放 Secrets，切勿提交到代码、Issue、截图或聊天。

## 2. 首次检查

进入 **Actions → EUserv free renewal → Run workflow**，保留 `dry_run` 勾选。此模式登录、检查合同和免费套餐，**不会点击套餐 Extend、不会请求 PIN，也不会续期**；暂不验证 Gmail 连接。

如果当前尚未开放续期，页面必须明确给出未来的可续期日期才能判定为无需续期。单纯缺少按钮会报错，以免漏续期被当成成功。

如果提示“合同结束日期字段”或“免费原套餐区域”无法识别，请提供对应页面的截图（遮住隐私），调整后再试。需要出现续期入口时才能完整检查免费套餐路径。

## 3. 首次真实续期与启用定时

在可续期时再次 **Run workflow**，取消勾选 `dry_run`，完成一次实际续期验证。期间不要在其他浏览器同时请求 PIN。脚本会在点击 Extend 之前记录邮箱 UID 检查点，仅接受指定发件人的新邮件、有效时间和 `PIN:` 后六位数字，并在原会话中提交。

只有看到“免费续期已确认”且结束日期确实增加，才算真实续期通过。若显示“PIN 已提交，但未确认到期日更新”，请先检查网站合同，避免重复提交。

随后进入 **Settings → Secrets and variables → Actions → Variables → New repository variable**：

```text
Name:  RENEW_ENABLED
Value: true
```

定时任务默认关闭。手动运行不受此变量限制。关闭自动续期时将变量改为 `false`。

默认分支 `main` 上的 Python 代码、测试、依赖或工作流更新会自动执行 `dry_run` 只读检查，不会请求 PIN 或提交续期。运行系统固定为 Ubuntu 24.04，以匹配锁定的 Playwright 版本。

工作流必须在默认分支。建议使用私有仓库：公开仓库连续 60 天无仓库活动可能被 GitHub 自动停用定时任务；脚本不会为维持活跃而自动提交代码。私有仓库的 Actions 用量按账户套餐计费，请在 GitHub Billing 中查看额度。

## 4. 结果与通知

每次结果在 Actions 运行摘要中显示；异常时任务失败。到 GitHub **Settings → Notifications → System → Actions** 开启工作流失败的邮件通知（是否收到取决于你的 GitHub 通知配置）。本脚本不会自行发送邮件，也不保存页面截图、HTML、会话 Cookie、PIN 或完整邮箱正文到 Actions 日志/产物。

## 行为限制

- 仅处理配置的合同，套餐必须是 `vServer VS2-free v2.1`；续期费和月费必须均为 `0.00 EUR`。
- 选择异常、付费项目、未知费用、多个新 PIN、登录失效时停止。
- 登录图形验证码会使用本机 `ddddocr` 尝试识别一次，只接受完整的简单算式；不上传图片、不记录答案、不使用付费打码服务。无法识别或验证失败则停止，不保证每次成功。身份验证器二次验证尚未支持。
- 不自动重试续期提交。网站布局、文案或规则变动可能导致失败，请留意 Actions 失败通知。
- 所有日期比较及邮箱读取都在当前运行中完成；不把本地记录当成服务端续期成功证据。

## 本地测试

Python 3.12：

```sh
pip install -r requirements.txt
python -m playwright install chromium
python -m unittest discover -s tests -v
```

测试覆盖费用拦截、免费套餐与付费升级隔离、精确合同匹配、纯文本/HTML PIN、旧邮件/错误发件人/多 PIN 拒绝、IMAP UID 边界。测试使用虚构邮件和模拟页面，不能代替真实站点验证。

官方参考：[GitHub 定时触发规则](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)、[Google 应用密码](https://support.google.com/mail/answer/185833?hl=zh-Hans)。
