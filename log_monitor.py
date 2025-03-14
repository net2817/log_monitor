import os
import time
import yaml
import hmac
import base64
import hashlib
import logging
import schedule
import requests
import threading
import glob
from queue import Queue, PriorityQueue
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from elasticsearch import Elasticsearch
from elastic_transport import ConnectionError, ConnectionTimeout
from elasticsearch.exceptions import ApiError, TransportError
import logging.handlers

class AlertMessage:
    """告警消息类"""
    def __init__(self, priority: int, rule_name: str, message: str):
        self.priority = priority
        self.rule_name = rule_name
        self.message = message
        self.timestamp = time.time()

    def __lt__(self, other):
        # 优先级队列比较方法
        return (self.priority, -self.timestamp) < (other.priority, -other.timestamp)

class AlertChannel:
    """告警通道基类"""
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._setup_channel()

    def _setup_channel(self):
        """初始化通道"""
        raise NotImplementedError

    def send(self, message: str) -> bool:
        """发送消息"""
        raise NotImplementedError

class LarkChannel(AlertChannel):
    """飞书Webhook告警通道"""
    def _setup_channel(self):
        self.token = self.config['token']
        self.base_url = self.config.get('base_url', 'https://open.feishu.cn/open-apis/bot/v2/hook/')
        self.retry_times = self.config.get('retry_times', 3)
        self.retry_interval = self.config.get('retry_interval', 5)
        self.templates = self.config.get('templates', {})
        # 构建完整的 webhook URL
        self.webhook_url = f"{self.base_url}{self.token}"

    def send(self, message: str) -> bool:
        """发送消息到飞书"""
        for attempt in range(self.retry_times):
            try:
                response = requests.post(
                    self.webhook_url,
                    json={
                        "msg_type": "text",
                        "content": {"text": message}
                    },
                    timeout=10
                )
                response.raise_for_status()
                logging.info("告警消息发送成功")
                return True
            except requests.exceptions.RequestException as e:
                logging.error(f"发送告警失败: {str(e)}")
                if attempt < self.retry_times - 1:
                    logging.info(f"等待{self.retry_interval}秒后重试...")
                    time.sleep(self.retry_interval)
        return False

class AlertManager:
    """告警管理器"""
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.channels: Dict[str, AlertChannel] = {}
        self.alert_queue = PriorityQueue()
        self._setup_channels()
        self._start_worker()

    def _setup_channels(self):
        """初始化告警通道"""
        channel_configs = self.config.get('alert_channels', {})
        if 'lark' in channel_configs:
            self.channels['lark'] = LarkChannel(channel_configs['lark'])

    def _start_worker(self):
        """启动告警处理线程"""
        self._worker_thread = threading.Thread(target=self._process_alerts, daemon=True)
        self._worker_thread.start()

    def _process_alerts(self):
        """处理告警队列"""
        while True:
            try:
                alert = self.alert_queue.get()
                if alert is None:
                    break
                
                for channel_name in self.channels:
                    channel = self.channels[channel_name]
                    channel.send(alert.message)
                
                self.alert_queue.task_done()
            except Exception as e:
                logging.error(f"处理告警失败: {str(e)}")

    def send_alert(self, priority: int, rule_name: str, message: str):
        """发送告警"""
        alert = AlertMessage(priority, rule_name, message)
        self.alert_queue.put(alert)

class DailyRotatingFileHandler(logging.handlers.BaseRotatingHandler):
    """按天轮转的日志处理器，使用日期作为后缀"""
    
    def __init__(self, filename, encoding='utf-8', backup_count=7):
        self.backup_count = backup_count
        super().__init__(filename, 'a', encoding=encoding)
        self.suffix = "%Y-%m-%d"
        self.base_filename = filename

    def shouldRollover(self, record):
        """判断是否需要轮转"""
        if not os.path.exists(self.baseFilename):
            return False
            
        current_date = datetime.now().strftime(self.suffix)
        if self.baseFilename.endswith(current_date):
            return False
            
        return True

    def doRollover(self):
        """执行日志轮转"""
        if self.stream:
            self.stream.close()
            self.stream = None

        # 生成当前日志文件名
        current_date = datetime.now().strftime(self.suffix)
        new_filename = f"{self.base_filename}.{current_date}"
        
        # 如果当前日期的日志文件已存在，先删除
        if os.path.exists(new_filename):
            os.remove(new_filename)
            
        # 重命名当前日志文件
        if os.path.exists(self.base_filename):
            os.rename(self.base_filename, new_filename)

        # 创建新的日志文件
        self.mode = 'a'
        self.stream = self._open()

        # 删除过期的日志文件
        self._remove_old_logs()

    def _remove_old_logs(self):
        """删除过期的日志文件"""
        if self.backup_count > 0:
            # 获取所有日志文件
            log_files = glob.glob(f"{self.base_filename}.*")
            if len(log_files) > self.backup_count:
                log_files.sort()  # 按日期排序
                for f in log_files[:-self.backup_count]:  # 保留最新的文件
                    try:
                        os.remove(f)
                    except OSError:
                        pass

def setup_logging(config: Dict[str, Any]):
    """设置日志配置"""
    log_config = config['basic']['log']
    
    # 创建日志目录
    log_file = config['basic']['file']['path']
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    # 创建日志处理器
    file_handler = DailyRotatingFileHandler(
        filename=log_file,
        backup_count=config['basic']['file']['backup_count'],
        encoding='utf-8'
    )
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    
    # 设置格式
    formatter = logging.Formatter(
        fmt=log_config['format'],
        datefmt=log_config['date_format']
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # 配置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_config['level']))
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

class LogMonitor:
    """日志监控器"""
    def __init__(self, config_path: str):
        """初始化监控器"""
        logging.info(f"正在加载配置文件: {config_path}")
        self.config = self._load_config(config_path)
        logging.info("配置文件加载成功")
        
        logging.info("正在初始化日志系统...")
        setup_logging(self.config)
        logging.info("日志系统初始化完成")
        
        logging.info("正在连接 Elasticsearch 集群...")
        self.es_clients = self._init_elasticsearch_clients()
        logging.info("Elasticsearch 集群连接成功")
        
        logging.info("正在初始化告警管理器...")
        self.alert_manager = AlertManager(self.config)
        logging.info("告警管理器初始化完成")
        
        self.last_alert_times = {}
        logging.info(f"正在创建线程池(大小: {self.config['monitor']['scan']['concurrent_rules']})...")
        self.thread_pool = ThreadPoolExecutor(
            max_workers=self.config['monitor']['scan']['concurrent_rules']
        )
        logging.info("线程池创建完成")

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """加载配置"""
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def _init_elasticsearch_clients(self) -> Dict[str, Elasticsearch]:
        """初始化ES客户端"""
        es_config = self.config['elasticsearch']
        clients = {}
        
        for cluster in es_config['clusters']:
            # 基础连接配置
            client_config = {
                'hosts': cluster['hosts'],
                'timeout': es_config.get('timeout', 30),
                'retry_on_timeout': True,
                'max_retries': es_config['retry']['max_retries']
            }
            
            # 认证配置
            if cluster.get('username') and cluster.get('password'):
                client_config['basic_auth'] = (cluster['username'], cluster['password'])
            
            # SSL配置
            if cluster.get('ssl'):
                client_config['verify_certs'] = True
                if 'ca_certs' in cluster:
                    client_config['ca_certs'] = cluster['ca_certs']
            
            try:
                client = Elasticsearch(**client_config)
                # 测试连接
                if client.ping():
                    clients[cluster['name']] = client
                    logging.info(f"成功连接到ES集群: {cluster['name']}")
                else:
                    logging.error(f"无法连接到ES集群: {cluster['name']}")
            except Exception as e:
                logging.error(f"初始化ES客户端失败 ({cluster['name']}): {str(e)}")
        
        if not clients:
            raise RuntimeError("没有可用的ES集群连接")
        
        return clients

    def _build_query(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        """构建ES查询"""
        conditions = rule['conditions']
        query = {
            "bool": {
                "must": [],
                "must_not": [],
                "filter": []
            }
        }

        # 添加日志保留时间限制
        retention_days = self.config['elasticsearch'].get('retention', {}).get('days', 7)
        query['bool']['filter'].append({
            "range": {
                "@timestamp": {
                    "gte": f"now-{retention_days}d",
                    "lte": "now"
                }
            }
        })

        # 关键词匹配
        if 'keywords' in conditions:
            query['bool']['must'].append({
                "multi_match": {
                    "query": " ".join(conditions['keywords']),
                    "fields": ["message", "log_message", "content"]
                }
            })

        # 排除关键词
        if 'exclude_keywords' in conditions:
            query['bool']['must_not'].append({
                "multi_match": {
                    "query": " ".join(conditions['exclude_keywords']),
                    "fields": ["message", "log_message", "content"]
                }
            })

        # 字段匹配
        if 'fields' in conditions:
            for field, value in conditions['fields'].items():
                query['bool']['must'].append({
                    "match": {field: value}
                })

        # 告警时间窗口
        time_window = rule['alert']['time_window']
        query['bool']['filter'].append({
            "range": {
                "@timestamp": {
                    "gte": f"now-{time_window}m"
                }
            }
        })

        return query

    def check_rule(self, rule: Dict[str, Any]):
        """检查单个规则"""
        try:
            if not rule.get('enabled', True):
                logging.info(f"规则 '{rule['name']}' 已禁用，跳过检查")
                return

            logging.info(f"开始检查规则 '{rule['name']}':")
            logging.info(f"- 描述: {rule.get('description', '无')}")
            logging.info(f"- 集群: {rule.get('cluster', '默认')}")
            logging.info(f"- 索引: {rule['index']}")
            
            query = self._build_query(rule)
            logging.debug(f"- 查询条件: {query}")
            
            cluster_name = rule.get('cluster', next(iter(self.es_clients.keys())))
            if cluster_name not in self.es_clients:
                logging.error(f"规则 '{rule['name']}' 指定的集群 '{cluster_name}' 不存在")
                raise ValueError(f"未找到集群: {cluster_name}")
            
            es_client = self.es_clients[cluster_name]
            
            logging.info(f"正在执行ES查询...")
            response = es_client.search(
                index=rule['index'],
                query=query,
                size=rule['alert']['max_samples']
            )

            hit_count = response['hits']['total']['value']
            logging.info(f"查询完成: 匹配到 {hit_count} 条日志")
            
            if hit_count >= rule['alert']['threshold']:
                logging.info(f"超过告警阈值({hit_count} >= {rule['alert']['threshold']})")
                current_time = time.time()
                last_alert = self.last_alert_times.get(rule['name'], 0)
                
                if current_time - last_alert >= rule['alert']['interval']:
                    logging.info("准备发送告警...")
                    self.last_alert_times[rule['name']] = current_time
                    
                    template_name = rule['alert']['template']
                    template = self.config['alert_channels']['lark']['templates'][template_name]
                    
                    message = template.format(
                        service=rule['conditions']['fields'].get('service', 'unknown'),
                        time_range=f"最近{rule['alert']['time_window']}分钟",
                        count=hit_count,
                        sample_messages=self._format_samples(response['hits']['hits'])
                    )
                    
                    priority = {'high': 0, 'medium': 1, 'low': 2}.get(rule['priority'], 1)
                    logging.info(f"发送优先级 {rule['priority']} 的告警...")
                    self.alert_manager.send_alert(priority, rule['name'], message)
                else:
                    logging.info(f"在告警间隔期内({rule['alert']['interval']}秒)，跳过告警")
            else:
                logging.info(f"未达到告警阈值({hit_count} < {rule['alert']['threshold']})")
            
        except Exception as e:
            logging.exception(f"检查规则 '{rule['name']}' 失败:")

    def _format_samples(self, hits: List[Dict[str, Any]]) -> str:
        """格式化日志样例"""
        samples = []
        for hit in hits:
            source = hit.get('_source', {})
            message = source.get('message', 'N/A')
            timestamp = source.get('@timestamp', 'N/A')
            samples.append(f"[{timestamp}] {message}")
        return "\n".join(samples)

    def run_checks(self):
        """执行所有规则检查"""
        futures = []
        for rule in self.config['alert_rules']:
            futures.append(
                self.thread_pool.submit(self.check_rule, rule)
            )
        
        for future in futures:
            try:
                future.result()
            except Exception as e:
                logging.error(f"规则检查失败: {str(e)}")

    def start(self):
        """启动监控"""
        scan_interval = self.config['monitor']['scan']['interval']
        logging.info("=== 监控服务启动 ===")
        logging.info(f"扫描间隔: {scan_interval} 秒")
        logging.info(f"规则数量: {len(self.config['alert_rules'])}")
        
        try:
            logging.info("执行首次规则检查...")
            self.run_checks()
            logging.info("首次检查完成")
            
            logging.info("设置定时任务...")
            schedule.every(scan_interval).seconds.do(self.run_checks)
            logging.info("进入主循环...")
            
            while True:
                try:
                    schedule.run_pending()
                    time.sleep(1)
                except KeyboardInterrupt:
                    logging.info("收到停止信号")
                    break
                except Exception as e:
                    logging.exception("运行出错:")
                    time.sleep(5)
                    
        finally:
            logging.info("正在关闭线程池...")
            self.thread_pool.shutdown()
            logging.info("=== 监控服务已停止 ===")

def main():
    """主函数"""
    try:
        logging.info("=== 日志监控程序启动 ===")
        logging.info("正在加载配置文件...")
        monitor = LogMonitor("config.yaml")
        logging.info("配置加载完成，开始监控...")
        monitor.start()
    except Exception as e:
        logging.exception("程序启动失败:")
        exit(1)

if __name__ == "__main__":
    main() 