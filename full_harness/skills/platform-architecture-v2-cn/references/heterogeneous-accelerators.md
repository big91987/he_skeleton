# 异构 AI 加速器架构

## 目录

使用目的 · 共同分析栈 · 主要设备家族 · 设备无关兼容矩阵 · 迁移裁决 · 基准可比性 · 新设备接入工作流 · 典型错误

## 使用目的

帮助 AI/ML 基础设施专家分析 GPU、TPU、NPU、LPU、HPU、Trainium/Inferentia 及未来加速器。目标是建立可验证的兼容与迁移方法，不是假装所有设备具有统一能力。

所有型号、软件版本、框架支持和性能结论都必须从厂商官方兼容矩阵和实测证据重新确认。

GPU、TPU、NPU、LPU、HPU 是生态称谓，不是可直接比较的统一技术分类。尤其 LPU 可能指不同厂商的不同架构；分析时必须先固定厂商、型号和交付形态。

## 共同分析栈

对任何设备家族按相同层级分析：

```text
模型与工作负载
→ Framework / Graph / Compiler Frontend
→ Compiler、Runtime 与 Kernel Library
→ Collective Communication 与分布式执行
→ Driver、Firmware 与 System Management
→ Device Memory、Compute、Interconnect 与 Host
→ Kubernetes Resource Exposure、Health 与 Telemetry
```

“支持 PyTorch”“支持 OpenAI API”或“支持同一模型格式”都不能证明中间层兼容。

## 主要设备家族

### NVIDIA GPU

- **核心栈**：CUDA、cuBLAS/cuDNN、NCCL、TensorRT-LLM/Runtime 生态、DCGM、GPU Operator/Device Plugin。
- **架构关注**：HBM、SM/Tensor Core、NVLink/NVSwitch、PCIe、MIG、GPUDirect/RDMA。
- **优势证据**：框架、Kernel、Runtime 和运维生态成熟度通常较高。
- **不可外推**：CUDA Kernel、NCCL 行为、MIG、NVLink 拓扑和 TensorRT 优化不是通用能力。
- **官方入口**：`https://docs.nvidia.com/`

### AMD GPU

- **核心栈**：ROCm、HIP、rocBLAS/MIOpen、RCCL、ROCm SMI、AMD GPU Operator/Device Plugin。
- **架构关注**：具体 CDNA/RDNA 型号支持、HBM、Infinity Fabric、ROCm/Kernel/OS 版本矩阵。
- **迁移重点**：CUDA 专用 Kernel、Triton/编译器支持、集合通信、镜像、Profiler 和 Runtime 后端。
- **官方入口**：`https://rocm.docs.amd.com/`

### Google TPU

- **核心栈**：XLA、PJRT、JAX、TensorFlow、PyTorch/XLA、TPU VM/GKE TPU。
- **架构关注**：编译图、静态/动态形状、Host 与 Device 数据管道、Chip/Slice/Pod 拓扑、ICI。
- **迁移重点**：模型是否可由 XLA 编译、算子覆盖、Sharding、编译时间、检查点和拓扑映射。
- **官方入口**：`https://cloud.google.com/tpu/docs`、`https://openxla.org/xla/pjrt`

### Huawei Ascend NPU

- **核心栈**：CANN、AscendCL/ACL、算子与编译工具、HCCL、MindSpore 及 PyTorch/Serving 适配生态。
- **架构关注**：具体 Ascend 型号、CANN/驱动/固件矩阵、算子覆盖、HCCS/RoCE 等互联、集群管理与遥测。
- **迁移重点**：CUDA 专用算子、模型转换、量化、HCCL、Runtime 分支、容器镜像和故障诊断。
- **官方入口**：`https://www.hiascend.com/document`

### AWS Trainium / Inferentia

- **核心栈**：AWS Neuron Compiler/Runtime、NeuronX Distributed、Neuron libraries、EFA/NeuronLink、EKS Device Plugin 或 DRA。
- **架构关注**：Trn/Inf 实例和 NeuronCore、编译缓存、模型 Fit、分布式策略、云资源供应与绑定。
- **迁移重点**：编译支持、Neuron Kernel、模型并行、实例拓扑、只能在 AWS 环境获得的控制与运维能力。
- **官方入口**：`https://awsdocs-neuron.readthedocs-hosted.com/`

### Groq LPU

- **核心栈**：编译器主导、确定性执行的推理系统；交付形态可能是 GroqCloud 或机架级系统。
- **架构关注**：目标模型支持、编译可用性、单流与批量性能、时延确定性、Scale-out、可购买/可部署形态。
- **迁移重点**：不能假设存在传统 PCIe 卡、CUDA 式 Kernel 或 Kubernetes Device Plugin；先确认是 API 服务还是自托管基础设施。
- **官方入口**：`https://groq.com/lpu-architecture`

### Intel Gaudi HPU

- **核心栈**：SynapseAI、Graph Compiler、Kernel/Library、HCCL、框架集成和 Kubernetes 设备支持。
- **架构关注**：片上内存、以太网 Scale-out、驱动/固件/SynapseAI 版本、模型参考实现。
- **迁移重点**：模型与算子覆盖、编译、HCCL、容器、Profiler 和 Runtime 后端。
- **官方入口**：`https://docs.habana.ai/`

## 设备无关的兼容矩阵

对每个“模型 × 设备 × Runtime × 拓扑”记录：

- 功能：模型架构、算子、Tokenizer、动态形状、多模态、量化；
- 精度：基线、允许误差和回归；
- 编译：首次/增量编译时间、缓存、失败诊断；
- 内存：权重、KV、激活、Workspace、碎片和卸载；
- 并行：TP/PP/DP/EP、集合通信、跨节点容错；
- 性能：TTFT、TPOT、Goodput、吞吐、尾延迟和功耗；
- 运营：驱动、固件、Runtime、镜像、升级、监控和故障隔离；
- Kubernetes：资源名/DRA、设备健康、拓扑、分区、共享和 Operator；
- 供应：交付周期、云/本地形态、地域和合同限制；
- 退出：权重、代码、Kernel、配置、数据和测试资产的迁移成本。

## 迁移裁决

稳定资产优先是：

- 模型身份、权重来源和 Tokenizer；
- 用户 API 语义与错误分类；
- 工作负载样本和负载生成器；
- 精度、性能、长稳和故障验收方法；
- 服务、用量、审计和关联标识。

通常需要重新验证：

- Kernel、量化、编译图和 Runtime 参数；
- 并行度、拓扑、通信库和批处理；
- 显存/内存模型、KV 策略和卸载；
- 驱动、固件、镜像、设备插件和遥测；
- 性能、功耗、故障行为和容量模型。

不要建立“所有设备最低公分母”接口。使用能力档案表达真实差异，例如：

```text
supported_model_families
supported_precisions
max_context_envelope
distributed_modes
device_topology
runtime_profiles
evidence_level
```

能力档案是平台内部判断依据，不应直接暴露厂商底层字段给产品用户。

## 基准可比性

跨设备比较必须固定：

- 模型、权重、精度和质量目标；
- 输入/输出长度分布、并发和到达模式；
- Server/Interactive/Offline 场景；
- TTFT、TPOT、Goodput 与尾延迟约束；
- 节点数、设备数、功耗边界和软件版本；
- 是否包含编译、冷启动、模型加载和失败请求。

峰值 Token/s、不同精度或不同质量目标的结果不可直接比较。优先使用 MLPerf 方法或等价的可复现 LoadGen。

## 新设备接入工作流

1. 确认交付形态：卡、整机、集群、云实例还是托管 API。
2. 固定硬件、驱动、固件、编译器、Runtime 和框架版本。
3. 运行最小算子、集合通信、内存、拓扑和健康测试。
4. 验证目标模型功能与精度。
5. 验证单实例、多实例、多节点和过载。
6. 验证 Kubernetes 暴露、调度、隔离、遥测和维护。
7. 执行长稳、故障、升级、回滚和重建。
8. 建立容量、成本、功耗和供应模型。
9. 形成能力档案与证据等级。
10. 只有通过退出测试后，才声称平台保持可迁移性。

## 典型错误

- 把非 NVIDIA 设备统称为“兼容 CUDA”；
- 看到 PyTorch 支持就假设全部模型可运行；
- 只比较理论 FLOPS、显存或峰值 Token/s；
- 忽略编译、算子、通信库、驱动和诊断工具；
- 把托管 LPU API 当可纳管的本地设备；
- 使用同一资源名隐藏设备能力差异；
- 未跑真实负载就承诺跨芯片迁移。
