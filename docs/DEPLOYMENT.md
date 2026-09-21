# 部署与运行

## 当前演示实例

应用监听本机 `127.0.0.1:8000`，通过 Cloudflare Quick Tunnel 提供 HTTPS 访问。数据库保存在本机项目的 `data/radar.sqlite3`。服务进程、网络、电脑唤醒状态或通道任一停止，公网体验均可能中断。地址也可能在通道重建后改变。

此方式适合现场演示与短期验收，不提供长期可用性保证。需要评审在无人值守时长期访问时，应使用常驻主机、持久化磁盘和固定 HTTPS 地址。

Cloudflare 将 Quick Tunnel 定位于测试与开发，不提供 SLA 或运行时间保证，见[官方说明](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)。本项目没有把临时通道写成常驻云部署。

2026年9月21日20:14（北京时间），旧临时入口返回1033，本地健康检查仍为ok。旧通道连接处于CLOSE_WAIT；重建后使用[当前体验地址](https://intention-water-assistant-comparative.trycloudflare.com/)，已通过公网浏览器的解析、创建与模拟触发验证。数据目录及应用进程保持原样。域名变化后浏览器会取得新的访客标识，原域名下的任务仍保存在服务器，但新地址不能自动读取原访客任务。

## 三种部署路径

| 方式 | 需要准备 | 运行边界 |
| --- | --- | --- |
| 本机 + 临时通道 | 当前环境已具备 | 地址临时、依赖电脑持续运行；可快速现场验证 |
| 常驻 Linux 主机 + Docker Compose | 可登录主机、域名、HTTPS 反向代理 | 使用命名卷保存 SQLite；适合本项目当前单实例结构 |
| 多实例服务 + PostgreSQL/队列 | 独立数据库、队列、任务租约 | 需要架构扩展，当前代码不能直接开启多个 worker |

## Docker Compose 配置

项目提供 `Dockerfile` 和 `compose.yaml`。默认绑定本机端口，供 HTTPS 反向代理转发。

```bash
cp .env.example .env
# 在本机编辑 .env，配置所需 API 凭据，不提交该文件。
docker compose up -d --build
curl http://127.0.0.1:8000/api/health
```

容器以非 root 用户运行。SQLite 目录挂载到命名卷 `radar-data`；服务重启不清空该卷。禁止多个容器共享并同时运行同一个任务数据库。不要使用多个 uvicorn worker。

容器基础镜像包含 Python 服务，默认不带本机 iFinD 查询模块及其私人配置。演示、DeepSeek 和扶摇可直接通过环境变量配置；真实公告接入需要部署方在合法授权的服务器上安装 Node 和 iFinD 模块，并通过 `IFIND_SCRIPT` 指定入口。私人凭据必须通过服务器秘密配置或只读挂载提供，不应写进镜像或源码。

Docker镜像已在GitHub的Ubuntu运行器中完成构建和启动，并通过HTTP主链路检查。见[容器检查记录](../artifacts/ci-baseline/container-smoke.json)与[对应运行记录](../artifacts/ci-baseline/run.json)。这次验证使用临时CI容器，没有将产品部署到常驻云主机。

## 配置项

| 变量 | 默认值或作用 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 留空时使用本地解析 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | `deepseek-flash` |
| `FUYAO_API_KEY` | 扶摇 API 凭据，仅服务器读取 |
| `FUYAO_KEY_FILE` | 可选的本地凭据文件路径 |
| `IFIND_SCRIPT` | 已配置 iFinD 模块的 `call-node.js` 路径 |
| `RADAR_DATA_DIR` | 持久化数据目录 |
| `RADAR_AI_ENABLED` | `1` 启用模型解析，`0` 仅本地解析 |
| `RADAR_ALLOW_LIVE` | `1` 允许真实数据任务，`0` 只开放演示 |
| `RADAR_SCHEDULER` | `1` 启用自动检查，测试环境可设 `0` |
| `RADAR_SECURE_COOKIE` | 在仅 HTTPS 的生产入口设为 `1`；HTTP 本地测试设为 `0` |

## 运行检查和恢复

`GET /api/health` 返回进程启动时间、调度心跳和最近错误。`status=ok` 只说明应用检查状态；不保证所有上游均正常，也不保证每条任务在高负载时准时完成。任务自身的状态和逐条件记录才反映其数据来源结果。

服务启动后读取持久化任务，保留冷却、已提醒指纹和待提醒公告，并记录恢复事件。停机期间价格路径不能补造。公告接口成功后推进检查游标，失败不推进，后续带重叠窗口补查。

备份应使用 SQLite 在线备份接口或在服务停止后复制完整数据库；运行时只复制 `.sqlite3` 文件可能遗漏 WAL 中尚未合并的数据。上线长期实例前还需完成备份演练、磁盘容量监控、数据保留策略与上游用量监控。
