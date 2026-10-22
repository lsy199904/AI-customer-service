# Token（词元）

知识ID:KB-8837800ac6a4
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:Token（词元）

英文/别名:Token
大语言模型处理文本的基本单位。模型不直接读取字符或单词，而是将文本切分为一个个 Token 后进行编码和预测。一个 Token 可以是一个汉字、一个词、甚至一个字符片段。 经验规则：中文约 1.5～2 个字 ≈ 1 Token，英文约 4 个字符 ≈ 1 Token。
示例:输入"人工智能是大趋势"（9个汉字）≈ 5～6 个 Token
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 分词

知识ID:KB-a2ca541fa23a
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:分词

英文/别名:Tokenization
将一段文本切分为 Token 序列的过程。不同模型使用不同的分词算法（如 BPE、WordPiece、SentencePiece），同一文本在不同模型下的 Token 数可能不同。

<<<KB_SPLIT>>>

# 分词器

知识ID:KB-c70751c8d414
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:分词器

英文/别名:Tokenizer
负责执行 Tokenization 的工具组件。主流中文大模型通常自训练分词器（如 ChatGLM、Qwen、DeepSeek 等），各自的词表大小和切分粒度不同，因此 "同一句话"在不同平台的 Token 消耗不同 。
示例:百度的 ERNIE 词表约 8 万+；通义千问 Qwen 词表约 15 万+
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 词表

知识ID:KB-60a5d0867fc3
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:词表

英文/别名:Vocabulary / Vocab
分词器能识别的所有 Token 的集合。词表大小直接影响模型的 Token 覆盖率和压缩效率。中文大模型通常采用更大的词表以覆盖汉字及常见词汇组合。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# BPE 分词算法

知识ID:KB-6d7997ee594d
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:BPE 分词算法

英文/别名:Byte Pair Encoding
最主流的子词分词算法。通过统计高频字符对（byte pair）并迭代合并，逐步构建词表。GPT 系列、Qwen、DeepSeek 等均采用 BPE 或其变体。

<<<KB_SPLIT>>>

# 输入 Token

知识ID:KB-41bf5fe895bf
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:输入 Token

英文/别名:Input Tokens / Prompt Tokens
用户发送给模型的 Prompt（提示词）被编码后消耗的 Token 数。包括 System Prompt、对话历史、当前问题等所有输入内容。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 输出 Token

知识ID:KB-a862ecb24b73
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:输出 Token

英文/别名:Output Tokens / Completion Tokens
模型生成回复内容所消耗的 Token 数。 输出 Token 的单价比输入 Token 更贵 （通常为 2～4 倍），因为生成阶段涉及逐字自回归推理，计算量远大于输入编码。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 上下文窗口

知识ID:KB-1db97d1ed118
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:上下文窗口

英文/别名:Context Window
模型在单次对话中能同时处理的 Token 总量上限（输入 + 输出）。窗口越大，模型能"记住"的对话轮次越多。当前主流模型从 4K、8K 到 128K、甚至 1M Token 不等。
示例:通义千问 Qwen-Long 支持 1000 万 Token 上下文；Kimi 支持长文本 200 万字
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 最大输出长度

知识ID:KB-f2da1e3a1f1b
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:最大输出长度

英文/别名:Max Output Tokens / Max Tokens
单次请求模型最多能生成的 Token 数上限。常见值为 2048、4096、8192 等。超出则被截断，需通过续写或多轮调用补全。

<<<KB_SPLIT>>>

# 百万 Token 计价

知识ID:KB-aab34a311b8a
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:百万 Token 计价

英文/别名:Per Million Tokens Pricing
中国内地主流定价方式。以"每百万 Token"为单位报价，输入和输出分别计费。例如： "输入 0.5 元/百万 Token，输出 2 元/百万 Token" 。
示例:DeepSeek-V3：输入约 1 元/百万 Token（缓存命中 0.1 元），输出约 8 元/百万 Token
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 万 Token 计价

知识ID:KB-0baf126b7766
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:万 Token 计价

英文/别名:Per 10K Tokens Pricing
部分中国内地厂商（如百度文心、部分早期接口）也使用"每万 Token"作为计价单位。1 百万 Token = 100 万 Token。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# TPM

知识ID:KB-22ec8ed1c74f
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:TPM

英文/别名:Tokens Per Minute
每分钟 Token 吞吐量上限。API 平台对单个账户/API Key 设置的限流指标，超出则返回 429 错误。TPM 越大，支持的并发和吞吐越高。

<<<KB_SPLIT>>>

# RPM

知识ID:KB-86748c5b7a86
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:RPM

英文/别名:Requests Per Minute
每分钟请求次数上限。与 TPM 不同，RPM 限制的是请求频率而非 Token 量。高频短请求场景需关注 RPM 限制。

<<<KB_SPLIT>>>

# TPS

知识ID:KB-470ccff16bcd
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:TPS

英文/别名:Tokens Per Second
每秒生成的 Token 数，衡量模型推理速度。TPS 越高，用户等待时间越短。当前主流模型 TPS 在 20～100+ Token/s。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# QPS

知识ID:KB-1e9d8cb8af48
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:QPS

英文/别名:Queries Per Second
每秒请求查询次数。常用于评估 API 服务端吞吐能力。在 LLM 场景中通常不等同于 TPS，因为一次请求可能生成数百个 Token。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 缓存命中

知识ID:KB-6b3eef890774
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:缓存命中

英文/别名:Cache Hit
当请求中的前缀部分命中服务端缓存时，该部分输入 Token 以更低价格计费（通常为正常价的 10%～50%）。DeepSeek、通义千问等均支持此机制，可大幅降低重复 Prompt 的成本。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 免费额度

知识ID:KB-e4c0f2f6e4f5
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:免费额度

英文/别名:Free Quota / Free Tier
中国内地 API 平台为新用户或开发者提供的免费 Token 额度。如百度千帆、阿里百炼、讯飞星火等均有赠送机制。
示例:阿里百炼：新用户赠送 100 万 Token 免费额度
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# Token 余额

知识ID:KB-9adece7f02e7
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:Token 余额

英文/别名:Token Balance / Remaining Tokens
账户中剩余可用 Token 数。部分平台以"Token"直接计费扣减，而非按金额计费。

<<<KB_SPLIT>>>

# 上下文长度

知识ID:KB-080317ded286
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:上下文长度

英文/别名:Context Length
模型在单次推理中可处理的最大 Token 数。包括输入和输出。主流值：4K、8K、32K、128K、256K、1M 等。中国内地主流模型如 Qwen（128K）、DeepSeek（128K）、Kimi（200万字≈300K+ Token）。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 上下文溢出

知识ID:KB-ea283da53edb
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:上下文溢出

英文/别名:Context Overflow
当输入 Token 数超过模型上下文窗口时，平台通常会截断最早的对话内容。会导致模型"忘记"早期信息，是多轮对话中常见问题。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# Token 压缩

知识ID:KB-2f5a29235da4
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:Token 压缩

英文/别名:Token Compression
通过摘要、裁剪、嵌入检索等手段减少对话历史中的 Token 数，以便在有限上下文窗口中保留更多信息。常见于智能体（Agent）多轮对话管理。

<<<KB_SPLIT>>>

# 多模态 Token

知识ID:KB-4eeab93b55d8
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:多模态 Token

英文/别名:Multimodal Tokens
多模态模型（如 Qwen-VL、文心一格）中，图像、音频等非文本输入也被转换为 Token 进行处理。 通常一张图片约消耗数百至数千 Token ，取决于分辨率和模型。
示例:Qwen-VL：一张 1080p 图片约消耗 1000+ Token
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# System Prompt Token

知识ID:KB-a036ba0fefc0
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:System Prompt Token

英文/别名:System Prompt Tokens
系统提示词所消耗的 Token。System Prompt 在每次请求中都会被重复发送，因此其 Token 数直接影响调用成本。优化 System Prompt 长度是降低成本的常见手段。

<<<KB_SPLIT>>>

# 推理 Token / 思维链 Token

知识ID:KB-1f1cde219e9d
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:推理 Token / 思维链 Token

英文/别名:Reasoning Tokens / Chain-of-Thought Tokens
推理型模型（如 DeepSeek-R1、Qwen-QwQ）在生成最终回答前，内部产生的思维链推理过程所消耗的 Token。 推理 Token 也参与计费 ，且不可见于用户输出，是推理模型的特殊成本项。
示例:DeepSeek-R1 的思维链通常比最终回答消耗更多 Token
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# KV Cache（键值缓存）

知识ID:KB-79d65d0c32bc
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:KV Cache（键值缓存）

英文/别名:Key-Value Cache
推理过程中缓存已计算的注意力键值对，避免对已处理 Token 的重复计算。 KV Cache 是自回归推理速度的核心优化 ，其显存占用与上下文长度成正比。

<<<KB_SPLIT>>>

# Prefix Caching（前缀缓存）

知识ID:KB-f1746b8142c7
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:Prefix Caching（前缀缓存）

英文/别名:Prefix Caching / Prompt Caching
将请求中相同的固定前缀（如 System Prompt、Few-shot 示例）的 KV Cache 进行复用，避免重复计算。 DeepSeek 的缓存命中计费优惠即基于此技术。

<<<KB_SPLIT>>>

# Prefill（预填充）

知识ID:KB-4799a15e7b9e
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:Prefill（预填充）

英文/别名:Prefill Phase
推理的第一阶段，模型并行处理所有输入 Token 生成初始 KV Cache。Prefill 阶段的计算量与输入 Token 数成正比，决定了首 Token 延迟（TTFT）。

<<<KB_SPLIT>>>

# Decode（解码阶段）

知识ID:KB-5de815732230
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:Decode（解码阶段）

英文/别名:Decode Phase
推理的第二阶段，模型逐个 Token 自回归生成。Decode 阶段受限于内存带宽，是推理速度的瓶颈所在。

<<<KB_SPLIT>>>

# TTFT（首 Token 延迟）

知识ID:KB-0e145319347d
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:TTFT（首 Token 延迟）

英文/别名:Time To First Token
从发送请求到模型返回第一个 Token 的时间。TTFT 主要受 Prefill 阶段和排队等待影响。中国内地厂商通常优化至 0.5～2 秒。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# TPOT（每 Token 生成时间）

知识ID:KB-180b6c43b784
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:TPOT（每 Token 生成时间）

英文/别名:Time Per Output Token
生成阶段每个 Token 的平均耗时。TPOT 越低，输出流式呈现越流畅。通常在 10～50ms/Token。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 批处理

知识ID:KB-80a0f17e58b4
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:批处理

英文/别名:Batching / Continuous Batching
将多个并发请求的 Token 合并为一个 Batch 进行并行推理，提升 GPU 利用率。连续批处理（Continuous Batching）是当前主流推理框架（如 vLLM、TensorRT-LLM）的核心特性。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 量化

知识ID:KB-b4ec974c9d4f
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:量化

英文/别名:Quantization
将模型参数从高精度（FP16/FP32）压缩为低精度（INT8/INT4 等），降低显存占用和计算成本。量化后 每 Token 推理成本可降低 2～4 倍 ，是国产模型降本的重要手段。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 投机采样

知识ID:KB-04b04c2c3970
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:投机采样

英文/别名:Speculative Decoding
使用小模型快速生成草稿 Token，再由大模型验证和修正，以减少大模型的逐 Token 解码次数。 可将推理速度提升 2～3 倍 。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 算力

知识ID:KB-a0b2c1c294be
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:算力

英文/别名:Compute / Computing Power
中国内地 AI 行业最核心的词汇之一，指 GPU/AI 芯片的计算能力。"算力"是 Token 生成的基础资源，中国内地强调"算力即国力"。主要提供方包括华为昇腾、寒武纪、海光等国产芯片厂商。

<<<KB_SPLIT>>>

# 算力卡

知识ID:KB-d332db9042af
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:算力卡

英文/别名:AI Accelerator Card / GPU Card
中国内地对 AI 加速芯片（GPU/NPU）的俗称。包括进口的 NVIDIA A100/H100 和国产的华为昇腾 910B、寒武纪思元等。受出口管制影响， "国产算力卡替代"是内地 AI 行业的热门话题 。

<<<KB_SPLIT>>>

# 国产大模型

知识ID:KB-629f33dc8c14
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:国产大模型

英文/别名:Domestic LLM
中国内地自主研发的大语言模型。主流包括：百度文心（ERNIE）、阿里通义千问（Qwen）、华为盘古、讯飞星火、智谱 ChatGLM、百川 Baichuan、DeepSeek、月之暗面 Kimi、MiniMax 等。每家 Token 定价和分词体系不同。

<<<KB_SPLIT>>>

# MaaS（模型即服务）

知识ID:KB-0c8a228bb43e
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:MaaS（模型即服务）

英文/别名:Model as a Service
中国内地主流的商业模式。模型厂商通过 API 方式对外提供大模型推理服务，按 Token 计费。代表平台：阿里百炼、百度千帆、腾讯混元、讯飞开放平台等。

<<<KB_SPLIT>>>

# 模型备案

知识ID:KB-23887dd85619
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:模型备案

英文/别名:Model Filing / Registration
中国内地的 《生成式人工智能服务管理暂行办法》 要求，面向公众提供生成式 AI 服务需向网信办备案。模型备案是 API 服务上线的前置条件。截至 2025 年已有数百个模型完成备案。

<<<KB_SPLIT>>>

# 模型微调

知识ID:KB-34459f531e75
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:模型微调

英文/别名:Fine-tuning
在基础模型上使用行业数据进行二次训练，使模型更适配特定场景。中国内地厂商普遍提供微调服务，部分按 Token 或按训练时长计费。微调后模型的 Token 计价与基础模型不同。

<<<KB_SPLIT>>>

# 国产算力

知识ID:KB-88e11ac09974
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:国产算力

英文/别名:Domestic Compute
使用中国内地自研 AI 芯片进行 Token 推理和训练。在出口管制背景下，华为昇腾（Ascend）、寒武纪、海光等国产芯片成为重要替代方案。 适配国产算力是当前中国 AI 企业的核心挑战之一 。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 信创

知识ID:KB-a0a9f3bc1625
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:信创

英文/别名:Information Technology Application Innovation
即"信息技术应用创新"，指在关键领域使用国产化软硬件替代进口产品。AI 领域的信创要求模型推理（Token 生成）在国产芯片 + 国产框架上完成，如华为 CANN + MindSpore 生态。

<<<KB_SPLIT>>>

# 模型一体机

知识ID:KB-1c2c5d333ca3
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:模型一体机

英文/别名:Model Appliance / All-in-One Machine
将大模型与国产算力硬件打包销售的私有化部署方案。企业购买后即可在本地生成 Token，无需通过 API 调用。华为、浪潮、联想等均有相关产品。

<<<KB_SPLIT>>>

# Token 消耗量

知识ID:KB-b0cdce32e221
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:Token 消耗量

英文/别名:Token Consumption
中国内地政企客户评估 AI 使用成本时的核心指标。通常按月统计 Token 消耗量，并据此调整 API 额度预算和模型选型。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 百模大战

知识ID:KB-cec82ab42e47
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:百模大战

英文/别名:Hundred-Model War
中国内地 AI 行业对 2023～2024 年间大量企业争相发布大模型这一现象的俗称。各模型在 Token 定价、上下文长度、推理速度等维度激烈竞争，推动 Token 单价快速下降。

<<<KB_SPLIT>>>

# tokens/秒

知识ID:KB-e0f8cc5ffb4b
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:tokens/秒

英文/别名:tokens/s
中国内地厂商宣传模型推理速度时最常用的指标。通常指单请求场景下的 Token 生成速率，与并发吞吐（throughput）不同，选型时需注意区分。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 提示词

知识ID:KB-ba36b295840d
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:提示词

英文/别名:Prompt
用户发送给模型的输入文本，被编码为输入 Token。 提示词越长，消耗的输入 Token 越多 ，但不一定带来更好的效果——冗余信息可能干扰模型注意力。

<<<KB_SPLIT>>>

# 系统提示词

知识ID:KB-3fafb6aa73e3
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:系统提示词

英文/别名:System Prompt
在对话开始时设定的全局指令。每次 API 请求都会携带，因此其 Token 数会持续累积成本。最佳实践是精简 System Prompt，避免冗长描述。

<<<KB_SPLIT>>>

# 少样本提示

知识ID:KB-9c5412c0ad0a
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:少样本提示

英文/别名:Few-shot Prompting
在 Prompt 中提供少量示例以引导模型输出格式和风格。每个示例都会消耗 Token，因此需要在示例数量和 Token 成本之间取舍。

<<<KB_SPLIT>>>

# 思维链

知识ID:KB-0d326b210cdc
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:思维链

英文/别名:Chain-of-Thought (CoT)
引导模型逐步推理的提示技术。CoT 会 显著增加输出 Token 数 （因为模型需要生成推理过程），但能提升复杂问题的准确率。推理型模型如 DeepSeek-R1 内置了 CoT 能力。

<<<KB_SPLIT>>>

# Token 预算

知识ID:KB-d665314f530c
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:Token 预算

英文/别名:Token Budget
为单次请求或单次会话设定的 Token 上限。开发者需要在 Token 预算内合理分配 System Prompt、Few-shot 示例和用户输入的空间。

<<<KB_SPLIT>>>

# 上下文管理

知识ID:KB-3937413b4030
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:上下文管理

英文/别名:Context Management
在多轮对话中管理 Token 消耗的技术。包括对话历史裁剪、摘要压缩、滑动窗口等策略，确保总 Token 数不超过模型的上下文窗口。

<<<KB_SPLIT>>>

# 检索增强生成

知识ID:KB-e38c7df74e63
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:检索增强生成

英文/别名:Retrieval-Augmented Generation (RAG)
从外部知识库检索相关内容并注入 Prompt 的技术。 RAG 会增加输入 Token 数 （因为检索到的文档片段被拼入 Prompt），但可让模型获取最新信息，减少幻觉。中国内地企业落地大模型时最常用的架构模式之一。

<<<KB_SPLIT>>>

# 截断

知识ID:KB-bd40a2a76318
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:截断

英文/别名:Truncation
当输入 Token 超过上下文窗口时，API 平台自动丢弃最早的消息或截断长文本。不同平台的截断策略不同（按 Token 数、按消息轮次等）。

<<<KB_SPLIT>>>

# 流式输出

知识ID:KB-9ec4c5e1548d
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:流式输出

英文/别名:Streaming / Stream Mode
模型生成 Token 后逐步返回（而非等待全部生成完毕），用户可实时看到输出。 流式输出不影响 Token 总数和计费 ，仅影响传输方式和用户体验。几乎所有中国内地 API 平台均支持此模式。

<<<KB_SPLIT>>>

# 火山方舟

知识ID:KB-f6de9356aa83
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:火山方舟

英文/别名:Volcano Ark
火山引擎旗下的大模型服务平台，提供模型推理、评测、精调等全流程服务。方舟搭载豆包及业界主流大模型，以 API 方式对外提供 Token 推理服务，是字节跳动 AI 能力的核心输出窗口。

<<<KB_SPLIT>>>

# 豆包大模型

知识ID:KB-48b62484570d
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:豆包大模型

英文/别名:Doubao Model
字节跳动自研的大语言模型系列，火山方舟的主力模型。包括豆包 Seed 系列（旗舰）、Doubao-1.5-lite（轻量版）、Doubao-Seed-Evolving（持续迭代版）等。各版本的 Token 定价、上下文窗口、能力支持均不同。
示例:Doubao-Seed-Evolving：输入 6 元/百万 Token，输出 30 元/百万 Token，上下文窗口 1024K
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 推理输入 / prompt_token

知识ID:KB-8de00649e89f
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:推理输入 / prompt_token

英文/别名:prompt_token
火山方舟对"输入 Token"的官方计费术语。将推理输入的内容（包括但不限于文字、图片）转化为 Token 数进行计费，对应 prompt_token 。多模态输入中的图片也按此计费。

<<<KB_SPLIT>>>

# 推理输出 / completion_token

知识ID:KB-defe8b7aaf00
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:推理输出 / completion_token

英文/别名:completion_token
火山方舟对"输出 Token"的官方计费术语。将推理输出的内容转化为 Token 数进行计费，对应 completion_token 。输出单价通常显著高于输入单价。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 输入长度定档计价

知识ID:KB-5f4e1778640f
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:输入长度定档计价

英文/别名:Input Length Tiered Pricing
火山方舟部分模型（如豆包 1.8）采用的特殊计费方式。 输入和输出单价随输入 Token 长度分档递增 。例如输入 0～32K 档最便宜，128～256K 档最贵。这是火山引擎特有的阶梯定价模式。
示例:豆包 1.8：输入 0-32K 档输入单价 0.8 元/百万 Token；128-256K 档输入单价 2.4 元/百万 Token
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 缓存命中 / cached_token

知识ID:KB-931b5b33450f
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:缓存命中 / cached_token

英文/别名:cached_token
火山方舟上下文缓存功能的核心计费项。当请求前缀命中 Cache 时，被命中的 Token 按 cached_token 计费，价格低于 prompt_token 单价（通常为 2 折）。批量推理场景下缓存命中价为 prompt_token 单价的 4 折。
示例:Doubao-1.5-lite：正常输入 0.3 元/百万 Token，缓存命中仅 0.06 元/百万 Token
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 缓存存储

知识ID:KB-05648e2d5e06
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:缓存存储

英文/别名:Cache Storage
火山方舟上下文缓存产生的存储费用。 按小时计费 ，基于每个自然小时内存储的最大 Token 数。与缓存命中（折价推理）不同，缓存存储是独立的存储费用项。
示例:Doubao-1.5-lite 缓存存储：0.017 元/百万 Token/小时
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 显式缓存

知识ID:KB-6a4980b45a84
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:显式缓存

英文/别名:Explicit Cache / Context API
火山方舟提供的上下文缓存模式之一。开发者通过 Context API 主动创建和管理缓存，可显式控制哪些内容被缓存。 适用于固定长篇上下文场景 （如长文档问答、固定 System Prompt）。

<<<KB_SPLIT>>>

# 隐式缓存

知识ID:KB-0edcc06ef9c4
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:隐式缓存

英文/别名:Implicit Cache / Transparent Cache
火山方舟提供的上下文缓存模式之一。系统自动判断请求前缀是否命中已有缓存，无需开发者主动管理。 批量推理场景下使用透明缓存 ，命中部分按 4 折计费。

<<<KB_SPLIT>>>

# TPM 保障包

知识ID:KB-ce30e782e0d8
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:TPM 保障包

英文/别名:TPM Guarantee Package
火山方舟特有的计费方式。购买特定模型及版本的 "TPM 额度" ，平台预留资源保障并发能力达到约定 TPM。 按天预付费或按小时后付费 ，不调用也会收费。适合生产级别、流量可预估的在线业务。与按 Token 后付费的区别：TPM 保障包承诺并发能力，按 Token 后付费不对 TPM 进行承诺。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 模型单元

知识ID:KB-646431d6dac7
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:模型单元

英文/别名:Model Unit
火山方舟最高级别的计费方式。提供 独占算力 ，对精调后模型表现更优。按"个"购买模型单元，按月预付费或按小时后付费。分为方舟模型单元 A/B/C/D 型，不同型号对应不同算力资源。适合对算力确定性要求极高的生产业务。

<<<KB_SPLIT>>>

# 准实时计费出账

知识ID:KB-c46b1754e729
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:准实时计费出账

英文/别名:Near Real-Time Billing
火山方舟特有的出账模式。 每 5 分钟出具上一计费周期费用账单 ，出账时间通常在周期结束后 5～10 分钟。部分模型（如 Seedance 系列）已缩短至 30 秒出账。与按小时计费出账（1～2 小时延迟）形成对比。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 推理限额

知识ID:KB-4c5cdbc227b1
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:推理限额

英文/别名:Inference Quota Limit
火山方舟的费用控制功能。为模型设置 Token 消耗上限，当调用量达到限额后平台自动关停对应服务， 避免推账、关停延迟带来的额外花销 。适合需要严格控制费用预期的场景。

<<<KB_SPLIT>>>

# 深度思考

知识ID:KB-15389a6f1e0f
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:深度思考

英文/别名:Deep Thinking / Thinking Mode
火山方舟豆包模型的推理能力。通过 thinking 参数 控制是否开启深度思考模式，支持 minimal、low、medium、high 四种模式调节思考长度。思维链内容参与 Token 计费，并可通过 reasoning_effort 参数控制推理力度。
示例:豆包 1.8：最大思维链内容长度 32K Token，最大输出长度 64K Token

<<<KB_SPLIT>>>

# 结构化输出

知识ID:KB-738bed9c917f
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:结构化输出

英文/别名:Structured Output
火山方舟模型能力之一，支持模型按照指定 JSON Schema 格式输出结果，确保输出可被程序直接解析。与 Function Calling 配合使用时，默认启用 JSON 模式提高输出合法率，支持 strict 模式 。

<<<KB_SPLIT>>>

# 函数调用

知识ID:KB-de97def3d8ef
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:函数调用

英文/别名:Function Calling
火山方舟模型能力之一。模型可根据用户意图自动生成函数调用指令（tool_calls），并返回 reasoning_content（思维链内容）。 开启深度思考的函数调用场景中，历史轮次的思维链内容按需参与推理，会增加输入 Token 数 。

<<<KB_SPLIT>>>

# 上下文编辑

知识ID:KB-5b173344e211
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:上下文编辑

英文/别名:Context Management / Context Editing
火山方舟特有的上下文管理功能。支持 自动管理上下文中的思考块（clear_thinking）及工具结果内容（clear_tool_uses） ，保持上下文在模型窗口限制内，并与缓存功能协同工作。
示例:配置 clear_thinking 保留最近 1 轮思维链；配置 clear_tool_uses 在工具调用超过 30 次时清除保留最近 20 次

<<<KB_SPLIT>>>

# 视觉 Token 优化

知识ID:KB-ef80e20e950d
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:视觉 Token 优化

英文/别名:Visual Token Optimization
火山方舟豆包 1.8 模型的视觉编码升级。 400 万像素以内的图片 Token 用量降至 44.4% ，可处理更长视频（最大抽帧数从 640 提升至 1280）。这是火山引擎在多模态 Token 效率方面的特色优化。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 全量精调

知识ID:KB-b5d5e3ccb7ca
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:全量精调

英文/别名:Full Fine-tuning
火山方舟精调方式之一。更新模型全部权重参数，效果上限高但成本高。 精调后推理成本为基础模型的 2～2.5 倍 （按 Token 计费时）。全量精调产物可直接用于模型单元独占部署。
示例:Doubao-1.5-lite 全量精调：60 元/百万 Token
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# LoRA 精调

知识ID:KB-c17895dfbc7a
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:LoRA 精调

英文/别名:LoRA Fine-tuning
火山方舟精调方式之一。冻结预训练模型全部权重，注入低秩适配层（Low-Rank Adaptation），大幅减少可训练参数。 训练成本远低于全量精调，效果可达全量精调 98% 以上 。LoRA 精调后按 Token 推理价格为基础模型的 2 倍。
示例:Doubao-1.5-lite LoRA 精调：30 元/百万 Token；精调后推理输入 0.75 元/百万 Token
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 按 Token 精调计费

知识ID:KB-baa8f3397168
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:按 Token 精调计费

英文/别名:Per-Token Fine-tuning Billing
火山方舟精调计费方式之一。 训练费用 = 总 Token 数 × 精调单价 =（训练集 Token 数 + 混入 Token 数 + 验证集 Token 数）× 迭代轮次 × 精调 Token 单价 。若 Token 数小于 1000，将上取整为 1000 Token 计算。

<<<KB_SPLIT>>>

# 按算力精调计费

知识ID:KB-0f69be99d635
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:按算力精调计费

英文/别名:Per-Compute Fine-tuning Billing
火山方舟精调计费方式之一。 训练费用 = 部署模板小时单价 × 计费小时数 ，按模型训练占用模型单元的有效时长计费。仅对"有效训练"计费——数据预处理、训练排队、训练完成等阶段不计费。

<<<KB_SPLIT>>>

# DPO（直接偏好优化）

知识ID:KB-b814b4270078
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:DPO（直接偏好优化）

英文/别名:Direct Preference Optimization
火山方舟支持的精调方法之一。基于用户反馈的偏好对比数据（A/B 选择），低成本拟合用户偏好。 相比 SFT 优化偏好成本更低，相比 RL 无需构建奖励模型 。最小数据需求为百条以上偏好对比数据。

<<<KB_SPLIT>>>

# CPT（继续预训练）

知识ID:KB-fced0ca20bb8
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:CPT（继续预训练）

英文/别名:Continual Pre-Training
火山方舟支持的精调方法之一。使用未标注数据在基础模型上继续预训练， 增强行业/垂直领域知识 。最小数据需求为一千万 Token 以上，数据量需求大但对数据质量也有要求。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# GRPO / PPO / DAPO（强化学习精调）

知识ID:KB-2bd423d420b5
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:GRPO / PPO / DAPO（强化学习精调）

英文/别名:Reinforcement Learning Fine-tuning
火山方舟支持的强化学习精调方法。包括 GRPO、PPO、DAPO 等算法，效果上限高、泛化好。 需要构建并调优 Reward 函数 ，对算法能力要求较高。最小数据需求为百条以上 prompt 集。RL 精调不支持音频输入。

<<<KB_SPLIT>>>

# SFT（有监督微调）

知识ID:KB-56797173a843
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:SFT（有监督微调）

英文/别名:Supervised Fine-Tuning
火山方舟默认推荐的精调方法。使用标注数据（prompt+response 问答对）进行有监督训练，拟合样本回答，针对性强、效果可控。最小数据需求为数百条以上。支持全量和 LoRA 两种训练方式。

<<<KB_SPLIT>>>

# 批量推理

知识ID:KB-68852a18a774
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:批量推理

英文/别名:Batch Inference / Batch API
火山方舟提供的离线推理模式。将请求以批量任务方式提交，使用夜间闲时资源推理， 成本低于在线推理 （输入/输出约为在线推理 5 折）。白天在线高峰期可能无进度。批量推理支持缓存命中（4 折），但不支持免费额度抵扣。
示例:Doubao-1.5-lite 批量推理：输入 0.15 元/百万 Token（在线推理 0.3 元的 5 折）
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 分词 API

知识ID:KB-11994a37162c
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:分词 API

英文/别名:Tokenization API
火山方舟提供的独立分词接口（ /api/v3/tokenization ）。对输入文本进行分词，返回每个 Token 的 ID 和偏移量。 仅支持文本输入 ，可用于预估 Token 消耗量和成本预算。

<<<KB_SPLIT>>>

# Responses API

知识ID:KB-367830127b03
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:Responses API

英文/别名:Responses API
火山方舟新推出的 API 接口，推荐新业务使用。支持 previous_response_id 参数，平台自动保存历史对话上下文并在多轮交互中回传给推理服务，无需用户自行管理上下文 Token。与 Chat API 相比，简化了多轮对话的 Token 管理。

<<<KB_SPLIT>>>

# 续写模式

知识ID:KB-b09aed7accd8
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:续写模式

英文/别名:Prefill Response
火山方舟特有的推理模式。允许用户在请求中提供部分输出内容作为前缀（Prefill），模型基于此前缀续写剩余内容。 可减少重复生成已确定内容的 Token 消耗 ，适用于续写、补全等场景。

<<<KB_SPLIT>>>

# IPM

知识ID:KB-d8ee662ee75e
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:IPM

英文/别名:Images Per Minute
火山方舟对图像生成模型的限流指标。每分钟可生成的图片数量上限，类似于文本模型的 RPM。不同模型的 IPM 限制不同。
示例:Doubao-Seedream-5.0-pro：IPM 500

<<<KB_SPLIT>>>

# AICC（AI 机密计算）

知识ID:KB-dc1e84e0b09f
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:AICC（AI 机密计算）

英文/别名:Artificial Intelligence Confidential Computing
火山引擎 Jeddak AICC 是面向大模型场景的机密计算平台。通过芯片级全链路加密，实现大模型推理和数据传输全过程的隐私保护，确保敏感数据 "数据可用不可见" 。火山方舟上的所有模型均可通过 MaaS on AICC 一键开启机密推理服务。适用于金融、政务、法务等高度敏感数据场景。
示例:Doubao-seed-2.0-pro-AICC 机密模型：按 Token 后付费，输入 6.4 元/百万 Token（普通版 6 元），溢价约 7%
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# 机密 Token（词元）工厂

知识ID:KB-34d1c3407d9e
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:机密 Token（词元）工厂

英文/别名:Confidential Token Factory
火山引擎与中国移动智算中心联合打造的产业模式。依托万卡级国产智算集群，在 TEE 可信执行环境中生产 Token， 实现大模型推理和数据传输全过程加密、全流程可追溯 。以 Token（词元）为标准计量单位，算力生产与结算全流程在园区内闭环完成。全国最大机密 Token 工厂已于 2026 年 8 月落地内蒙古和林格尔新区。
示例:核心特征："数据进不来、模型拿不走、过程可追溯"
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# TEE（可信执行环境）

知识ID:KB-0f6f02d7f4aa
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:TEE（可信执行环境）

英文/别名:Trusted Execution Environment
机密计算的核心技术载体。通过硬件级安全机制，将安全边界从"机房围墙"下沉到"计算内核"。 对内存进行加密，并保护寄存器状态和运行时上下文 ，在整个 Token 推理过程中为敏感数据提供隔离与防护。即便底层基础设施遭到入侵，数据依然不会被窃取或篡改。火山方舟的机密部署方案即基于 TEE 技术构建。

<<<KB_SPLIT>>>

# 机密部署 / 机密推理

知识ID:KB-90a2ce7f20bf
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:机密部署 / 机密推理

英文/别名:Confidential Deployment / Confidential Inference
火山方舟提供的 MaaS 原生机密推理服务。用户在创建推理接入点时选择"机密部署"即可一键开启，Token 生成全流程在 TEE 环境中完成。核心特性： ① 芯片级安全隔离 （从 GPU/CPU 到容器全链路隔离）； ② 端到端数据保护 （Prompt、Response 仅在 TEE 内部可见）； ③ 可验证透明信任 （提供远程证明报告供用户离线验证）。
示例:机密推理支持的模型：Doubao-seed-2.0-pro-AICC、Doubao-seed-2.0-lite-AICC、DeepSeek-V4-pro-AICC、GLM-5.1-AICC 等

<<<KB_SPLIT>>>

# 远程证明

知识ID:KB-f90af598e97b
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:远程证明

英文/别名:Remote Attestation (RA)
火山方舟机密部署的核心信任机制。机密部署完成后，平台提供 可下载的远程证明报告 ，用户可使用离线工具手动解析和验证该报告，以验证机密推理部署运行环境的可信性。实现从"契约信任"到 "技术可验证信任" 的转变。
适用边界:本条为原词典的通用解释或估算,不能作为特定模型的精确 Token 数、价格、上下文或服务政策;以实际分词器、模型规格及账单为准。

<<<KB_SPLIT>>>

# PD 分离

知识ID:KB-cde63ae66b7e
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:PD 分离

英文/别名:Prefill-Decode Disaggregation
火山方舟机密推理服务默认支持的高性能推理框架。将 Token 生成的 Prefill（预填充）阶段和 Decode（解码）阶段分离部署到不同计算节点， 在提供更高等级安全防护的同时保证推理效率 。这是机密计算与推理优化的结合点。

<<<KB_SPLIT>>>

# 机密模型资源包

知识ID:KB-e5012abc7c0c
产品:通用AI术语
版本:原文件未标注版本
适用对象:customer
状态:source_based
来源:8.AI_Token术语词典.html | HTML术语卡片:机密模型资源包

英文/别名:Confidential Model Resource Package
火山引擎为 AICC 机密模型提供的预付费资源包。按 Token 量购买，有效期 3～12 个月。支持抵扣豆包大模型-AICC 版和开源大模型-AICC 版的机密推理 Token 消耗。
示例:Doubao-seed-2.0-pro 机密模型：1 亿 Token 资源包 2800 元（有效期 3 个月）
