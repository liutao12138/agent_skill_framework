---
name: cache-strategy-storage
description: 缓存策略存储场景。指导模型进行缓存设计时的思考过程，包括缓存模式选择、一致性保证、失效策略和常见问题处理。
version: 1.0.0
author: Agent Team
tags: [cache, redis, memory, performance, strategy]
---

# 缓存策略存储场景思维指南

## 思考框架

当你需要设计缓存策略时，按以下流程思考：

### 1. 是否需要缓存？

**缓存适用场景检查**
```
                    ┌─────────────────────┐
                    │   数据访问模式？     │
                    └─────────────────────┘
                              │
           ┌──────────────────┼──────────────────┐
           │                  │                  │
      ┌────▼────┐       ┌────▼────┐        ┌────▼────┐
      │读多写少 │       │读写均衡 │        │写多读少 │
      │适合缓存 │       │可考虑缓存│        │不适合缓存│
      └────┬────┘       └────┬────┘        └─────────┘
           │                  │
           ▼                  ▼
      命中率 > 70%        命中率 > 50%
```

**不适合缓存的情况**
```python
# ✗ 不适合缓存的数据
├── 频繁变化的数据（实时计数器）
├── 单次使用的临时数据
├── 数据量极大且访问分散
├── 对一致性要求极高
└── 计算成本低于缓存成本
```

**适合缓存的情况**
```python
# ✓ 适合缓存的数据
├── 热点数据（访问频率高）
├── 复杂计算结果（CPU密集型）
├── 外部API调用结果
├── 用户配置/偏好数据
├── 字典/枚举数据
└── 会话数据
```

### 2. 缓存模式选择

**Cache-Aside（旁路缓存）**
```
                    应用服务器
                        │
         ┌──────────────┼──────────────┐
         │              │              │
         ▼              ▼              ▼
    ┌─────────┐   ┌─────────┐   ┌─────────┐
    │ 读取数据 │   │ 缓存存在 │   │ 缓存不存在│
    └────┬────┘   └────┬────┘   └────┬────┘
         │              │              │
         ▼              ▼              ▼
    ┌─────────┐   ┌─────────┐   ┌─────────┐
    │查缓存？ │←──│返回缓存 │   │查数据库 │
    └────┬────┘   └─────────┘   └────┬────┘
         │                           │
    ┌────┴────┐                      │
    │         │                      │
    ▼         ▼                      ▼
┌────────┐  ┌────────┐           ┌────────┐
│缓存命中 │ │缓存未中 │           │写入缓存│
└────────┘  └────┬────┘           └────────┘
                 │
                 ▼
              ┌────────┐
              │返回数据│
              └────────┘
```

```python
# 伪代码实现
def get_user(user_id):
    # 1. 先查缓存
    user = cache.get(f"user:{user_id}")
    if user:
        return user
    
    # 2. 缓存未命中，查数据库
    user = db.query("SELECT * FROM users WHERE id = ?", user_id)
    
    # 3. 写入缓存
    if user:
        cache.set(f"user:{user_id}", user, ttl=3600)
    
    return user

def update_user(user_id, data):
    # 1. 更新数据库
    db.execute("UPDATE users SET ... WHERE id = ?", user_id)
    
    # 2. 删除缓存（而非更新）
    cache.delete(f"user:{user_id}")
```

**Read-Through / Write-Through**
```python
# Read-Through：缓存负责加载数据
user = cache.get_or_load(f"user:{user_id}", loader=load_user_from_db)

# Write-Through：写入时同步更新缓存
def update_user(user_id, data):
    db.execute(...)
    cache.set(f"user:{user_id}", updated_user, ttl=3600)
```

**Write-Behind（异步写入）**
```
                    应用服务器
                        │
                        ▼
              ┌─────────────────┐
              │   写入操作队列   │
              └────────┬────────┘
                       │
         ┌─────────────┼─────────────┐
         │             │             │
         ▼             ▼             ▼
    ┌─────────┐  ┌─────────┐  ┌─────────┐
    │批量写入 │  │延迟写入 │  │失败重试 │
    │数据库  │  │数据库   │  │数据库   │
    └─────────┘  └─────────┘  └─────────┘
```

### 3. 缓存数据结构选择

**Redis 数据结构决策树**
```
需要存储的数据类型
│
├─ 简单字符串/JSON
│   └─ STRING (GET/SET)
│
├─ 计数器
│   └─ STRING (INCR/DECR) 或专用命令
│       └── INCR user:{id}:view_count
│
├─ 哈希（对象）
│   └─ HASH (HSET/HGET)
│       └── HSET user:1001 name "张三" age 25
│
├─ 列表（队列/栈）
│   └─ LIST (LPUSH/RPOP)
│       └── LPUSH queue:tasks '{"id":1,"task":"xxx"}'
│
├─ 去重集合
│   └─ SET (SADD/SISMEMBER)
│       └── SADD user:1001:tags "python" "redis" "cache"
│
├─ 有序集合（排行榜）
│   └─ ZSET (ZADD/ZRANGE)
│       └── ZADD leaderboard 1000 "user1" 900 "user2"
│
├─ 位图（用户签到、活跃度）
│   └─ BITSET (SETBIT/GETBIT)
│
└─ 布隆过滤器（去重、存在性判断）
    └─ BF.ADD bf:email "test@example.com"
```

### 4. 失效策略

**TTL 设计原则**
```python
# TTL 选择的考虑因素
CACHE_TTLS = {
    # 配置类数据（变化极少）
    "config:*": 86400 * 7,      # 7天
    "dict:*": 86400,             # 1天
    
    # 用户相关数据（中等变化）
    "user:{id}": 3600,          # 1小时
    "user:{id}:profile": 1800,   # 30分钟
    
    # 会话数据（严格时效）
    "session:{id}": 86400,      # 1天
    "token:{id}": 3600,          # 1小时
    
    # 热点数据（较短TTL）
    "hot:product:*": 300,        # 5分钟
    "hot:article:*": 600,        # 10分钟
    
    # 临时数据（秒级）
    "rate_limit:*": 60,          # 1分钟
    "lock:{resource}": 30,       # 30秒
}
```

**失效策略选择**
```python
# 策略1：TTL 过期（简单但可能有不一致窗口）
# 适用：允许短暂不一致的场景

# 策略2：主动失效（更新时删除/更新缓存）
# 适用：对一致性要求较高的场景
def update_user(user_id, data):
    # 方案A：删除缓存
    cache.delete(f"user:{user_id}")
    
    # 方案B：更新缓存
    cache.hset(f"user:{user_id}", data)

# 策略3：延迟双删（减少不一致概率）
def update_user(user_id, data):
    # 1. 删除缓存
    cache.delete(f"user:{user_id}")
    
    # 2. 更新数据库
    db.execute(...)
    
    # 3. 延迟删除（等待主从同步）
    time.sleep(0.1)
    cache.delete(f"user:{user_id}")
```

### 5. 一致性保证

**缓存与数据库一致性模型**
```
一致性级别
│
├─ 最终一致（可接受短时间不一致）
│   └── 场景：商品列表、阅读数
│
├─ 读写一致（写入后能读到）
│   └── 场景：用户配置、个人信息
│
└─ 强一致（任何时刻都一致）
    └── 场景：库存、余额、支付
```

**强一致场景处理**
```python
# 方案1：分布式锁
def deduct_stock(product_id, quantity):
    lock_key = f"lock:stock:{product_id}"
    
    # 获取锁（最多等待5秒，持有3秒）
    if not cache.acquire_lock(lock_key, ttl=3, timeout=5):
        raise Exception("系统繁忙，请重试")
    
    try:
        # 在锁保护下读取并更新
        stock = cache.get(f"stock:{product_id}")
        if stock < quantity:
            raise Exception("库存不足")
        
        cache.decrby(f"stock:{product_id}, quantity)
        db.execute("UPDATE stock SET count = count - ?", quantity)
    finally:
        cache.release_lock(lock_key)

# 方案2：直接查数据库（牺牲性能保证一致）
def get_stock(product_id):
    # 放弃缓存，直接读库
    return db.query("SELECT count FROM stock WHERE id = ?", product_id)
```

### 6. 缓存问题处理

**缓存穿透**
```
问题：查询一个不存在的数据，每次都穿过缓存查数据库

解决方案：
├── 缓存空值（NULL）
│   cache.set("user:999", NULL, ttl=60)
│
└── 布隆过滤器
    bf.exists bf:users "999@example.com"
```

**缓存击穿**
```
问题：热点key过期瞬间，大量请求同时穿透到数据库

解决方案：
├── 互斥锁
│   if not cache.get("lock:product:123"):
│       lock = cache.setnx("lock:product:123", 1, ttl=30)
│       if lock:
│           data = db.query(...)
│           cache.set("product:123", data)
│           cache.delete("lock:product:123")
│
└── 逻辑永不过期
    # 设置很长的TTL，用后台线程刷新
```

**缓存雪崩**
```
问题：大量key在同一时间过期，导致数据库压力骤增

解决方案：
├── 随机化TTL
│   ttl = base_ttl + random.randint(0, 300)
│
├── 多级缓存
│   L1: 本地缓存 1分钟
│   L2: Redis 5分钟
│
└── 预热
    cache.set("hot:product:*", data, ttl=3600+random())
```

### 7. 缓存容量规划

**内存管理策略**
```
Redis 内存使用
│
├─ volatile-lru      # 删除有过期时间的 LRU 键
├─ allkeys-lru       # 删除所有键的 LRU 键
├─ volatile-ttl      # 删除过期时间最短的键
├─ volatile-random   # 随机删除过期键
└─ noeviction        # 不删除，满了报错
```

```bash
# 配置示例
maxmemory 2gb
maxmemory-policy allkeys-lru
```

**Key 设计规范**
```
命名格式：{业务}:{类型}:{标识}

# ✓ 推荐
user:1001
user:1001:profile
order:2024:001234
product:hot:list
session:abc123xyz

# ✗ 避免
data (太泛)
temp (无意义)
```

## 监控指标

```python
# 需要监控的指标
MONITOR_METRICS = {
    # 性能指标
    "hit_rate": "缓存命中率",
    "avg_latency": "平均响应延迟",
    "command_per_sec": "每秒命令数",
    
    # 内存指标
    "used_memory": "已用内存",
    "memory_fragmentation": "内存碎片率",
    "keys_count": "键数量",
    
    # 错误指标
    "evicted_keys": "被驱逐的键数量",
    "expired_keys": "过期的键数量",
    "connections": "当前连接数",
}
```

## 决策清单

```
✓ 缓存设计决策
├── [ ] 是否真的需要缓存？（收益 > 成本）
├── [ ] 选择了合适的缓存模式？
├── [ ] 选择了合适的失效策略？
├── [ ] TTL 设置是否合理？
├── [ ] 有缓存穿透/击穿/雪崩的应对方案？
├── [ ] 有一致性保证方案？
├── [ ] 进行了容量规划？
├── [ ] 有监控告警？
└── [ ] 进行了压力测试？
```
