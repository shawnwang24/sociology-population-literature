# 配置填写指南

真正需要经常修改的只有 `config/` 下四个文件。

## 1. 期刊：`journals.yml`

```yaml
journals:
  - name: "Journal Name"
    enabled: true
    issns:
      - "1234-5678"   # 纸质版
      - "8765-4321"   # 电子版，可选
    priority: 3        # 0—5；越高越容易进入邮件
    rss_url: ""       # 有稳定 RSS 时填写，没有就留空
```

建议先放 10—20 本真正会看的期刊。期刊太多并不会自动提高质量，只会扩大筛选噪声。

注意：

- ISSN 不是 DOI，也不是期刊主页 URL；
- 同一本期刊的纸质 ISSN 和电子 ISSN 可以同时填；
- 程序会按 DOI 去重，不会因为两个 ISSN 把同一论文发两次；
- `priority` 是你的个人优先级，不代表期刊客观等级。

## 2. 研究画像：`topics.yml`

### 主题组

```yaml
groups:
  - name: "健康不平等"
    enabled: true
    weight: 2.5
    keywords:
      - "health inequality"
      - "health disparities"
      - "social gradient in health"
```

最好按理论或研究维度分组，而不是把所有词堆进一个列表。例如：

- 核心问题：健康不平等；
- 分层维度：教育、职业、收入、财富、户口；
- 人群：农民工、老年人、夫妻、儿童；
- 健康结局：自评健康、抑郁、死亡、慢病；
- 就业处境：职业错配、失业、工作质量；
- 地区/数据：中国、CFPS、CHARLS、CLHLS；
- 方法：固定效应、事件研究、工具变量。

核心问题权重应更高，方法和宽泛背景词应较低。单独出现 `health`、`family`、`education` 往往不足以判断高度相关。

### 关注作者

```yaml
watched_authors:
  - "Author Full Name"
  - "另一位作者"
```

目前是姓名字符串匹配。姓名非常常见时可能误匹配，后续可以扩展为 ORCID。

### 排除词

```yaml
exclude_keywords:
  - "mouse model"
  - "in vitro"
```

排除词是硬过滤，宜少不宜多。只有确定不属于你的研究范围时才添加。

### 跨期刊发现

```yaml
discovery_queries:
  - '"health inequality" sociology'
```

还要在 `settings.yml` 中把 `sources.openalex.discovery_enabled` 改为 `true`。建议先稳定运行期刊监测，再开启此项。

## 3. 通用 RSS：`feeds.yml`

```yaml
feeds:
  - name: "Working paper feed"
    enabled: true
    journal: "Working Papers"
    url: "https://example.org/feed.xml"
    priority: 1
```

它可以接工作论文平台、研究机构或期刊预发表 feed。不要把普通网页 URL 当作 RSS；浏览器打开后通常应看到 XML，或页面源代码中存在 `<rss>` / `<feed>`。

## 4. 阈值与邮件：`settings.yml`

最常调的是：

```yaml
lookback:
  days: 14

selection:
  min_score: 6
  max_papers: 15
  max_per_journal: 5
```

- 每周运行一次时，回看 14 天比较稳妥；
- 每天运行可改成 7 天，重复记录仍会被状态文件排除；
- `min_score` 越高，邮件越少；
- `max_per_journal` 防止某本期刊占满整封邮件。

邮件服务器默认 Gmail。如果只想先生成本地报告：

```yaml
email:
  enabled: false
```

正式部署前建议保持 `enabled: true`，通过 GitHub Secrets 提供账号信息。

## 推荐的调试顺序

1. `validate`：检查 YAML 结构；
2. `demo`：检查评分和版式，不访问网络；
3. `run --dry-run`：真实检索但不发邮件；
4. `send-test`：只测试 SMTP；
5. `run`：真实检索并发邮件；
6. 最后再开启 GitHub Actions 定时任务。

不要在第一次运行前同时加入几十本期刊、几百个关键词和跨期刊发现。先用小范围观察一两轮，才容易判断哪些词带来噪声。
