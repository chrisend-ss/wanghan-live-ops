# 新分支核心运营思路

此Skill负责战略判断、模块归类、实验设计、指标选择、复盘结论与下一轮实验。所有视觉、内容、活动以直播数据验证，不凭主观感觉拍板；除非用户明确要求，不主动写逐字稿或具体主播话术。

默认执行顺序：①电人直播画面形象＋②直播流量切入点 → ③女性向中医专场/④长线直播内容方向 → ⑤消费群体拆解/⑦粉丝粘性 → ⑥二创切片号；⑧每日直播复盘贯穿全程。

## 源文件

- [SKILL.md](../skills/wanghan-core-ops/SKILL.md)：核心决策规则及标准输出。
- [界面信息](../skills/wanghan-core-ops/agents/openai.yaml)：中文展示名与调用提示。
- [输入与指标模板](../skills/wanghan-core-ops/references/measurement.md)：分子分母、时间窗和实验记录。
- [调用示例](../skills/wanghan-core-ops/references/examples.md)：七个虚构场景与行为预期。
- [plugin.json](../plugin.json)：skills-only 私有插件包清单，不含数据接口服务。

中文展示名统一为“新分支核心运营思路”；为兼容Skill与插件命名规则，内部标识为 `wanghan-core-ops`。

## 调用

在支持Skill的客户端安装后：

```text
使用 $wanghan-core-ops 分析下面的视觉方案。
先判断所属模块和运营功能，再给变量、核心指标、验证方式、结论标准与下一步。
本轮目标是进房，只有方案，没有历史数据，不需要主播话术。
[粘贴方案]
```

```text
使用 $wanghan-core-ops 复盘这场直播。
资料：[录屏复盘/时间轴与后台数据]
按进房、留人、关系、消费、扩散识别瓶颈，区分事实和假设，设计下一轮实验。
```

输入可为直播数据、录屏复盘、视觉方案、活动方案、选题或切片方案。输出依次为：归类与判断 → 证据与缺口 → 变量 → 核心指标 → 验证方式 → 结论标准 → 结论与下一步。缺数据先给实验计划和最小补数项，不宣称效果已验证。

## 安装与私有打包

Codex个人安装：将 `skills/wanghan-core-ops/` 完整复制到个人 `~/.codex/skills/wanghan-core-ops/`，重新打开会话后检查发现与调用。此步骤不等于ChatGPT账户同步。

独立插件包仅包括下列单一顶层目录，不打包整个仓库：

```text
wanghan-core-ops/
  plugin.json
  README.md
  skills/wanghan-core-ops/
    SKILL.md
    agents/openai.yaml
    references/measurement.md
    references/examples.md
```

支持私有插件保存的环境可把该ZIP交给 `create_plugin` 注册，保存成功后通过返回的插件链接安装或启用；客户端支持与账号状态以实际结果为准。源码、打包、注册、安装与行为验证是不同状态，未成功时不得声称完成。无需新的MCP服务器，也不自动连接直播数据接口。

本仓库公开；此处只放通用规则和虚构例子，真实后台明细、用户标识与认证信息留在私有存储。插件注册为私有不改变GitHub源码的公开可见性。

## 验证

用 skill-creator 的 `quick_validate.py` 检查Skill格式；检查清单、中文展示名、相对引用与ZIP内容。用调用示例检查缺数据不判胜负、多变量不拆分归因、留存护栏、回流不可推断及明确话术请求的范围例外。文档新增不改变直播API或转写程序。
