# 照看 · 技术实现说明

2026-09-22提交核对版。以当前代码与接口为准。

## 架构与职责

Python 3.11+、FastAPI和Uvicorn提供服务。前端使用本地HTML、CSS和JavaScript，无需前端构建；产品与演示页共用浅色样式。SQLite WAL保存任务及检查记录，通过事务保证提醒、去重信息与任务状态一起提交。

| 模块 | 实际职责 |
| --- | --- |
| `app/main.py` | HTTP接口、访客隔离、输入校验与静态页面 |
| `app/config.py` | 读取项目环境配置；凭据不进入前端或提交包 |
| `app/models/dsl.py` | TaskSpec及请求模型，拒绝未知字段与无效组合 |
| `app/core/nlp_compiler.py` | DeepSeek整理条件、本地回退、澄清及编译记录 |
| `app/core/scheduler.py` | 持续调度、恢复检查、并发控制 |
| `app/core/state_machine.py` | 条件判断、状态与提醒决策 |
| `app/core/audit_logger.py` | SQLite持久化及检查记录 |
| `app/adapters/live.py` | 独立获取行情和公告，隔离单个来源失败 |
| `app/adapters/fuyao_adapter.py` | 官方REST行情和交易日历；有效性校验及有限重试 |
| `app/adapters/ifind_adapter.py`、`ifind_bridge.cjs` | 通过已配置的Node模块调用公告检索，构造事件指纹 |
| `app/product.py` | 当前访客运行统计与反馈 |

AI只提取条件，不做持续行情计算、公告归因或交易执行。真实来源失败返回相应异常，不自动切换为模拟数据。

## 接口约定

解析接口`POST /api/tasks/parse`接收`prompt`、可选`target`、`data_mode`和`use_ai`；返回`task_spec`、`compilation`和`warnings`。编译记录保留实际引擎与失败回退原因，不能将本地解析计为模型成功。

`POST /api/tasks/create`经用户确认保存任务。`GET /api/tasks`和`GET /api/tasks/{task_id}`读取任务；`PUT /api/tasks/{task_id}`修改规则并检查预期版本。暂停与恢复使用对应`/pause`和`/resume`接口；DELETE归档任务。

`/audit-trail`、`/versions`和`/export`提供检查记录、版本及证据导出；`/rollback`将历史规则恢复为新版本。`GET /api/alerts`读取站内通知。具体请求字段与响应结构见服务自动生成的`/openapi.json`；任务规则另提供`GET /api/schema`。

`POST /api/simulate/inject`仅允许模拟任务注入情景。`POST /api/simulate/tick`触发检查，不能用于向真实任务注入模拟行情。

## 调度与持久化

同一数据目录只运行一个服务进程，启动锁阻止重复调度器。任务独立加锁，最多四路并发取数；同一任务串行更新。检查按任务频率运行，默认60秒；冷却期间继续检查。待提醒公告与去重信息持久化，重启后恢复。

所有条件都保留满足、未满足或无法判断的结果。组合条件通过后仍须经过冷却和去重。规则修改生成新版本，旧提醒保留生成时证据。服务停止期间的行情路径不能补造。

## 凭据与部署

DeepSeek和扶摇凭据由后台配置提供。iFinD需要服务器上有Node及授权调用模块，使用`IFIND_SCRIPT`指定入口。源码包不包含本机私人配置；复制源码到新机器后须配置相应凭据才能使用外部服务。

无外部凭据时可以运行模拟体验与本地规则解析。完整启动命令见[README](README.md)，Docker与常驻部署条件见[部署说明](docs/DEPLOYMENT.md)。公开体验目前依赖本机和临时通道。

## 验证

功能、异常和恢复证据见[测试说明](TESTING_AND_EVAL.md)。原始批次与测量范围独立保存；真实模型结果、模拟任务结果和真实数据取数结果分别解释。
