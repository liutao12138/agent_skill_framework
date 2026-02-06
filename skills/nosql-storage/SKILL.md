---
name: nosql-storage
description: NoSQL存储场景。指导模型进行NoSQL数据库设计时的思考过程，包括数据库选择、数据模型设计、一致性保证和性能优化。
version: 1.0.0
author: Agent Team
tags: [nosql, mongodb, redis, cassandra, dynamodb, document, key-value]
---

# NoSQL存储场景思维指南

## 思考框架

当你需要选择和使用NoSQL数据库时，按以下流程思考：

### 1. 是否需要NoSQL？

**SQL vs NoSQL 选择树**
```
数据存储选择
│
├─ 需要强事务（ACID）？
│   ├─ 是 → 使用关系型数据库
│   └─ 否 → 继续
│
├─ 数据结构是否固定？
│   ├─ 是 → 关系型数据库可能更适合
│   └─ 否 → 继续
│
├─ 需要水平扩展？
│   ├─ 是 → 考虑 NoSQL
│   └─ 否 → 继续
│
├─ 数据量是否大？
│   ├─ 是 (> 10TB) → 考虑 NoSQL
│   └─ 否 → 关系型数据库通常足够
│
└─ 访问模式是什么？
    ├─ 简单 KV → Key-Value 存储
    ├─ 文档查询 → 文档数据库
    ├─ 关系查询 → 图数据库
    └─ 时序数据 → 时序数据库
```

**NoSQL 适用场景**
```
适合 NoSQL 的场景
│
├─ 大规模数据（PB级别）
│   └── 互联网用户行为日志
│
├─ 灵活Schema
│   └── 用户配置、动态属性
│
├─ 高并发读写
│   └── 社交Feed、消息队列
│
├─ 地理分布
│   └── 多地域部署的内容
│
├─ 快速迭代
│   └── 原型验证、新业务尝试
│
└─ 成本敏感
    └── 需要廉价存储大量数据
```

### 2. NoSQL 类型选择

**NoSQL 数据库分类**
```
┌──────────────┬─────────────┬─────────────┬─────────────┬─────────────┐
│    类型     │    示例     │    优点     │    缺点     │   适用场景 │
├──────────────┼─────────────┼─────────────┼─────────────┼─────────────┤
│  Key-Value  │ Redis       │ 极快        │ 无查询能力  │ 缓存、会话│
│  文档      │ MongoDB     │ 灵活Schema  │ 不支持JOIN  │ 内容管理   │
│  宽列      │ Cassandra   │ 线性扩展    │ 查询受限    │ 时序、日志 │
│  图        │ Neo4j       │ 关系查询强  │ 水平扩展难  │ 社交网络   │
│  搜索      │ Elasticsearch│ 搜索强大    │ 写性能弱    │ 全文搜索   │
│  时序      │ InfluxDB    │ 时序优化    │ 通用查询弱  │ 监控指标   │
└──────────────┴─────────────┴─────────────┴─────────────┴─────────────┘
```

**选择决策矩阵**
```
场景选择
│
├─ 缓存/会话
│   └── Redis (内存KV) → Memcached
│
├─ 内容管理/CMS
│   └── MongoDB (文档) → CouchDB
│
├─ 用户数据/配置
│   └── MongoDB (文档) → DynamoDB
│
├─ 社交关系/推荐
│   └── Neo4j (图) → JanusGraph
│
├─ 日志/时序数据
│   └── Cassandra (宽列) → InfluxDB → TimescaleDB
│
├─ 全文搜索
│   └── Elasticsearch → Solr
│
├─ 排行榜/计数器
│   └── Redis (Sorted Set)
│
└─ 消息队列
    └── Redis (Streams) → Kafka → RabbitMQ
```

### 3. MongoDB 设计

**文档模型设计原则**
```
文档设计指南
│
├─ 嵌入（Embedding）原则
│   ├── 一对一关系 → 嵌入到主文档
│   ├── 一对多关系（子文档少） → 嵌入
│   └── 一对多关系（子文档多） → 引用
│
├─ 引用（Reference）原则
│   ├── 需要独立更新子文档
│   ├── 子文档经常变化
│   ├── 子文档数量不确定
│   └── 需要原子更新
│
└─ 混合策略
    └── 常用数据嵌入，冷数据引用
```

**嵌入 vs 引用示例**
```javascript
// 场景：博客文章 + 评论

// ❌ 错误：无限嵌套评论
{
    title: "我的博客",
    comments: [
        {
            text: "评论1",
            replies: [
                {
                    text: "回复1-1",
                    replies: [...]  // 无限嵌套
                }
            ]
        }
    ]
}

// ✅ 正确：适度嵌入
{
    title: "我的博客",
    comments: [
        {
            user_id: "user123",
            text: "评论1",
            created_at: ISODate(),
            like_count: 10
        }
    ],
    comment_count: 100  // 计数器
}

// ✅ 推荐：引用（大评论量）
// 文章集合
{
    _id: ObjectId("article1"),
    title: "我的博客",
    content: "...",
    comment_count: 1000
}

// 评论集合
{
    _id: ObjectId("comment1"),
    article_id: ObjectId("article1"),
    user_id: "user123",
    text: "评论内容",
    created_at: ISODate()
}
```

**索引设计**
```javascript
// 索引设计原则

// 1. 查询字段加索引
db.users.createIndex({ email: 1 }, { unique: true })
db.orders.createIndex({ user_id: 1, created_at: -1 })

// 2. 复合索引（考虑查询顺序）
// 查询：{ status: "active", created_at: { $gte: date } }
// 索引：{ status: 1, created_at: -1 }

// 3. 覆盖索引（避免回表）
// 查询：{ _id: 1, name: 1, email: 1 }
// 索引：{ name: 1, email: 1 }
// 投影：{ _id: 0, name: 1, email: 1 }

// 4. 部分索引（节省空间）
db.orders.createIndex(
    { status: 1, created_at: 1 },
    { partialFilterExpression: { status: "pending" } }
)

// 5. 文本索引（全文搜索）
db.articles.createIndex({ title: "text", content: "text" })

// 索引注意事项
INDEX_NOTES = {
    "不要索引": ["大字段", "低选择字段", "数组字段"],
    "索引限制": ["复合索引 ≤ 32 字段", "索引名 ≤ 128 字符"],
    "监控索引": ["idx_hit", "idx_miss", "index_size"]
}
```

### 4. Redis 设计

**数据结构选择**
```
Redis 数据结构使用场景

String (字符串)
├── 缓存简单值
│   └── SET user:1001:name "张三"
├── 计数器
│   └── INCR page:view:1001
├── 分布式锁
│   └── SET lock:order123 1 EX 30 NX
└── 缓存JSON
    └── SET user:1001:json '{"name":"张三"}'

Hash (哈希)
├── 对象存储（适合部分字段读取）
│   HSET user:1001 name "张三" age 25
├── 购物车
│   HSET cart:1001 product:1 2 product:2 1
└── 配置缓存
    HSET config:redis host "localhost" port 6379

List (列表)
├── 消息队列
│   LPUSH queue:tasks '{"id":1}' / BRPOP queue:tasks
├── 最新N条
│   LPUSH user:1001:feed:ids 1001 / LTRIM 0 99
└── 历史记录
    RPUSH user:1001:history page1 / LTRIM 0 99

Set (集合)
├── 去重
│   SADD user:1001:tags python redis
├── 标签系统
│   SADD post:1001:tags 1 2 3
└── 共同好友
│   SINTER user:1001:friends user:1002:friends

Sorted Set (有序集合)
├── 排行榜
│   ZADD leaderboard 1000 user1 900 user2
├── 优先级队列
│   ZADD queue:priority 10 task1 5 task2
└── 时间索引
│   ZADD user:feed:ts 1705315200 feed_item_1
```

**缓存模式设计**
```python
# 缓存模式：Cache-Aside + Write-Through

# 1. 读取
def get_user(user_id):
    # 先查 Redis
    user_data = redis.get(f"user:{user_id}")
    if user_data:
        return json.loads(user_data)
    
    # 缓存未命中，查 MongoDB
    user = mongo.users.find_one({"_id": user_id})
    
    # 写入缓存
    if user:
        redis.setex(f"user:{user_id}", 3600, json.dumps(user))
    
    return user

# 2. 写入
def update_user(user_id, data):
    # 更新 MongoDB
    mongo.users.update_one({"_id": user_id}, {"$set": data})
    
    # 更新 Redis（Write-Through）
    redis.setex(f"user:{user_id}", 3600, json.dumps(data))

# 3. 删除
def delete_user(user_id):
    # 同时删除
    mongo.users.delete_one({"_id": user_id})
    redis.delete(f"user:{user_id}")
```

### 5. Cassandra 设计

**数据模型设计**
```sql
-- Cassandra 数据模型

-- 1. 查询驱动的表设计
-- ❌ 按实体设计（错误）
CREATE TABLE users (
    id UUID PRIMARY KEY,
    name TEXT,
    email TEXT
);

CREATE TABLE posts (
    id UUID PRIMARY KEY,
    user_id UUID,
    content TEXT,
    created_at TIMESTAMP
);

-- ✅ 按查询设计（正确）
CREATE TABLE posts_by_user (
    user_id UUID,
    post_id TIMEUUID,
    content TEXT,
    created_at TIMESTAMP,
    PRIMARY KEY ((user_id), post_id)
) WITH CLUSTERING ORDER BY (post_id DESC);

-- 2. 分区键设计
-- 单字段分区键
PRIMARY KEY ((user_id), post_id)

-- 复合分区键（多租户）
PRIMARY KEY ((tenant_id, user_id), post_id)

-- 3. 反规范化设计
-- 为热门查询创建专用表
CREATE TABLE posts_popular (
    post_id UUID PRIMARY KEY,
    user_id UUID,
    content TEXT,
    like_count INT,
    view_count INT,
    created_at TIMESTAMP,
    PRIMARY KEY ((like_count), created_at)
) WITH CLUSTERING ORDER BY (like_count DESC, created_at DESC);

-- 4. 静态列（同一分区共享）
CREATE TABLE user_profiles (
    tenant_id TEXT,
    user_id UUID,
    name TEXT,
    bio TEXT,
    post_count INT STATIC,
    PRIMARY KEY ((tenant_id), user_id)
);
```

**一致性级别**
```python
# Cassandra 一致性级别

CONSISTENCY_LEVELS = {
    "ONE": "返回第一个响应节点的数据",
    "TWO": "返回两个节点的数据（取最新）",
    "THREE": "返回三个节点的数据",
    "QUORUM": "大多数节点（DC内）",
    "ALL": "所有节点",
    "LOCAL_QUORUM": "本地DC大多数",
    "EACH_QUORUM": "所有DC大多数",
    "LOCAL_ONE": "本地DC第一个节点"
}

# 读写一致性配置
READ_CONSISTENCY = "LOCAL_QUORUM"  # 读
WRITE_CONSISTENCY = "QUORUM"        # 写

# 根据场景选择
SCENE_CONSISTENCY = {
    "强一致（金融）": {"read": "ALL", "write": "ALL"},
    "高可用（社交）": {"read": "ONE", "write": "ONE"},
    "平衡（电商）": {"read": "QUORUM", "write": "QUORUM"},
    "最终一致（日志）": {"read": "ONE", "write": "ONE"}
}
```

### 6. 一致性与事务

**NoSQL 一致性模型**
```
一致性级别
│
├─ 强一致
│   └── 所有副本同步
│   └── 代价：延迟高、可用性低
│
├─ 最终一致
│   └── 异步复制，最终一致
│   └── 代价：可能读到旧数据
│
├─ 因果一致
│   └── 相关操作有序
│   └── 比最终一致强，比强一致弱
│
└─ 读己所写
    └── 能读到自己的写入
```

**分布式事务方案**
```python
# 方案1：Saga 模式（补偿事务）

# 订单创建Saga
ORDER_SAGA = [
    {
        "step": "创建订单",
        "action": create_order,
        "rollback": cancel_order
    },
    {
        "step": "扣减库存",
        "action": deduct_inventory,
        "rollback": restore_inventory
    },
    {
        "step": "扣款",
        "action": charge_payment,
        "rollback": refund_payment
    },
    {
        "step": "发送通知",
        "action": send_notification,
        "rollback": send_cancellation
    }
]

# 方案2：事件溯源
EVENT_SOURCING = {
    "events": ["OrderCreated", "InventoryDeducted", "PaymentCharged"],
    "state": "Order",
    "saga": "执行所有事件"
}

# 方案3：两阶段提交（2PC）
TWO_PHASE_COMMIT = {
    "prepare": "所有参与者准备好",
    "commit": "所有参与者提交",
    "rollback": "任何失败则全部回滚"
}
```

### 7. 性能优化

**MongoDB 优化**
```javascript
// 1. 查询优化
// 避免全表扫描
db.orders.find({ status: "completed" }).hint({ created_at: -1 })

// 限制返回字段
db.users.find({}, { name: 1, email: 1, _id: 0 })

// 使用聚合管道优化
db.orders.aggregate([
    { $match: { status: "completed" } },
    { $group: { _id: "$user_id", total: { $sum: "$amount" } } },
    { $sort: { total: -1 } },
    { $limit: 10 }
])

// 2. 批量操作
const bulk = db.users.initializeUnorderedBulkOp();
users.forEach(user => {
    bulk.insert(user);
});
bulk.execute();

// 3. 分片设计
sh.shardCollection("app.orders", {
    "user_id": "hashed",  // 哈希分片
    "created_at": 1        // 局部排序
})
```

**Redis 优化**
```python
# 1. Pipeline 批量操作
pipe = redis.pipeline()
for user_id in user_ids:
    pipe.get(f"user:{user_id}")
results = pipe.execute()

# 2. Lua 脚本（原子操作）
LUA_SCRIPT = """
local key = KEYS[1]
local current = redis.call('GET', key)
if current == ARGV[1] then
    return redis.call('SET', key, ARGV[2])
end
return 0
"""
redis.eval(LUA_SCRIPT, 1, "counter", "old", "new")

# 3. 集群客户端
from redis.cluster import RedisCluster

# 4. 内存优化
# 使用合适的数据结构
# Hash 而不是 String 存储对象
# Set 而不是 String 存储标签

# 5. 持久化配置
REDIS_PERSISTENCE = {
    "RDB": {
        "save": "900 1 300 10 60 10000",  # 条件触发
        "dbfilename": "dump.rdb"
    },
    "AOF": {
        "appendonly": "yes",
        "appendfsync": "everysec"
    }
}
```

### 8. 监控与运维

**关键监控指标**
```python
# MongoDB 监控
MONGODB_METRICS = {
    "连接": ["connections", "connections_available"],
    "操作": ["opcounters", "opcounters_replica"],
    "内存": ["mem_bits", "mem_mapped", "mem_resident"],
    "锁": ["globalLock", "locks"],
    "复制": ["replSetGetStatus", "replicationLag"],
    "索引": ["indexCounters", "indexSize"],
    "分片": ["shardServerStatus", "balancer"]
}

# Redis 监控
REDIS_METRICS = {
    "性能": ["connected_clients", "instantaneous_ops-per_sec"],
    "内存": ["used_memory", "used_memory_human", "memory_fragmentation_ratio"],
    "持久化": ["rdb_changes_since_last_save", "aof_enabled"],
    "复制": ["master_link_status", "master_repl_offset"],
    "键": ["db_keys", "expired_keys", "evicted_keys"]
}

# 告警阈值
ALERT_THRESHOLDS = {
    "连接使用率": "> 80%",
    "内存使用率": "> 85%",
    "复制延迟": "> 5秒",
    "慢查询": "> 100ms",
    "锁等待": "> 1秒"
}
```

## 设计决策清单

```
✓ NoSQL 设计检查
├── [ ] 选择了正确的 NoSQL 类型？
├── [ ] 数据模型设计合理？
├── [ ] 查询模式是否高效？
├── [ ] 索引设计是否合适？
├── [ ] 一致性级别是否匹配业务？
├── [ ] 分片/分桶策略？
├── [ ] 缓存策略？
├── [ ] 监控告警？
├── [ ] 备份恢复方案？
├── [ ] 容量规划？
└── [ ] 成本评估？
```
