# 王焓直播实验系统 V1

目标：把“凭感觉做运营”改成“假设 → 实验 → 数据 → 结论 → 下一轮实验”。

本版本优先打通三件事：

1. 画面形象实验（visual）
2. 开场 / 流量切入实验（opening）
3. 每日复盘结果（daily review）

## 一场直播的标准流程

### 1. 开始场次

```http
POST /sessions/start
```

```json
{
  "room_id": "WANGHAN_ROOM",
  "title": "王焓日常直播"
}
```

服务会把这场直播设为 active session。之后通过 `/ingest` 收到的抖音事件会同时：

- 进入实时内存统计
- 写入 SQLite
- 自动绑定 active session

### 2. 登记实验

```http
POST /experiments
```

画面实验示例：

```json
{
  "category": "visual",
  "name": "银蓝发色 + 深色竹林背景",
  "hypothesis": "提高陌生用户第一眼进房意愿",
  "target_metric": "entry_rate",
  "variables": {
    "hair": "silver-blue",
    "outfit": "cool-cyan",
    "background": "dark-bamboo",
    "brightness": "low",
    "contrast": "high"
  },
  "notes": "本场只改画面，不改开场结构"
}
```

开场实验示例：

```json
{
  "category": "opening",
  "name": "唱歌开场 + 开灯钩子",
  "hypothesis": "提高新人前段停留和关注转化",
  "target_metric": "new_viewer_1m_retention",
  "variables": {
    "opening_type": "singing",
    "light_hook": true,
    "color_change": false
  }
}
```

### 3. 把实验绑定到直播场次

```http
POST /experiments/{experiment_id}/start
```

```json
{
  "session_id": "20260930-..."
}
```

### 4. 保存实验结果

```http
PUT /experiments/{experiment_id}/result
```

```json
{
  "metrics": {
    "exposure": 421000,
    "enters": 92000,
    "entry_rate": 0.219,
    "follows": 0
  },
  "conclusion": "画面提高进房，但留人效果尚不确定",
  "decision": "iterate",
  "next_experiment": "固定画面，只改变唱歌开场"
}
```

建议 decision 只使用：

- keep：继续保留
- reject：停止该方案
- iterate：继续迭代
- inconclusive：数据不足

### 5. 保存每日复盘

```http
PUT /reviews/{session_id}
```

每日复盘固定围绕四个运营问题：

- 什么把人拉进来
- 什么把人留下来
- 什么产生互动 / 消费
- 什么地方浪费流量

并额外保存：

- 二创候选片段
- 当日发现
- 下一轮只测什么
- 数据质量与时间轴是否已对齐

## V1 数据表

- sessions：直播场次
- events：抖音实时事件
- markers：人工或系统内容节点
- transcript_segments：B站录屏转写片段
- experiments：运营实验定义
- experiment_results：实验结果
- daily_reviews：每日运营复盘

## 当前仍未自动化的部分

V1 先解决“有地方可稳定记录和关联”。

下面几项属于 V2：

1. B站录屏与抖音 session 自动对齐
2. 从事件流自动计算实验指标
3. 自动识别进房 / 留人 / 互动 / 付费异常节点
4. 自动生成二创候选 TOP N
5. 跨场次对照实验和置信度判断
6. 消费群体与复访群体拆解
