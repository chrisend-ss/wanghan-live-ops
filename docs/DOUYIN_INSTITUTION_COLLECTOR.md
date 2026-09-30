# Douyin Institution Collector

目标：以抖音机构版单场直播详情页 `liveRecordDetail` 为标准源，抓取王焓每场直播的机构后台聚合数据，并绑定到运营实验系统。

## 标准页面

页面形态：

```text
https://union.bytedance.com/open/portal/anchor/list/liveRecordDetail?...&roomID=...
```

采集器会从 URL 自动识别：

- anchorID
- roomID
- appId

其中 `roomID` 是后续场次绑定的核心键之一。

## 两种模式

### A. 附着到已经登录的 Chromium

如果浏览器开放 Chrome DevTools Protocol 调试端口：

```bash
python tools/douyin_institution_collect.py \
  --url "<liveRecordDetail URL>" \
  --cdp-url http://127.0.0.1:9222
```

采集器会优先寻找已经打开的机构详情页，复用登录态，不会关闭用户浏览器。

### B. 持久化采集浏览器

如果当前 Codex/ChatGPT 内置浏览器不开放 CDP，就使用采集器自己的持久化 Chromium：

```bash
pip install -r requirements-institution.txt
python -m playwright install chromium

python tools/douyin_institution_collect.py \
  --url "<liveRecordDetail URL>"
```

第一次需要用户本人完成登录。之后登录态保留在：

```text
data/douyin-institution-profile/
```

该目录已被 `.gitignore` 覆盖，不上传 GitHub。

## 第一版采集策略

不硬编码页面 DOM，而是监听详情页加载时的 JSON 响应。

保存：

- 页面可见文本（用于核对指标中文名称）
- 机构后台 JSON 响应
- roomID / anchorID / appId
- 标准化指标候选
- 每个指标的原始 source_url / source_path
- 映射置信度

不保存：

- Cookie
- 密码
- request headers
- URL query 中的 token/signature
- 浏览器登录凭据

## 输出

每次采集写到：

```text
data/institution/<timestamp>_<roomID>/
  ├─ page_text.txt
  ├─ responses.jsonl
  └─ standardized.json
```

原始数据只留本地，不提交公开仓库。

## 标准化指标

第一版先尝试发现这些聚合字段：

- exposure_uv
- viewer_uv
- viewer_pv
- enter_uv
- entry_rate
- max_online
- avg_online
- avg_watch_seconds
- new_followers
- unfollows
- fanclub_joins
- comments
- likes
- pay_users
- gift_value

注意：第一次运行前，这些字段映射全部视为 provisional。
只有拿真实机构页面返回与页面标签逐项核对后，才升级为 verified。

## 下一步

第一次真实采集完成后：

1. 读取 `page_text.txt`
2. 检查 `responses.jsonl` 的字段路径
3. 把页面中文指标和 JSON key 一一对齐
4. 固化 verified schema
5. 把 verified 指标写入 session 级机构数据表
6. 自动回填 visual/opening experiment_results

切片模块不读取这些抖音指标；切片继续只由 B站录屏内容决定。
