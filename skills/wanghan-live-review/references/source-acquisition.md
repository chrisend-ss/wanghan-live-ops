# B站录屏与Chrome抖音后台：两个数据入口

## 能力与状态

本Skill包含读取规则和只读整理脚本，浏览器由宿主提供。不会自行安装Chrome扩展或凭说明获得浏览器权限。逐项记录：已发现浏览器、页面已登录、场次已确认、数据已采集、时间已校准；没有实际返回数据不得标为完成。

执行前检查当前工具。Chrome已连接时，绑定用户指定的浏览器配置/标签页，不另开未登录浏览器替代它，也不读取本机Chrome凭据库。只使用实际浏览器工具返回的API，不通过其他技术绕过缺失连接或网站访问控制。

## 入口一：B站录屏

1. 接收BV或完整B站链接；记录分P、CID、页面标题、每P时长和发布日期。短链接先在可用浏览器中解析。发布日期与标题中的日期不能自动认定实际开播日期。
2. GitHub仓库 `chrisend-ss/wanghan-live-ops` 已有公开视频元数据、字幕读取及云端临时音轨转写。先查 `reviews/`，同BV还必须核对分P/CID、模型/版本、覆盖范围和质量，避免错误复用或重复提交任务。
3. 可使用 `scripts/prepare_sources.py bilibili --url URL --reviews-root REPO/reviews --output PRIVATE/intake.json`。脚本只查询匿名元数据/字幕轨列表和扫描已有结果，不下载音视频、不读取Cookie、不启动云端转写。metadata_available不表示有转写；reuse_candidate仍需质量审查。
   匿名请求返回412等错误时，改由已连接浏览器查看正常页面。工具实际提供CDP并允许开发者检查时，只读提取页面已加载的 `__INITIAL_STATE__.videoData` 中bvid/title/pages/cid/duration/pubdate，排除媒体签名URL和Cookie；保存筛选元数据后加 `--metadata-input PRIVATE/browser-metadata.json` 整理。没有这项能力则保留页面观察和未确认字段，不能凭空填写CID。
4. 匿名字幕为空不代表视频没有字幕。已登录B站浏览器可见字幕时，在工具允许范围读取轨道和原文，保留时间码与来源；账号字幕或ASR均不能自动标王焓，也不能证明已经区分歌唱/BGM。
5. 无可用文字时，使用仓库现有 `review_requests/*.json` → `.github/workflows/bilibili-review.yml` → `tools/cloud_bilibili_review.py` 链路。在提交前查参数和任务状态；不能盲目workflow_dispatch重跑全部历史请求。B站访问失败、登录/验证码或云端失败明确报告，不绕过限制。
6. 只有已核验同录像参考与ASR质量同时通过时，片段才作为王焓确认原话。主簇、首次出现、最长时长只能产生待核验候选；旧V2的medium/high不是独立身份确认。仓库若采用V2.1核验，检查具体实现和结果，不能只因版本名称宣称验收通过。
7. 用B站播放器检查少量关键画面/原音。复盘阶段先验证锚点，保留暂停、剪辑和分P边界；完整视频不默认长期落盘。私人后台信息不得混入公开转写请求。

## 入口二：已登录Chrome的抖音后台

### 一次性连接

官方说明：https://learn.chatgpt.com/docs/chrome-extension

- 桌面应用“设置 → Computer Use／计算机使用”，需要时展开More browsers／更多浏览器，选择Chrome并从应用入口安装官方扩展。
- 使用安装扩展且已登录后台的同一Chrome配置，确认显示Manage／管理，并在聊天中@Chrome或@指定后台标签页。
- 快捷入口：`codex://settings/computer-use/google-chrome`；另有 `codex://settings/browser-use`。若实际界面没有入口，记录宿主限制，先交付可完成的整理部分，不假称已连接。
- 连接是用户当前配置的状态，不写入通用Skill为永久事实。账号和验证码由用户在原站完成；无需把Cookie或密码粘贴到对话。

### 每场只读采集

支持抖音后台页面及直播服务平台·机构版 `https://union.bytedance.com`。机构版入口由用户提供，先在主播详情的“直播场次”核对账号和日期，再进入对应场次详情。公开文档和样例不保存用户的anchorID或场次查询参数；URL整理器保留域名与路径，具体场次身份放在私有数据的独立字段中。

1. 确认王焓账号与选中场次、session ID、实际开播/结束、时区及日期筛选。不同账号/场次不得自动合并。
2. 优先原生导出或页面可读取的表格/数值；收集总览、趋势、流量来源、转化、新人留存及必要的PK/投流节点。无导出时按实际可用浏览器API读取页面。截图仅在其他方式不可用时补证，不把像素曲线编成精确数值。
3. 对Canvas/ECharts趋势，只有当前浏览器工具实际支持并明确允许页面数据/网络响应读取时才读取原始序列。可以观察页面当前发起的只读数据响应，核对session和筛选；不能在不支持开发者读取的工具里执行隐藏状态脚本。否则用平台导出，不推测接口参数。
   CDP可用时，按其实际文档启用Network事件，先保存事件游标，再进行正常页面刷新/筛选，读取该游标后的responseReceived/loadingFinished。只对已经观察到的相关JSON响应调用Network.getResponseBody；仅提取该场汇总与趋势字段。不输出请求头、Cookie、未清理的查询参数或粉丝明细。不得禁用缓存/安全限制来强行取得响应；响应不可得时回到原生导出。
4. 历史可能出现 `overview_v3`、`minute_trend`、`entrance_v2`、`conversion_ratio` 等路由名，仅作查找线索。必须以当前页面已观察的路由、响应结构与含义为准；不硬编码未验证的API，不通过复制认证参数到外部请求来接入。
5. 每个指标保留原标签、值、单位、窗口、流量来源、人群、采集时间和证据位置。分别标记window_increment/cumulative/instant/cohort/official_rate；万/亿缩写标近似。未显示的指标是缺失，不是0。
6. 采集只读数据不操作投流、收益、直播设置、消息或账号权限。数据输出先做字段白名单与URL清理，不保存Cookie、请求头、完整HAR、签名参数或粉丝身份明细。

### 交接与验证

将明确映射的数据整理为 `scripts/prepare_sources.py backend --input PRIVATE/capture.json --output PRIVATE/normalized.json` 的输入，示例见 `backend-capture-example.json`。示例全部虚构，不能写入真实场次。

脚本只规范数据，不控制浏览器、不连接抖音、不自动猜测接口字段。输出状态为observations_normalized_not_validated；derived_rates保持空。下一步必须审查人数/次数、去重、人群、窗口和官方指标定义，再计算进房率或新人60秒留存。官方比例无分子分母时保留原值，不倒推人数。

抖音曝光进房率需要同来源、同窗口、兼容口径的曝光与进房；新人60秒留存需要完整观察队列或平台正式指标。在线人数、累计观看、B站播放数均不能代替这两项。

至少两个双方独立锚点验证录屏偏移和漂移；失败区间留空。新采集与已确认同场记录按session ID＋窗口＋来源＋指标核对重复，再保存到用户选定的私人Airtable/Sheets；公开GitHub只放方法和虚构示例。

## 验收

- B站入口：本轮链接/分P已确认，取得元数据或说明实际失败，找到可复用文本或明确字幕/转写状态，身份和覆盖限制可回溯。
- Chrome入口：实际浏览器已连接、正确账号场次可读，取得至少一个真实后台指标且口径可核对；只有写完说明或规范示例不能算完成采集。
- 联合分析：时间校准、曝光/进房及新人留存能测的部分分别说明，不把一项成功扩大成全流程完成。
