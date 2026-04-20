# Render 部署、Redis 持久化与扩容说明

更新时间：`2026-04-20`

本文针对当前这个 `TRS demo` 的实际情况整理：

- Web 服务本身是一个 Python 进程，启动时会把较大的技能语料加载到内存里
- 现在默认的每日 `Run` 配额已经改为 `10` 次 / IP / 24 小时
- 配额后端现在支持两种模式：
  - 优先使用 `Redis` / Render Key Value
  - 如果没有配置 Redis，则回退到本地 `data/run_quota_store.json`

## 1. Redis 版配额是否持久化

结论：

- 如果你用的是 **Render Key Value 的付费实例**，那么是持久化的。
- 如果你只是重新 `deploy` Web Service，之前的配额记录仍然会保留。
- 如果你用的是 **Render Key Value Free**，则**不持久化**，重启/中断后数据可能丢失。

Render 官方文档的关键点：

- Paid Key Value 会把状态写盘，配置是 `appendfsync everysec`
- Free Key Value 不会写盘
- 如果从 Free Key Value 升级到付费，Free 上原有数据会丢失

对这个项目的含义：

- `Web Service` 重启或重新部署，不会清空 Redis 里的配额
- 只要 `TRS_DEMO_REDIS_URL` 还指向同一个付费 Key Value 实例，之前的限额计数还在
- 最多存在约 `1` 秒的数据丢失窗口

## 2. Web Service 的 instance type 和 workspace plan 有什么区别

这是两层完全不同的东西。

### A. Web Service 的 instance type

这决定的是**某一个服务实例本身**有多少算力：

- RAM
- CPU
- 单实例性能

例如你现在看到的这些：

- `Starter`: `512 MB / 0.5 CPU`
- `Standard`: `2 GB / 1 CPU`
- `Pro`: `4 GB / 2 CPU`
- `Pro Plus`: `8 GB / 4 CPU`
- `Pro Max`: `16 GB / 4 CPU`
- `Pro Ultra`: `32 GB / 8 CPU`

这属于**纵向扩容**，也就是把“单台机器”变强。

### B. Workspace plan

这决定的是**整个工作区的功能权限**，不是单个 Web Service 的硬件。

例如：

- `Hobby`
- `Professional`

它主要影响：

- 是否有 `autoscaling`
- 团队协作人数
- 带宽额度
- 环境隔离、preview environments 等平台能力

它**不会**自动把你的 Web Service 从 `2 GB / 1 CPU` 变成 `4 GB / 2 CPU`。

也就是说：

- 升级到 `Professional workspace`，不会直接提升你当前这台 Web Service 的算力
- 真正决定单实例性能的，仍然是该 Web Service 自己选的 instance type

## 3. 如果想支持高并发，到底该升级哪个

### 先说结论

如果你想让这个 demo 扛住更多并发，**优先升级 Web Service 的 instance type**。

如果你还希望在高峰期自动加机器，再考虑把 workspace 升到 `Professional` 去开 `autoscaling`。

最关键的一句话：

- `instance type` 解决的是“单实例太弱”
- `Professional workspace + autoscaling` 解决的是“需要多实例横向扩容”

二者不是替代关系，而是先后关系。

## 4. 把 workspace 升到 Professional，有没有用

有用，但用途要说清楚。

### 有什么用

`Professional` workspace 最重要的相关能力是：

- 开启 `autoscaling`
- 更多带宽
- 更多团队/环境能力

### 没什么用

如果你当前瓶颈是：

- 内存不够
- 单线程/单 CPU 太慢
- 单次 `Run` 本身太吃资源

那么**只升级 workspace 到 Professional 而不升级 Web Service instance type，帮助有限**。

因为：

- 你的单实例还是原来那点 RAM/CPU
- `autoscaling` 只是允许你开多实例，不会增强单实例

## 5. autoscaling 能不能带来高并发

可以，但有前提。

Render 官方文档说明：

- autoscaling 只在 `Professional workspace` 或更高可用
- 它按 CPU / memory utilization 在你设定的最小实例数和最大实例数之间自动扩缩
- 多实例流量会被负载均衡分发
- 每个实例按相同 instance type 单独计费

对这个项目来说，autoscaling 只有在下面条件同时满足时才真正有意义：

1. Web 服务已经足够“无状态”
2. 共享数据不再依赖本地文件
3. 没有给 Web Service 挂 persistent disk
4. 单实例本身已经不是明显瓶颈

这也是为什么这次我把配额后端加上了 Redis 支持：

- 如果仍然把限额存在本地 JSON，那么多实例时每台机器各记各的，配额会乱
- 放到 Redis 之后，多实例能共享同一份配额状态

另外 Render 文档还明确提到：

- **挂了 persistent disk 的服务不能扩成多实例**

所以对这个项目，正确方向是：

- Web Service 保持无状态
- 状态放 Redis / Postgres
- 然后再做 horizontal scaling

## 6. 当前这个项目，更应该升级哪一项

### 我的判断

当前更优先的是：

1. Web Service instance type
2. Render Key Value
3. 再考虑 workspace Professional

原因很实际：

- 这个服务启动时会把大语料读进内存
- 我之前本地测过，空载启动后内存占用就已经接近 `1 GB`
- 所以 `Standard 2 GB / 1 CPU` 只是“勉强可用”的配置，不是高并发配置

### 如果只是稳定公开演示

建议最低配置：

- Web Service：`Standard`
- Key Value：至少 `Starter`
- Workspace：`Hobby` 也可以先用

适用场景：

- 有读者访问
- 并发不高
- 你接受人工观察和必要时手动扩容

### 如果希望更稳一点、能接一定突发流量

更推荐：

- Web Service：`Pro`
- Key Value：`Starter` 或 `Standard`
- Workspace：`Professional`

原因：

- `Pro` 的 `4 GB / 2 CPU` 对这个项目更宽裕
- `Professional` 可以开 autoscaling
- Redis 持久化后，多实例共享限额没有问题

### 如果你担心“500 人同时点 Run”

我不建议按“网页访问人数”估算，而要按“同时触发 live inference 的人数”估算。

这个 demo 的重负载点不是普通页面浏览，而是：

- `/api/retrieve_skill`
- `/api/run_stream`
- 上游模型推理
- verifier 调用

即使 Render 能把 Web 层扩成多实例，真正的瓶颈还会包括：

- 上游模型 API 时延
- 上游 API 的限速
- 你的 API 成本
- 每次 `Run` 触发的多路请求与重试

所以：

- `500` 人同时打开页面，不一定有事
- `500` 人同时点 `Run`，这不是现在这套配置应该承受的目标

## 7. 1w 人陆续访问会不会有问题

“1w 人陆续访问”要分成两种情况。

### 情况 A：大多数只是浏览页面

问题不大。

静态资源和普通接口负担相对可控。

### 情况 B：很多人真的去点 Run

那问题主要会变成：

- 上游 API 总费用迅速增长
- Web Service CPU / RAM 被持续占用
- Redis / retrieval / verifier 请求数增加
- 即使有每 IP 每日 `10` 次限制，也挡不住“很多不同 IP”

所以这个限额只是**局部风控**，不是总成本上限。

如果你预计大量真实用户会反复点击，后续还应再补：

- 全站每日总调用上限
- 全站预算阈值熔断
- 更强的用户层鉴权

## 8. 对你现在这套 Render 选型的直接建议

### 如果你只想先稳住 demo

建议：

- Web Service 从 `Standard` 升到 `Pro`
- 新建一个 **付费** Render Key Value，别用 Free
- 先不急着升 workspace 到 `Professional`

这是最划算的一步，因为它会同时解决：

- 单实例内存/CPU余量
- Redis 持久化配额
- 为后续多实例扩容做准备

### 如果你已经明确要抗更高并发

建议：

- Web Service：`Pro`
- Workspace：升 `Professional`
- 开 `autoscaling`
- Key Value：付费实例
- Web Service 不挂 persistent disk

## 9. Redis 在 Render 上的落地方式

### 最简单的操作方式

1. 在 Render 里新建 `Key Value`
2. 选和 Web Service **同一区域**
3. 不要用 Free，如果你要持久化
4. 复制它的 **internal URL**
5. 在 Web Service 里设置：

```text
TRS_DEMO_REDIS_URL=<你的 internal redis://... URL>
```

6. 重新 deploy Web Service

### 部署后效果

- Web Service 会优先用 Redis 存配额
- 没有 Redis URL 时才回退到本地 JSON
- 所以部署成功后，重新 deploy Web Service 不会丢之前的限额数据

## 10. 本仓库当前已经做的改动

- 默认每日限额已改为 `10`
- 新增 Redis 配额后端支持：
  - `TRS_DEMO_REDIS_URL`
  - 兼容 `REDIS_URL`
- Docker 镜像已加入 `redis` Python 客户端依赖
- 如果未配置 Redis，仍可回退到本地 JSON

## 官方资料

- Render Pricing: https://render.com/pricing
- Scaling Render Services: https://render.com/docs/scaling
- Render Key Value: https://render.com/docs/key-value
- Persistent Disks: https://render.com/docs/disks
- Professional Features: https://render.com/docs/professional-features
- Blueprint YAML Reference: https://render.com/docs/blueprint-spec
