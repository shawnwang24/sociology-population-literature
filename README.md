# 社会学与人口学文献雷达

一个可以部署到 GitHub Actions 的个人化学术文献推送程序。你只需要修改期刊、研究主题和邮箱配置；程序会定期检索新论文、补充摘要与开放获取链接、计算相关性、去重，并把高相关论文发送到邮箱。

本项目借鉴了 [daily-econ-literature-radar](https://github.com/lishn6/daily-econ-literature-radar) 的“研究画像—来源监测—综合评分—摘要邮件”思路，但程序代码是独立实现，且移除了 JEL、NBER、经济学 Top 5 等经济学专用结构。

## 它会做什么

- 通过期刊 ISSN 从 Crossref 读取最近登记的新论文；
- 可用 RSS/Atom 更快发现 Online First / Early View；
- 可从部分中文期刊的 Magtech 编辑部官网读取当期标题、作者和完整中文摘要；
- 可从国家哲学社会科学文献中心（NCPSSD）统一监测中文核心期刊，并补全作者、摘要、关键词和发布日期；
- 可用 OpenAlex 按 DOI 补充摘要、主题、关键词和开放获取链接；
- 可选用 OpenAlex 主题检索跨期刊发现论文；
- 分别给标题、摘要、作者关键词和 OpenAlex 主题赋权；
- 按 DOI 去重；缺 DOI 时优先使用稳定的来源文章编号，并兼容历史标题记录；
- 记录已经推送的论文，避免重复邮件；
- 将符合条件但未进入本次发送上限的论文保存到待发送队列，后续即使超出 14 天检索窗口也会继续参与推送；
- 每周报告来源成功数、失败数、中文期刊成功率和失败名单；
- 连续两次失败的来源会在邮件中警告，中文期刊成功率低于 90% 时工作流自动报错；
- 即使本周没有相关文章，也发送一封简短的运行成功通知；
- 云端正式任务执行离线测试；Crossref、NCPSSD、Magtech 在线冒烟测试独立运行，外站临时故障不会阻断正式邮件；
- 生成 Markdown、HTML 和 JSON 报告；
- 通过任意支持 SMTP 的邮箱发送 HTML 邮件；
- 可选调用兼容 Chat Completions 的模型生成简短中文摘要。

程序只处理公开元数据、摘要和合法链接，不绕过登录、不抓取知网或出版社受限全文，也不把付费 PDF 作为邮件附件。

## 项目结构

```text
config/
  settings.yml       运行、评分、邮件和数据源设置
  topics.yml         研究方向、关键词、作者、排除词
  journals.yml       目标期刊、ISSN、优先级、可选 RSS/中文期刊来源
  feeds.yml          工作论文平台或其他通用 RSS
data/state.json      已推送论文的去重状态
src/socdem_radar/    程序主体
tests/               离线测试
.github/workflows/   GitHub Actions 定时工作流
```

## 最短部署流程

### 1. 新建一个私有 GitHub 仓库

解压本项目，把文件上传到仓库根目录。建议使用私有仓库，因为研究画像本身可能包含尚未公开的选题。

### 2. 填写期刊与研究方向

修改：

- `config/journals.yml`：期刊名称、纸质版/电子版 ISSN、期刊优先级，以及可选的 `rss_url`、`magtech_url`、`ncpssd_code`；
- `config/topics.yml`：主题组、关键词、权重、关注作者、排除词；
- `config/settings.yml`：相关性阈值、每封最多几篇、回看天数。

项目自带“健康不平等—社会分层—人口家庭—劳动职业—中国情境”的示例。它只是示范，可以全部替换。详细写法见 [CONFIG_GUIDE_CN.md](CONFIG_GUIDE_CN.md)。

当前目录共 155 本期刊，已接通 153 本：107 本英文期刊和 46 本中文期刊。中文部分包含 3 本编辑部官网来源和 43 本 NCPSSD 来源；《农村经济》《南方人口》因暂未找到稳定的公开机器可读入口而保留在目录中，但暂不启用。NCPSSD 来源不需要 API key。

### 3. 配置 GitHub Actions Secrets

进入仓库的 `Settings → Secrets and variables → Actions → New repository secret`，添加：

| Secret | 是否必需 | 内容 |
| --- | --- | --- |
| `SMTP_USERNAME` | 发邮件时必需 | 发件邮箱账号 |
| `SMTP_PASSWORD` | 发邮件时必需 | SMTP 授权码或 Gmail App Password，不是主密码 |
| `SMTP_FROM` | 建议 | 发件邮箱，通常与账号相同 |
| `EMAIL_TO` | 发邮件时必需 | 收件邮箱；多个地址用英文逗号分隔 |
| `CROSSREF_MAILTO` | 建议 | 真实联系邮箱，供 Crossref polite pool 使用 |
| `OPENALEX_API_KEY` | 建议 | OpenAlex 免费 API key，用于摘要和开放链接补全 |
| `LLM_API_KEY` | 可选 | 只有开启中文 AI 摘要时才需要 |
| `LLM_MODEL` | 可选 | AI 摘要所用模型名 |

GitHub Secrets 不会写入配置文件；工作流只在运行时把它们注入环境变量。不要把邮箱密码、授权码或 API key 直接写进 YAML 或提交到 Git 历史。

### 4. 先做一次 dry-run

进入 `Actions → Sociology & Demography Literature Radar → Run workflow`，保留 `dry_run = true`。

这次运行会：

- 检查配置；
- 拉取并筛选论文；
- 在 Actions 的运行摘要中展示结果；
- 上传一个保存 14 天的预览包；
- 不发邮件，也不更新去重状态。

确认结果合理后，再手动运行一次并把 `dry_run` 改成 `false`，测试真实邮件发送。

### 5. 自动运行

默认工作流在每周日北京时间 `14:07` 左右运行。GitHub Actions 的 cron 使用 UTC；为降低整点拥堵造成的延迟，配置为：

```yaml
schedule:
  - cron: "7 6 * * 0"  # UTC 06:07 = 北京时间 14:07
```

例如每天早上 08:23：

```yaml
schedule:
  - cron: "23 0 * * *"  # UTC 00:23 = 北京时间 08:23
```

定时工作流只从默认分支运行；GitHub Actions 的 cron 不是严格实时调度，繁忙时可能延迟。状态文件会在成功运行后由 Actions 自动提交回仓库，因此下一次能排除已推送论文。

为避免延迟定时任务与手动正式运行在同一天连续发信，默认发送间隔为 12 小时。SMTP 临时失败会自动重试 3 次；状态提交遇到分支前进时会合并远端去重记录并重试，避免“邮件已发出但去重状态未保存”。

待发送队列默认最多保存 500 篇、最长保留 180 天，因此不会无限占用内存或让状态文件无限增长。每封邮件发送后，相应论文会立即从队列移除；邮件周报会显示剩余待发送数量。

### 来源健康监控

`config/settings.yml` 中的默认设置为：

```yaml
health:
  chinese_min_success_rate: 0.9
  consecutive_failure_warning: 2
```

中文期刊来源成功率低于 90% 时，系统仍会先生成报告并发送健康警告邮件，随后让 GitHub Actions 标记为失败。每个来源的连续失败次数保存在 `data/state.json`；恢复成功后计数自动清零。邮件中的“数据源周报”会列出总成功数、失败数、中文期刊成功率和失败来源。

## 本地运行

需要 Python 3.11 或更高版本。

```bash
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

python -m pip install -e .
python -m socdem_radar --config-dir config validate
python -m socdem_radar --config-dir config demo
python -m socdem_radar --config-dir config run --dry-run
```

离线 `demo` 不访问任何学术 API，适合先检查评分和邮件版式。真实检索的报告位于 `outputs/latest.md`、`outputs/latest.html` 和 `outputs/latest.json`。

如果需要在本地发送邮件，先复制 `.env.example` 中的变量到你自己的环境变量，再运行：

```bash
python -m socdem_radar --config-dir config send-test
python -m socdem_radar --config-dir config run
```

## Gmail 与其他邮箱

默认设置是 Gmail SMTP：

```yaml
host: "smtp.gmail.com"
port: 587
use_ssl: false
use_starttls: true
```

Gmail 通常需要先开启两步验证，再生成单独的 App Password。不要使用 Google 主密码。QQ 邮箱、163 邮箱、Outlook 等也可以使用，但要把 `host`、`port`、SSL/STARTTLS 方式改成邮箱服务商给出的设置，并使用其 SMTP 授权码。

## 评分与筛选

每个主题组有自己的 `weight`；同一关键词出现在哪个字段，会乘以不同权重：

| 命中位置 | 默认倍数 |
| --- | ---: |
| 标题 | 3.0 |
| 作者关键词 | 2.0 |
| OpenAlex 主题 | 1.5 |
| 摘要 | 1.0 |

同一主题组默认最多计入 3 个不同关键词，防止摘要堆叠同义词后分数失控。期刊优先级和关注作者会额外加分。命中 `exclude_keywords` 的论文直接排除。

如果结果过多：提高 `selection.min_score`、减少宽泛词、增加排除词或降低通用主题权重。结果过少时则反向调整。不要仅靠 `health`、`family`、`China` 这类单个宽泛词作为高权重核心主题。

## 数据源的合理分工

- **Crossref**：最适合按 ISSN 精确监测指定期刊；元数据完整度取决于出版社实际提交的内容。
- **OpenAlex**：适合补摘要、主题和开放获取地址。2026 年起官方用 API key 取代原来的 `mailto` polite-pool 机制；免费 key 足以支持个人化小规模雷达。
- **RSS/Atom**：通常比卷期信息更快，但出版社会改变 feed 地址；失效后需要更新 URL。
- **中文期刊官网**：当前已接通《人口研究》《社会》《社会学评论》的当期目录；这些页面直接提供中文摘要，无需额外 API key。《社会》官网超时或解析失败时，会自动切换到 NCPSSD 备用源。

本项目每次都回看最近 14 天，再用 `state.json` 去重。这样即使一次定时任务延迟或某个来源暂时失败，也比只依赖“上次运行时间到现在”的窗口更不容易漏报。

## 已知限制

- “新论文”指在数据源窗口中出现的新记录，不保证等同于纸质卷期的正式出版日；
- Crossref 可能缺摘要和作者关键词，OpenAlex 也并非每篇都有摘要；缺失时程序不会虚构结论；
- 完整核心目录中的中文期刊会全部保留；只有存在可稳定访问的数据源时才启用，避免把“目录已收录”误当成“已经抓取成功”；
- OpenAlex 跨期刊检索比期刊 ISSN 监测噪声大，默认关闭；
- GitHub Actions 的定时任务可能延迟，因此邮件不应被当作分钟级提醒服务；
- 相关性评分是信息筛选工具，不是文献质量评价或系统综述的纳入标准。

## 测试

```bash
python -m unittest discover -s tests -v
```

测试不访问外网，覆盖配置、关键词边界、排除词、DOI/标题去重、Crossref/OpenAlex/中文期刊官网解析、摘要重建和状态持久化。

## 参考接口

- [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)
- [Crossref REST API filters](https://www.crossref.org/documentation/retrieve-metadata/rest-api/rest-api-filters/)
- [OpenAlex Works API](https://developers.openalex.org/api-reference/works)
- [OpenAlex authentication and pricing](https://developers.openalex.org/guides/authentication)
- [GitHub Actions scheduled workflows](https://docs.github.com/actions/using-workflows/events-that-trigger-workflows)
- [GitHub Actions secrets](https://docs.github.com/actions/security-guides/using-secrets-in-github-actions)

## 许可证

MIT。
