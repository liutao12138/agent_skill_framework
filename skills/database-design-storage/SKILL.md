---
name: database-design-storage
description: 数据库设计存储场景。指导模型进行关系型数据库设计时的思考过程，包括范式选择、表结构设计、索引策略和性能优化。
version: 1.0.0
author: Agent Team
tags: [database, sql, design, schema, rdbms]
---

# 数据库设计存储场景思维指南

## 思考框架

当你需要设计或优化关系型数据库时，按以下流程思考：

### 1. 需求分析阶段

**首先问自己：**

- 业务实体有哪些？它们之间是什么关系？
- 主要的查询模式是什么？（读多写少？还是读写均衡？）
- 数据量预估是多少？（小数据量、中等规模、还是大数据？）
- 数据的一致性要求有多高？（强一致？还是最终一致？）
- 有哪些业务规则需要强制约束？

### 2. 实体识别

**从需求中提取实体：**

```
核心实体（必须有）
├── 用户 (User)
├── 订单 (Order)
├── 产品 (Product)
└── ...

关联实体（用于建立关系）
├── 用户订单关联
├── 订单商品关联
└── ...

枚举/配置实体
├── 状态枚举
├── 类型枚举
└── ...
```

### 3. 关系建模

**一对一关系 (1:1)**
```sql
-- 何时使用：需要将大字段分离、或者需要不同的访问权限
-- 示例：用户基本信息 <-> 用户扩展信息
CREATE TABLE users (
    id BIGINT PRIMARY KEY,
    username VARCHAR(50) NOT NULL
);

CREATE TABLE user_profiles (
    user_id BIGINT PRIMARY KEY,
    bio TEXT,
    avatar_url VARCHAR(255)
);
```

**一对多关系 (1:N)**
```sql
-- 何时使用：主表的一条记录对应从表多条记录
-- 示例：一个用户可以有多个订单
CREATE TABLE users (
    id BIGINT PRIMARY KEY
);

CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

**多对多关系 (N:M)**
```sql
-- 何时使用：两边都需要互相引用多条记录
-- 示例：学生和课程的关系
CREATE TABLE students (
    id BIGINT PRIMARY KEY
);

CREATE TABLE courses (
    id BIGINT PRIMARY KEY
);

CREATE TABLE student_courses (
    student_id BIGINT,
    course_id BIGINT,
    enrolled_at DATETIME,
    PRIMARY KEY (student_id, course_id)
);
```

### 4. 范式选择

**第一范式 (1NF) - 确保原子性**
```
✓ 原子性检查：
├── 每个字段都是原子的（不可再分）
├── 没有重复的字段组
└── 每条记录都是唯一的
```

**第二范式 (2NF) - 消除部分依赖**
```
✓ 在 1NF 基础上：
├── 每个非主键字段完全依赖于主键
└── 不存在非主键字段只依赖于主键的一部分（复合主键时）
```

**第三范式 (3NF) - 消除传递依赖**
```
✓ 在 2NF 基础上：
├── 非主键字段之间没有依赖关系
└── 非主键字段只依赖于主键
```

**反范式化场景**
```sql
-- 何时考虑反范式：
-- 1. 读多写少的场景
-- 2. 需要避免大量 JOIN 查询
-- 3. 性能优化瓶颈在 JOIN 操作

-- 示例：在订单表中冗余用户姓名，减少 JOIN
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    user_name VARCHAR(100),  -- 冗余字段
    total_amount DECIMAL(10,2)
);
```

### 5. 字段设计

**主键选择优先级**
```
1. 自增 BIGINT（简单、紧凑）
   ✓ 优点：插入性能高、存储空间小
   ✗ 缺点：分布式环境下有冲突风险

2. UUID / GUID（全局唯一）
   ✓ 优点：全局唯一、可合并数据
   ✗ 缺点：占用空间大、插入性能略低

3. 业务主键（自然键）
   ✓ 优点：有业务含义
   ✗ 缺点：变更风险高、可能不够高效
```

**字段类型选择原则**
```sql
-- 字符串
VARCHAR(n)    -- 可变长度，有长度限制
TEXT          -- 长文本
CHAR(n)       -- 固定长度

-- 数值
INT / BIGINT  -- 整数
DECIMAL(p,s)  -- 精确小数（金额）
FLOAT / DOUBLE -- 浮点数（注意精度问题）

-- 日期时间
DATE          -- 日期（2024-01-15）
DATETIME      -- 日期时间
TIMESTAMP     -- 时间戳（自动更新）

-- 布尔
BOOLEAN / TINYINT(1)

-- 大对象
BLOB          -- 二进制
JSON          -- JSON 数据（MySQL 5.7+）
```

**必填与可选**
```sql
-- NOT NULL + 默认值（推荐）
is_deleted BOOLEAN NOT NULL DEFAULT FALSE

-- 软删除设计
deleted_at DATETIME NULL,
deleted_by BIGINT NULL

-- 审计字段
created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
created_by BIGINT NOT NULL
updated_by BIGINT NOT NULL
```

### 6. 索引策略

**主键索引**
```sql
-- 聚簇索引（InnoDB）
-- 叶子节点存储完整数据行
PRIMARY KEY (id)
```

**二级索引（辅助索引）**
```sql
-- 唯一索引
UNIQUE INDEX idx_user_email (email)

-- 普通索引
INDEX idx_order_user_id (user_id)

-- 联合索引（最左前缀原则）
INDEX idx_order_status_created (status, created_at DESC)

-- 覆盖索引（减少回表）
INDEX idx_covering (user_id, status, created_at)
```

**索引设计决策树**
```
查询场景分析
│
├─ 查询条件中有等值匹配吗？
│   ├─ 是 → 考虑添加等值匹配的索引
│   └─ 否 → 进入范围查询分析
│
├─ 有范围查询（>、<、BETWEEN、LIKE）吗？
│   ├─ 是 → 范围查询字段放在联合索引的最后
│   └─ 否 → 字段顺序按区分度排列
│
├─ 需要排序吗？
│   ├─ 是 → 排序字段加入索引
│   └─ 否 → 跳过
│
└─ 选择性分析
    ├─ 选择性高（> 20%）→ 索引效果好
    └─ 选择性低 → 考虑是否值得建索引
```

### 7. 性能优化检查清单

**SQL 编写规范**
```sql
-- ✓ 使用具体字段名，不要用 SELECT *
SELECT id, name, status FROM users WHERE id = 1;

-- ✓ JOIN 前确保关联字段有索引
SELECT * FROM orders o
JOIN users u ON o.user_id = u.id;

-- ✓ 分页使用高效方式
-- 传统方式（性能差）
SELECT * FROM orders ORDER BY id LIMIT 1000000, 20;

-- 高效方式
SELECT * FROM orders
WHERE id > 1000000
ORDER BY id LIMIT 20;

-- ✓ 避免在索引列上使用函数
-- 错误
SELECT * FROM orders WHERE DATE(created_at) = '2024-01-15';

-- 正确
SELECT * FROM orders
WHERE created_at >= '2024-01-15 00:00:00'
  AND created_at < '2024-01-16 00:00:00';
```

**分表策略**
```sql
-- 水平分表（按时间）
orders_202401
orders_202402
...

-- 水平分表（按用户ID哈希）
orders_user_00 ~ orders_user_15

-- 垂直分表（按字段使用频率）
-- 热数据表：频繁查询的字段
-- 冷数据表：不常查询的大字段
```

## 常见反模式

**1. EAV (Entity-Attribute-Value)**
```sql
-- ✗ 避免：难以查询、索引效率低
CREATE TABLE product_attributes (
    product_id BIGINT,
    attribute_name VARCHAR(50),
    attribute_value VARCHAR(255),
    PRIMARY KEY (product_id, attribute_name)
);
```

**2. 超级表（上帝对象）**
```sql
-- ✗ 避免：一个表包含所有字段
CREATE TABLE everything (
    id BIGINT,
    user_name VARCHAR(50),
    order_id BIGINT,
    product_id BIGINT,
    product_name VARCHAR(100),
    ...
);
```

**3. 缺乏外键约束**
```sql
-- ✓ 使用外键约束保证数据完整性
FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE CASCADE
    ON UPDATE CASCADE
```

## 设计评审要点

```
✓ 评审检查项
├── [ ] 主键设计是否合理？
├── [ ] 字段类型是否合适？
├── [ ] 索引是否覆盖主要查询？
├── [ ] 是否存在不必要的 JOIN？
├── [ ] 分表策略是否必要？
├── [ ] 软删除/硬删除决策？
├── [ ] 审计字段是否完整？
└── [ ] 是否有数据迁移方案？
```
