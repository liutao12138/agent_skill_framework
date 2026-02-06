---
name: file-storage
description: 文件存储场景。指导模型进行文件存储设计时的思考过程，包括存储方案选择、本地vs云存储、目录结构和文件管理策略。
version: 1.0.0
author: Agent Team
tags: [file, storage, s3, oss, local, directory]
---

# 文件存储场景思维指南

## 思考框架

当你需要设计文件存储方案时，按以下流程思考：

### 1. 存储需求分析

**首先评估需求：**
```
文件存储需求评估
│
├─ 文件类型
│   ├── 静态资源（图片、CSS、JS）
│   ├── 用户上传（头像、文档）
│   ├── 业务文件（合同、报表）
│   └── 临时文件（缓存、生成物）
│
├─ 访问模式
│   ├── 公开访问（静态资源）
│   ├── 私有访问（用户文件）
│   └── 带权限（业务文档）
│
├─ 数据规模
│   ├── 小 (< 10GB)
│   ├── 中 (10GB - 1TB)
│   └── 大 (> 1TB)
│
└─ 访问频率
    ├── 热数据（频繁访问）
    ├── 温数据（偶尔访问）
    └── 冷数据（很少访问）
```

### 2. 存储方案选择

**存储方案对比**
```
┌──────────────┬─────────────┬─────────────┬─────────────┬─────────────┐
│    方案     │    成本     │    扩展性   │    性能     │   复杂度    │
├──────────────┼─────────────┼─────────────┼─────────────┼─────────────┤
│  本地磁盘    │    低       │    差       │    快       │    低       │
│  NAS/SAN    │    中       │    中       │    中       │    中       │
│  对象存储    │    低       │    好       │    中       │    低       │
│  分布式存储  │    高       │    很好     │    快       │    高       │
│  云存储      │    按量     │    极好     │    好       │    低       │
└──────────────┴─────────────┴─────────────┴─────────────┴─────────────┘
```

**选择决策树**
```
存储方案选择
│
├─ 数据量 < 100GB
│   ├─ 临时项目 → 本地磁盘
│   └─ 正式项目 → 对象存储（OSS/S3）
│
├─ 100GB - 1TB
│   ├─ 低频访问 → 对象存储
│   └─ 高频访问 → NAS + CDN
│
├─ 1TB - 100TB
│   ├─ 公开资源 → CDN + 对象存储
│   └─ 私有文件 → 分布式存储
│
└─ > 100TB
    └── 分布式存储 + 多级缓存
```

### 3. 本地存储设计

**目录结构规范**
```
项目目录结构
│
├─ uploads/              # 上传文件目录
│   ├─ {yyyy}/{MM}/{dd}/ # 按日期分目录
│   │   ├─ user_1001/
│   │   │   ├─ avatar/
│   │   │   └─ documents/
│   │   └─ ...
│   └─ temp/              # 临时文件
│
├─ static/                # 静态资源
│   ├─ images/
│   │   ├─ common/       # 公共图片
│   │   └─ {module}/      # 模块图片
│   ├─ css/
│   ├─ js/
│   └─ fonts/
│
├─ exports/               # 导出文件
│   ├─ reports/
│   └─ backups/
│
└─ workspace/             # 工作空间
```

**文件命名规范**
```python
# 文件命名格式
FILE_NAMING = {
    # 用户上传
    "avatar": "{user_id}/avatar_{timestamp}.{ext}",
    "document": "{user_id}/{yyyy}/{MM}/{original_name}_{timestamp}.{ext}",
    
    # 临时文件
    "temp": "temp/{session_id}/{filename}",
    
    # 系统生成
    "export": "exports/{type}/{yyyyMMdd}_{type}_{uuid}.{ext}",
    
    # 缓存文件
    "cache": "cache/{hash_key}.{ext}"
}

# 示例
# 用户头像：1001/avatar_1705315200.jpg
# 用户文档：1001/2024/01/简历_1705315200.pdf
# 导出报表：exports/report/20240115_report_abc123.xlsx
```

### 4. 云存储设计

**主流云存储对比**
```
┌──────────────┬─────────────┬─────────────┬─────────────┬─────────────┐
│   服务      │    厂商     │    特点     │   CDN      │   价格      │
├──────────────┼─────────────┼─────────────┼─────────────┼─────────────┤
│  OSS        │   阿里云    │ 生态完善    │   集成      │   低        │
│  S3         │   AWS       │ 标准兼容    │   CloudFront│   中        │
│  COS        │   腾讯云    │ 性价比高    │   集成      │   低        │
│  OBS        │   华为云    │ 安全特性    │   集成      │   低        │
│  GCS        │   Google    │ AI集成      │   集成      │   中        │
└──────────────┴─────────────┴─────────────┴─────────────┴─────────────┘
```

**OSS 最佳实践**
```python
# 阿里云 OSS 设计
OSS_CONFIG = {
    "bucket": "my-bucket",
    "region": "oss-cn-hangzhou",
    "endpoint": "oss-cn-hangzhou.aliyuncs.com",
    
    # 目录结构
    "dir_structure": {
        "public": "public/{project}/{module}/{filename}",
        "private": "private/{app_id}/{user_id}/{year}/{month}/{filename}",
        "temp": "temp/{session_id}/{filename}",
    },
    
    # 访问控制
    "policy": {
        "public_read": ["public/*"],
        "private_read": ["private/*"],
        "upload_path": ["uploads/*"]
    }
}

# S3 兼容设计
S3_CONFIG = {
    "bucket": "my-bucket",
    "region": "us-east-1",
    
    # 生命周期规则
    "lifecycle": {
        "temp_files": {
            "prefix": "temp/",
            "expiration_days": 7
        },
        "archives": {
            "prefix": "archives/",
            "transition_days": 30,
            "storage_class": "GLACIER"
        }
    }
}
```

### 5. 文件访问控制

**访问权限模型**
```
文件访问控制
│
├─ 公开文件（无需认证）
│   └── 静态资源、公开文档
│   └── URL: https://cdn.example.com/images/logo.png
│
├─ 私有文件（需签名）
│   └── 用户上传、付费内容
│   └── URL: https://oss.example.com/private/user_1001/doc.pdf?Signature=xxx
│
├─ 带权限文件（RBAC）
│   └── 业务文档、内部文件
│   └── 需要检查用户权限
│
└─ 临时文件（有时效）
│   └── 分享链接、验证码
│   └── URL 带过期时间
```

**私有文件访问流程**
```python
def get_private_file_url(file_path: str, user_id: int) -> str:
    # 1. 检查用户权限
    if not check_file_permission(file_path, user_id):
        raise PermissionError("无权限访问")
    
    # 2. 生成签名URL（有效期1小时）
    signed_url = oss_client.sign_url(
        bucket="private-bucket",
        key=file_path,
        expires=3600  # 1小时
    )
    
    return signed_url

def upload_file(file_obj, target_path: str, user_id: int) -> str:
    # 1. 检查上传权限
    if not check_upload_permission(user_id, target_path):
        raise PermissionError("无上传权限")
    
    # 2. 检查文件类型
    if not allowed_file_type(file_obj.name):
        raise ValueError("不支持的文件类型")
    
    # 3. 检查文件大小
    if file_obj.size > MAX_FILE_SIZE:
        raise ValueError("文件大小超出限制")
    
    # 4. 生成唯一文件名
    filename = generate_unique_filename(file_obj.name)
    full_path = f"{target_path}/{filename}"
    
    # 5. 上传到OSS
    oss_client.upload_file(full_path, file_obj)
    
    # 6. 返回访问URL
    return f"https://oss.example.com/{full_path}"
```

### 6. 文件处理流程

**上传处理管道**
```python
# 文件上传处理
UPLOAD_PIPELINE = [
    {
        "step": "1. 文件类型校验",
        "action": "检查扩展名、MIME类型",
        "reject": "不支持的文件类型"
    },
    {
        "step": "2. 文件大小校验",
        "action": "检查文件大小",
        "reject": "文件大小超出限制"
    },
    {
        "step": "3. 安全扫描",
        "action": "病毒扫描、恶意内容检测",
        "reject": "文件包含恶意内容"
    },
    {
        "step": "4. 内容审核",
        "action": "图片鉴黄、文本敏感词",
        "reject": "内容审核不通过"
    },
    {
        "step": "5. 格式转换",
        "action": "图片压缩、格式标准化",
        "output": "转换后的文件"
    },
    {
        "step": "6. 生成缩略图",
        "action": "为图片生成不同尺寸缩略图",
        "output": "thumb_xxx.jpg"
    },
    {
        "step": "7. 提取元数据",
        "action": "EXIF、文档信息",
        "output": "metadata.json"
    },
    {
        "step": "8. 上传存储",
        "action": "上传到OSS/S3",
        "output": "文件URL"
    },
    {
        "step": "9. 写入数据库",
        "action": "保存文件元信息",
        "output": "file_id"
    }
]
```

### 7. 存储优化策略

**多级存储架构**
```
多级存储架构
│
├─ L1: 本地缓存 (SSD)
│   ├── 容量: 100GB
│   ├── 访问: 毫秒级
│   └── 用途: 热点文件缓存
│
├─ L2: 对象存储 (OSS/S3)
│   ├── 容量: 无限制
│   ├── 访问: 毫秒级
│   └── 用途: 主存储
│
├─ L3: 低频存储 (IA)
│   ├── 容量: 无限制
│   ├── 访问: 分钟级
│   └── 用途: 30天前冷数据
│
└─ L4: 归档存储 (Archive)
    ├── 容量: 无限制
    ├── 访问: 小时级
    └── 用途: 1年前历史数据
```

**生命周期管理**
```python
# 存储生命周期策略
LIFECYCLE_POLICY = {
    "rules": [
        {
            "name": "temp-cleanup",
            "prefix": "temp/",
            "expiration_days": 7
        },
        {
            "name": "logs-archival",
            "prefix": "logs/",
            "transitions": [
                {"days": 30, "storage_class": "IA"},
                {"days": 90, "storage_class": "ARCHIVE"},
                {"days": 365, "storage_class": "DEEP_ARCHIVE"}
            ]
        },
        {
            "name": "thumbnails",
            "prefix": "thumbnails/",
            "expiration_days": 60
        }
    ]
}
```

### 8. 文件监控指标

**需要监控的指标**
```python
STORAGE_METRICS = {
    # 容量指标
    "total_size": "总存储量",
    "used_size": "已使用空间",
    "file_count": "文件数量",
    "avg_file_size": "平均文件大小",
    
    # 访问指标
    "download_count": "下载次数",
    "upload_count": "上传次数",
    "hit_rate": "缓存命中率",
    "avg_latency": "平均访问延迟",
    
    # 错误指标
    "upload_errors": "上传失败数",
    "download_errors": "下载失败数",
    "storage_errors": "存储错误数",
    
    # 安全指标
    "auth_failures": "认证失败次数",
    "permission_denied": "权限拒绝次数"
}
```

## 设计决策清单

```
✓ 文件存储设计检查
├── [ ] 选择了合适的存储方案？
├── [ ] 目录结构是否规范？
├── [ ] 文件命名是否清晰？
├── [ ] 访问控制策略是否完善？
├── [ ] 是否有多级存储架构？
├── [ ] 生命周期管理是否配置？
├── [ ] 上传安全检查是否完整？
├── [ ] 有监控告警机制？
├── [ ] 有备份和恢复方案？
└── [ ] CDN 加速是否需要？
```
