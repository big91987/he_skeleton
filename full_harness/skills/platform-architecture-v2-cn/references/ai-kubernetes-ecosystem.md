# Kubernetes AI Infra 生态地图

## 目录

使用目的 · 分层地图 · 常见组合模式 · 选型裁决顺序 · 典型边界错误

## 使用目的

在进入组件选择时，帮助云原生 AI 基础设施专家识别项目所处层级、责任边界、重叠区域和组合方式。此文件不是默认技术栈。

使用前必须先说明目标模块、负责、不负责、接口、质量属性和当前阶段。所有判断都要绑定具体版本及官方文档日期。

## 分层地图

### 1. 分布式计算与任务运行

#### KubeRay

- **负责**：在 Kubernetes 上管理 RayCluster、RayJob、RayService；Ray 集群生命周期、作业提交、自动扩缩、Ray Serve 图和零停机升级。
- **适用**：依赖 Ray Core/Ray Serve 的训练、批计算、数据处理或分布式推理。
- **不负责**：企业级租户、商业计量、通用模型服务协议、集群资源公平性的完整实现、底层 AI 算子。
- **关键问题**：Ray 自身调度与 Kubernetes 调度如何分层；Head/Worker 故障；Ray autoscaler 与节点扩容；RayService 升级；多节点推理拓扑。
- **官方依据**：`https://github.com/ray-project/kuberay`

### 2. 模型服务控制面

#### KServe

- **负责**：模型服务声明、生命周期、预测模型与生成式模型服务、推理协议、Runtime 集成、流量与模型装载相关能力。
- **适用**：需要标准模型服务对象、统一部署生命周期和多 Runtime 接入的 Kubernetes 推理平台。
- **不负责**：完整 MaaS 租户/鉴权/计费、芯片调度器、模型训练、所有 LLM 系统级优化。
- **关键问题**：标准模式还是 Knative 模式；InferenceService 与 LLMInferenceService 的边界；模型缓存；Runtime 支持；升级与回滚；与 Gateway、LWS、Kueue 的版本兼容。
- **官方依据**：`https://kserve.github.io/website/docs/`

#### Knative Serving

- **负责**：无状态 HTTP 服务生命周期、不可变 Revision、流量切分、并发驱动扩缩和 Scale-to-Zero。
- **适用**：冷启动可接受、服务可按请求弹性、需要 Revision 和灰度流量的通用服务或 KServe Knative 模式。
- **不负责**：模型语义、GPU 拓扑、分布式推理、KV Cache、作业队列、MaaS 治理。
- **关键问题**：模型冷启动和装载时间；Activator/Queue Proxy 路径；流式长请求；并发指标是否适合 LLM；GPU 缩零是否真的释放节点成本。
- **官方依据**：`https://knative.dev/docs/`

### 3. LLM 推理系统控制与数据面

#### AIBrix

- **负责**：面向 LLM 推理的模型元数据、LoRA 适配器、请求调度与路由、扩缩、指标和分布式推理编排等控制面与数据面能力。
- **适用**：需要在 Kubernetes 上进行 LLM 特定路由、扩缩和多节点推理系统优化。
- **不负责**：完整 MaaS 商业运营、底层推理内核、企业 IAM、通用训练平台。
- **关键问题**：Envoy Gateway 依赖；KubeRay 为可选分布式后端还是使用 StormService；Runtime 支持范围；路由指标与 SLO；组件成熟度和版本耦合。
- **官方依据**：`https://aibrix.readthedocs.io/latest/`

#### Gateway API Inference Extension

- **负责**：在 Kubernetes Gateway API 体系中表达 InferencePool，并通过 Endpoint Picker 进行模型与负载感知的端点选择。
- **适用**：需要把通用 Gateway 转化为自托管生成式模型的推理感知路由入口。
- **不负责**：API Key、租户套餐、商业限流、计量收费、模型部署生命周期和 Runtime 执行。
- **关键问题**：EPP 指标与一致性；失败回退；会话/KV 亲和；Gateway 实现兼容；与上层 MaaS Gateway 的责任分离。
- **官方依据**：`https://gateway-api-inference-extension.sigs.k8s.io/`

### 4. 多 Pod 与多机工作负载生命周期

#### LeaderWorkerSet

- **负责**：将一个 Leader 与多个 Worker 作为可复制、协同创建和协同滚动的 Pod 组管理，面向多机推理等工作负载。
- **适用**：模型跨多个节点和设备分片、需要组级身份、生命周期和故障处理。
- **不负责**：配额公平、完整作业队列、模型感知请求路由和 Runtime 内部并行。
- **关键问题**：组级失败语义；滚动升级；与 Kueue/Volcano、KServe/AIBrix 的组合；DisaggregatedSet 成熟度。
- **官方依据**：`https://lws.sigs.k8s.io/`

### 5. 作业准入、配额与公平共享

#### Kueue

- **负责**：作业开始前的 Workload 准入、Quota Reservation、ClusterQueue/LocalQueue、ResourceFlavor、Cohort 借用、公平共享、抢占、AdmissionCheck、MultiKueue 和拓扑感知准入。
- **适用**：多团队共享批任务、训练、RayJob、JobSet、LWS 等需要排队和配额治理的工作负载。
- **不负责**：普通 Pod 的最终节点打分与绑定、在线请求路由、模型 Runtime、商业计费。
- **关键区别**：Kueue 的“调度”主要是作业何时获准开始，不应与 Pod 调度器混为一谈。
- **关键问题**：名义配额与借用；公平共享；抢占受害者；ResourceFlavor；Topology-Aware Scheduling；AdmissionCheck；弹性工作负载。
- **官方依据**：`https://kueue.sigs.k8s.io/docs/`

### 6. Pod 与批工作负载调度

#### Volcano

- **负责**：Pod/Job 调度、Gang Scheduling、Queue、DRF/Proportion、公平与优先级、抢占、回收、Backfill、Binpack 和批工作负载插件。
- **适用**：训练、HPC、大数据和强协同 AI 作业需要组调度、队列和高级放置策略。
- **不负责**：模型服务生命周期、推理请求路由、MaaS 运营和 Runtime 执行。
- **关键区别**：Volcano 能进入实际 Pod 放置；Kueue更侧重作业准入与配额。二者是否组合必须基于支持矩阵和具体版本验证，不能默认互斥或默认叠加。
- **关键问题**：VCJob 与原生 Job；Gang minAvailable；Queue 与企业配额的映射；插件顺序；抢占与 Backfill；调度吞吐和故障恢复。
- **官方依据**：`https://volcano.sh/docs/`

### 7. 设备暴露与基础资源

#### Kubernetes Device Plugin 与 Dynamic Resource Allocation

- **负责**：把设备暴露为可申请资源；DRA进一步表达设备属性、Claim、分配和更丰富的设备选择。
- **适用**：GPU、NPU、TPU、Neuron 等设备纳管及拓扑、型号、分区、驱动属性参与调度。
- **不负责**：模型兼容、算子支持、性能保证和租户商业配额。
- **关键问题**：扩展资源与 DRA 的迁移；设备健康；分区和共享；拓扑；驱动/固件；厂商 Operator；故障后的 Claim 行为。
- **官方依据**：`https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/`

## 常见组合模式

| 目标 | 可能组合 | 必须验证 |
|---|---|---|
| Ray 分布式训练/推理 | KubeRay + Kueue 或专业调度器 | 双层调度、Gang、配额、扩缩、故障 |
| 标准模型服务 | KServe 标准模式或 KServe + Knative | 冷启动、Runtime、流量、缩零、模型缓存 |
| 多机 LLM 服务 | KServe/AIBrix + LWS + 调度/准入能力 | Pod 组生命周期、拓扑、路由、升级 |
| LLM 感知入口 | Gateway API Inference Extension + Runtime/Serving | EPP 指标、KV 亲和、回退、上层鉴权限流 |
| 多租户批任务 | Kueue + Kubernetes 调度器或 Volcano | 配额与节点放置的职责、抢占与公平 |
| LLM 系统优化 | AIBrix + Runtime + 可选 KubeRay/StormService | 版本、路由、扩缩、Runtime 和网络路径 |

这些是研究假设，不是推荐栈。每种组合都要验证 CRD 所有权、控制循环冲突、状态事实源、版本矩阵和故障恢复。

## 选型裁决顺序

1. 先判断在线服务、批任务、训练、分布式计算还是混合负载。
2. 再判断缺的是服务生命周期、任务运行、作业准入、Pod 放置、推理路由还是设备暴露。
3. 明确唯一事实源和控制器所有权。
4. 检查项目之间的 CRD、Webhook、调度器、Autoscaler、Gateway 和指标依赖。
5. 比较最小组合与完整组合的运维负担。
6. 固定版本做功能、性能、升级、故障和退出验证。

## 典型边界错误

- 把 KServe、AIBrix 或 KubeRay 当完整 MaaS；
- 把 Knative 当 AI 调度器；
- 把 Kueue 和 Volcano 简化为二选一的同类产品；
- 把 Gateway API Inference Extension 当商业 API Gateway；
- 把 LWS 当分布式 Runtime；
- 把 Kubernetes 设备可见性当模型兼容性；
- 因 CRD 能组合就假设控制循环可以安全共存。
