---
name: vector-storage
description: 向量存储场景。指导模型进行向量数据库设计时的思考过程，包括向量表示、索引选择、相似度查询和混合检索策略。
version: 1.0.0
author: Agent Team
tags: [vector, embedding, similarity, pinecone, milvus, faiss]
---

# 向量存储场景思维指南

## 思考框架

当你需要使用向量存储时，按以下流程思考：

### 1. 确认是否需要向量存储

**向量存储适用场景**
```
需要向量存储的情况
│
├─ 语义搜索（理解意图而非关键词匹配）
│   └── 搜索"如何学习编程" 能找到"Python入门教程"
│
├─ 相似性检索（找相似的）
│   └── 推荐相似商品、相似文章、相似图片
│
├─ RAG（检索增强生成）
│   └── 从知识库检索相关文档增强 LLM 回答
│
├─ 去重/重复检测
│   └── 检测重复内容、抄袭识别
│
└─ 分类/聚类
    └── 用户分群、内容分类
```

**不需要向量存储的情况**
```python
# ✗ 不需要向量存储的情况
├── 精确匹配查询（用传统数据库）
├── 简单关键词搜索（用 Elasticsearch）
├── 事务性操作（用关系数据库）
└── 结构化数据分析（用 SQL）
```

### 2. 向量表示选择

**文本向量化方法**
```
文本 → 向量

├─ OpenAI text-embedding-ada-002
│   └── 1536 维，成本低，效果好
│
├─ OpenAI text-embedding-3-small/large
│   └── 更小/更大维度，可调
│
├─ BGE (BAAI)
│   └── 中英文效果好，开源
│
├─ M3E (WangXiaoxuan)
│   └── 中文效果好，开源
│
├─ Cohere
│   └── 企业级服务，多语言
│
└─ 本地模型
    └── HuggingFace 各种模型
```

**向量维度选择**
```
维度 vs 效果 vs 性能

┌─────────┬──────────┬──────────┬──────────┐
│  维度   │   效果   │   内存   │  速度    │
├─────────┼──────────┼──────────┼──────────┤
│   256   │   较低   │   最低   │   最快   │
│   512   │   中等   │   低     │   快     │
│   768   │   较好   │   中     │   中     │
│  1024   │   好     │   高     │   慢     │
│  1536   │   很好   │   很高   │   很慢   │
│  3072   │   极好   │   极高   │   最慢   │
└─────────┴──────────┴──────────┴──────────┘

建议：
├── 通用场景：768 或 1024
├── 资源受限：512
├── 追求质量：1536
└── 可调参数：根据效果反馈调整
```

**向量化最佳实践**
```python
# 分块策略
CHUNK_STRATEGIES = {
    # 固定大小分块（简单但可能切断语义）
    "fixed": {
        "chunk_size": 1000,
        "chunk_overlap": 100  # 重叠保持上下文
    },
    
    # 句子级别分块（保留完整句子）
    "sentence": {
        "chunk_size": 5,
        "chunk_overlap": 1
    },
    
    # 段落级别分块（推荐）
    "paragraph": {
        "chunk_size": None,  # 按段落自然分割
        "max_chunk_size": 1500
    },
    
    # 递归分块（智能分割）
    "recursive": {
        "separators": ["\n\n", "\n", "。", "！", "？", "；", " "],
        "chunk_size": 1000
    }
}

# 元数据保留
METADATA_TO_KEEP = {
    "source": "文档来源 URL",
    "title": "标题",
    "created_at": "创建时间",
    "section": "章节信息",
    "heading": "小标题",
    "page_num": "页码（PDF）"
}
```

### 3. 向量数据库选择

**主流向量数据库对比**
```
┌──────────────┬─────────────┬─────────────┬─────────────┬─────────────┐
│    数据库    │   类型      │   规模      │   延迟      │   特点      │
├──────────────┼─────────────┼─────────────┼─────────────┼─────────────┤
│  Pinecone    │  云服务     │   超大      │   低        │   托管简单  │
│  Milvus      │  开源/云    │   大        │   低        │   功能丰富  │
│  Weaviate    │  开源/云    │   中大      │   低        │   混合搜索  │
│  Qdrant      │  开源/云    │   中大      │   低        │   Rust开发  │
│  Chroma      │  开源       │   小中      │   低        │   轻量简单  │
│  FAISS       │  开源       │   中        │   很低      │   离线高效  │
│  Elasticsearch│ 开源/云    │   大        │   中        │   生态完善  │
└──────────────┴─────────────┴─────────────┴─────────────┴─────────────┘
```

**选择决策树**
```
向量数据库选择
│
├─ 数据规模
│   ├─ 百万级以下 → Chroma / FAISS
│   ├─ 百万到亿级 → Milvus / Qdrant / Weaviate
│   └─ 亿级以上 → Pinecone (云)
│
├─ 部署方式
│   ├─ 自托管 → Milvus / Qdrant / Weaviate
│   └─ 托管服务 → Pinecone / Qdrant Cloud
│
├─ 特殊需求
│   ├─ 需要混合搜索 → Weaviate / Elasticsearch
│   ├─ 需要精确过滤 → Milvus / Qdrant
│   ├─ 需要离线分析 → FAISS
│   └─ 需要多模态 → Weaviate
│
└─ 成本考虑
    ├─ 免费 → Chroma / FAISS / 开源版
    └─ 付费 → 云服务
```

### 4. 索引选择

**向量索引算法**
```
索引类型对比

┌──────────────┬────────────┬────────────┬────────────┬────────────┐
│    索引     │   构建速度 │   查询速度 │   精度     │   内存     │
├──────────────┼────────────┼────────────┼────────────┼────────────┤
│   FLAT       │    快      │    慢      │   100%     │    高      │
│   IVF_FLAT   │    快      │    中      │   可调     │    中      │
│   IVF_PQ     │    快      │    快      │   较低     │    低      │
│   HNSW       │    慢      │    最快    │   很高     │    高      │
│   SCANN      │    中      │    快      │    高      │    中      │
│   ANNOY      │    中      │    中      │    高      │    中      │
└──────────────┴────────────┴────────────┴────────────┴────────────┘
```

**索引选择建议**
```python
# 根据场景选择
INDEX_CHOICES = {
    # 追求精确（少量数据）
    "flat": {
        "description": "暴力精确搜索",
        "use_when": "数据量 < 10万",
        "params": {}
    },
    
    # 平衡速度和精度
    "hnsw": {
        "description": "图索引，最常用",
        "use_when": "大多数场景",
        "params": {
            "M": 16,           # 连接数
            "ef_construction": 200,  # 构建时的搜索范围
            "ef": 100          # 查询时的搜索范围
        }
    },
    
    # 大规模数据
    "ivf_flat": {
        "description": "倒排文件索引",
        "use_when": "数据量 > 100万",
        "params": {
            "nlist": 1024,     # 聚类数量
            "nprobe": 32       # 查询的聚类数
        }
    },
    
    # 内存受限
    "ivf_pq": {
        "description": "量化压缩",
        "use_when": "内存受限，需要压缩",
        "params": {
            "nlist": 1024,
            "m": 16,           # 子向量数
            "nbits": 8        # 每子向量位数
        }
    }
}
```

### 5. 相似度度量选择

**度量方法**
```
向量距离度量

├─ 余弦相似度 (Cosine)
│   └── 推荐，最常用
│   └── 适合：文本相似性
│   └── 范围：[-1, 1]，越接近1越相似
│
├─ 欧氏距离 (L2)
│   └── 适合：图像、特征距离
│   └── 越接近0越相似
│
├─ 点积 (Dot Product)
│   └── 适合：推荐系统（考虑向量长度）
│   └── 越大越相似
│
└─ 曼哈顿距离 (L1)
    └── 适合：高维稀疏数据
```

```python
# 归一化后的向量
if use_dot_product:
    # 点积 = 余弦相似度 * ||a|| * ||b||
    # 归一化后两者等价
    normalized_vectors = normalize(vectors)
    score = dot_product(query, doc)
else:
    score = cosine_similarity(query, doc)
```

### 6. 混合检索策略

**向量 + 关键词混合搜索**
```python
# 权重混合
HYBRID_WEIGHTS = {
    "bm25_weight": 0.3,      # 关键词权重
    "vector_weight": 0.7,     # 向量权重
}

# 融合算法
def hybrid_search(query_vector, query_text, k=10):
    # 1. 向量搜索
    vector_results = vector_db.search(
        query_vector,
        k=k*2,  # 多取一些
        filter=metadata_filter
    )
    
    # 2. 关键词搜索
    keyword_results = es.search(query_text, k=k*2)
    
    # 3. 分数归一化
    vector_scores = normalize_scores(
        [r.score for r in vector_results],
        method="minmax"
    )
    
    keyword_scores = normalize_scores(
        [r.score for r in keyword_results],
        method="minmax"
    )
    
    # 4. 加权融合
    fused_results = []
    for r in vector_results:
        fused_score = (
            vector_weights["vector_weight"] * r.normalized_score +
            vector_weights["bm25_weight"] * keyword_scores.get(r.id, 0)
        )
        fused_results.append((r.id, fused_score))
    
    # 5. 重排序
    return sorted(fused_results, key=lambda x: x[1], reverse=True)[:k]
```

**RAG 检索优化**
```python
# 查询转换
QUERY_TRANSFORMATIONS = {
    # Step-back prompting
    "step_back": {
        "template": "从{query}中抽象出一个更通用的问题"
    },
    
    # HyDE (Hypothetical Document Embeddings)
    "hyde": {
        "template": "写一个回答{query}的理想文档",
        "generate_first": True
    },
    
    # 多查询
    "multi_query": {
        "template": "将{query}改写成多个不同角度的查询",
        "num_queries": 3
    },
    
    # 子查询分解
    "decompose": {
        "query": "复杂问题分解为多个简单问题"
    }
}

# RAG 流程
def rag_retrieve(query, top_k=5):
    # 1. 查询转换
    expanded_queries = expand_query(query)
    
    # 2. 并行检索
    results = []
    for q in expanded_queries:
        results.extend(vector_db.search(q, top_k=top_k))
    
    # 3. 去重
    unique_results = deduplicate(results)
    
    # 4. 重排序
    reranked = reranker.rerank(query, unique_results, top_k=top_k)
    
    return reranked
```

### 7. 生产环境检查清单

```
✓ 向量存储上线检查
├── [ ] 向量维度是否合理？
├── [ ] 选择了合适的向量模型？
├── [ ] 分块策略是否保留语义完整性？
├── [ ] 选择了合适的向量数据库？
├── [ ] 索引参数是否调优？
├── [ ] 相似度度量是否合适？
├── [ ] 是否需要混合搜索？
├── [ ] 元数据过滤是否有效？
├── [ ] 查询延迟是否满足要求？
├── [ ] 检索质量是否达标？
├── [ ] 有监控告警？
└── [ ] 成本是否可控？
```

### 8. 常见问题处理

**召回率低**
```python
# 排查步骤
TROUBLESHOOTING = {
    "1. 检查向量模型": {
        "方法": "用已知相似的文本测试",
        "问题": "中文效果差？换 BGE/M3E"
    },
    
    "2. 调整检索参数": {
        "方法": "增加 ef 或 nprobe",
        "问题": "查询太快结束"
    },
    
    "3. 优化分块": {
        "方法": "减小 chunk_size，增加 overlap",
        "问题": "语义被切断"
    },
    
    "4. 添加更多元数据": {
        "方法": "过滤条件更精确",
        "问题": "召回太多不相关内容"
    },
    
    "5. 使用重排序": {
        "方法": "引入 Cross-Encoder 重排",
        "问题": "初排精度不够"
    }
}
```

**延迟高**
```python
# 优化方向
OPTIMIZATIONS = {
    "索引": {
        "action": "换 HNSW 或 IVF",
        "params": {"nprobe": 16}
    },
    "缓存": {
        "action": "缓存热门查询向量",
        "key": "cache:query:{hash(query)}"
    },
    "批量": {
        "action": "合并多次查询",
        "method": "batch_search(queries)"
    },
    "预计算": {
        "action": "提前计算向量",
        "when": "离线导入时"
    }
}
```
