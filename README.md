# ES日志监控告警系统

## 项目概述

ES日志监控告警系统是一个基于Elasticsearch的日志监控工具，可以定期检查ES中的日志数据，根据预设规则自动触发告警，并通过飞书等渠道发送通知。系统采用多线程并发处理，支持多ES集群，具备灵活的告警规则配置和可靠的错误处理机制。

## 主要功能

- **实时日志监控**：定期查询ES集群中的日志数据
- **灵活的告警规则**：支持关键词匹配、字段精确匹配、阈值控制等多种规则配置
- **多集群支持**：可同时连接和监控多个ES集群
- **并发处理**：使用线程池并发执行规则检查，提高效率
- **告警优先级**：支持高、中、低三级告警优先级处理
- **异步告警发送**：通过队列异步发送告警，避免阻塞主流程
- **告警重试机制**：发送失败自动重试，提高告警可靠性
- **日志轮转**：自动按日期轮转程序日志，方便管理
- **错误处理**：完善的异常捕获和处理机制，提高系统稳定性

## 技术架构

- **核心组件**：
  - `LogMonitor`：日志监控主类，负责规则检查和调度
  - `AlertManager`：告警管理器，负责告警队列处理
  - `LarkChannel`：飞书告警通道，负责发送告警消息
  - `DailyRotatingFileHandler`：日志轮转处理器

- **执行流程**：
  1. 加载配置文件
  2. 初始化ES客户端连接
  3. 创建告警管理器和告警通道
  4. 按设定间隔并发执行规则检查
  5. 根据规则检查结果发送告警

## 配置说明

系统配置采用YAML格式，主要包含以下部分：

```yaml
# 基础配置
basic:
  # 日志配置
  log:
    level: INFO  # 日志级别：DEBUG/INFO/WARNING/ERROR
    format: "[%(asctime)s] %(levelname)s: %(message)s"  # 日志格式
    date_format: "%Y-%m-%d %H:%M:%S"  # 日期格式
  file:
    path: "logs/monitor.log"  # 日志文件路径
    backup_count: 7  # 保留日志文件数量(天)

# Elasticsearch配置
elasticsearch:
  # ES集群配置
  clusters:
    - name: "es-cluster"  # 集群名称
      hosts:  # ES服务器地址
        - "http://es1:9200"
        - "http://es2:9200"
      username: "elastic"  # 用户名
      password: "password"  # 密码
      ssl: false  # 是否启用SSL
  timeout: 30  # 连接超时时间(秒)
  retention:
    days: 7  # 日志保留天数
  # 重试配置
  retry:
    max_retries: 3  # 最大重试次数
    retry_interval: 5  # 重试间隔(秒)

# 告警通道配置
alert_channels:
  lark:  # 飞书机器人配置
    token: "your-token-here"  # 飞书机器人Token
    base_url: "https://open.feishu.cn/open-apis/bot/v2/hook/"  # API基址
    retry_times: 3  # 发送失败重试次数
    retry_interval: 5  # 重试间隔(秒)
    # 消息模板
    templates:
      error: |  # 错误告警模板
        【严重告警】发现异常日志
        服务: {service}
        时间范围: {time_range}
        错误数量: {count}
        样例消息:
        {sample_messages}
      warning: |  # 警告告警模板
        【警告通知】发现警告日志
        服务: {service}
        时间范围: {time_range}
        警告数量: {count}
        样例消息:
        {sample_messages}

# 监控配置
monitor:
  scan:
    interval: 300  # 扫描间隔(秒)
    batch_size: 1000  # 每批处理数量
    concurrent_rules: 5  # 并发规则数
  indices:
    - pattern: "prod-*"  # 索引模式
      description: "prod日志索引"

# 告警规则配置
alert_rules:
  - name: "Error Log Alert"  # 规则名称
    enabled: true  # 是否启用
    description: "检测ERROR级别日志"  # 规则描述
    cluster: "es-cluster"  # 使用的ES集群
    index: "prod-*"  # 查询的索引
    priority: "high"  # 优先级(high/medium/low)
    
    # 匹配条件
    conditions:
      keywords: ["error", "exception", "failed"]  # 匹配关键词
      fields:  # 字段精确匹配
        level: "ERROR"
        service: "prod"
      exclude_keywords: ["expected", "handled"]  # 排除关键词
    
    # 告警配置
    alert:
      threshold: 10  # 告警阈值(超过多少条触发)
      time_window: 5  # 时间窗口(分钟)
      interval: 300  # 告警间隔(秒)
      max_samples: 3  # 最大样例数
      template: "error"  # 使用的模板
      channels: ["lark"]  # 告警通道
```

## 使用方法

### 安装依赖

```bash
pip install -r requirements.txt
```

### 修改配置

1. 复制并修改配置文件
```bash
cp config.yaml.example config.yaml
# 编辑config.yaml设置你的ES和飞书配置
```

2. 设置告警规则
```yaml
alert_rules:
  - name: "My Custom Rule"
    # 配置你的告警规则...
```

### 运行程序

```bash
python log_monitor.py
```

### 后台运行

```bash
nohup python log_monitor.py > /dev/null 2>&1 &
```

## 告警规则说明

每个告警规则包含以下主要部分：

1. **基本信息**：
   - `name`：规则名称
   - `enabled`：是否启用
   - `description`：规则描述
   - `cluster`：使用的ES集群
   - `index`：查询的索引
   - `priority`：告警优先级

2. **匹配条件**：
   - `keywords`：匹配任一关键词(或)
   - `fields`：字段精确匹配(与)
   - `exclude_keywords`：排除关键词

3. **告警配置**：
   - `threshold`：告警阈值
   - `time_window`：时间窗口(分钟)
   - `interval`：告警间隔(秒)
   - `max_samples`：最大样例数
   - `template`：消息模板
   - `channels`：告警通道

## 日志说明

程序日志存储在配置的路径(默认为logs/monitor.log)，按日期自动轮转，格式为：
- 当天日志：monitor.log
- 历史日志：monitor.log.2024-01-20

日志包含详细的运行信息、规则检查过程、告警发送状态和错误信息，便于排查问题。

## 故障排除

1. **ES连接失败**：
   - 检查ES集群地址和认证信息
   - 确认网络连接和防火墙设置

2. **规则不触发**：
   - 检查规则的enabled是否为true
   - 确认阈值和时间窗口设置是否合理
   - 验证索引模式是否匹配

3. **告警发送失败**：
   - 检查飞书token是否正确
   - 确认网络连接和重试配置

4. **程序性能问题**：
   - 调整concurrent_rules参数
   - 优化查询条件减少ES负担

## 未来优化方向

1. 添加更多告警通道(如邮件、企业微信等)
2. 支持告警消息自定义格式化
3. 增加Web管理界面
4. 添加告警抑制和聚合功能
5. 增加监控指标统计和可视化
6. 规则动态加载和热更新 