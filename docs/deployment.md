# DSH NOVA QA 与 AstrBot 部署清单

这套部署包含三个独立部分：DSH 服务、NOVA Knowledge QA Bundle、AstrBot 及本插件。AstrBot 插件不会替你安装或启动 Node.js/DSH。

## 1. 准备服务器

- Linux 服务器安装 Node.js `^22.19` 或 `>=24`、pnpm 11、Python 3.10+。
- 创建只供 DSH 使用的系统账号和目录，例如 `/srv/nova/dsh-home`、`/srv/nova/knowledge`。
- 把 NOVA 资料放入 `/srv/nova/knowledge`，确认 DSH 服务账号只有需要的读取权限。
- 准备 DeepSeek API Key，但不要写入 Git 仓库、Preset、AstrBot 插件配置或聊天消息。

## 2. 安装 DSH 与 NOVA QA Bundle

```bash
corepack enable
corepack prepare pnpm@11.7.0 --activate
pnpm add --global @deepseek-ai/dsh@0.1.0-rc.7
```

设置一次部署环境后安装 Bundle：

```bash
export DSH_HOME=/srv/nova/dsh-home
export DSH_QA_WORKSPACE=/srv/nova/knowledge

dsh plugin --profile web add \
  https://github.com/whyself/dsh-knowledge-qa-plugin/releases/download/v0.1.0/dsh-knowledge-qa-bundle-0.1.0.tgz
```

不需要把 QA 仓库中的 `presets/` 或 `profiles/` 复制到服务器；发布包已经注册 `nova-qa` 和固定 Workspace。

## 3. 配置并启动 DSH

创建仅 root 和 DSH 服务账号可读的 `/etc/nova-dsh.env`：

```dotenv
DSH_HOME=/srv/nova/dsh-home
DSH_QA_WORKSPACE=/srv/nova/knowledge
DEEPSEEK_API_KEY=在服务器上填写真实密钥
```

建议权限：

```bash
sudo chmod 600 /etc/nova-dsh.env
```

systemd 单元示例 `/etc/systemd/system/nova-dsh.service`：

```ini
[Unit]
Description=DeepSeek Harness NOVA QA
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=nova
WorkingDirectory=/srv/nova
EnvironmentFile=/etc/nova-dsh.env
ExecStart=/usr/local/bin/dsh --profile web --port 3081
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

根据 `command -v dsh` 修改 `ExecStart`。然后启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now nova-dsh
sudo systemctl status nova-dsh
```

## 4. 验证 DSH 固定配置

在同一服务器调用只读 RPC：

```bash
curl --fail-with-body http://127.0.0.1:3081/api/workspace.list \
  -H 'content-type: application/json' \
  --data '{"type":"client-request","rpcId":"deploy-check","method":"workspace.list","payload":{}}'
```

返回值应只有一个 Workspace，标题为 `NOVA知识库`。再打开 DSH Web 页面确认默认模式为 `nova-qa`、权限为 `Read Only`。

## 5. 安装并配置 AstrBot

按照 [AstrBot 官方部署文档](https://docs.astrbot.app/what-is-astrbot) 安装 AstrBot，并在 WebUI 中完成 `aiocqhttp`、QQ 官方机器人或 QQ 官方 Webhook 适配器配置。

如果 AstrBot 直接运行在同一台主机上，在它的服务环境中加入：

```dotenv
DSH_BASE_URL=http://127.0.0.1:3081
```

也可以让插件控制台的 `dsh_base_url` 覆盖这个值。AstrBot 在 Docker 中时，容器内的 `127.0.0.1` 是容器自己；应让 AstrBot 与 DSH 进入同一个私有服务网络，并把 `DSH_BASE_URL` 指向该网络内的 DSH 服务名。不要为了连通容器而把 DSH 管理 API 暴露到公网。

## 6. 从 AstrBot 控制台安装本插件

打开 WebUI → 插件管理 → 从 GitHub 仓库安装，填写：

```text
https://github.com/whyself/astrbot_plugin_dsh_nova_qa
```

安装后进入插件配置：

1. `dsh_base_url`：同机非容器可留空；其他私有网络填写内部 DSH URL。
2. `group_whitelist`：逐项填写允许使用的群 ID；QQ 官方机器人填写 `group_openid`。
3. `user_whitelist`：逐项填写允许通过好友私聊 `/cac <问题>` 使用知识库的 QQ 用户 ID。
4. 保持 `request_timeout_seconds=15`、`response_timeout_seconds=180`、`poll_interval_seconds=0.5`，除非服务器日志表明需要调整。
5. 保存并重载插件。

## 7. 端到端验收

在一个白名单群中发送：

```text
@机器人 NOVA 是什么？
```

检查以下结果：

- 机器人只回复一次。
- 同群追问能记住上一轮；另一白名单群不会继承这个上下文。
- 非白名单群、未 @机器人、只 @其他人的消息没有响应。
- 群聊 `@机器人 /其他命令` 仍由原命令插件处理。
- DSH Web 中出现形如 `qq-group-<bot_id>-<group_id>` 的 Session，Preset 是 `nova-qa`。
- 白名单好友私聊 `/cac NOVA 是什么？` 能回答，普通私聊和非白名单好友 `/cac` 不触发。
- 好友私聊创建 `qq-private-<bot_id>-<sender_id>` Session，并且不继承群聊上下文。
- AstrBot 日志没有 DSH transport/protocol 错误，DSH 日志以 `turn/end: completed` 结束。

## 8. 运行与备份

- 只在服务器私网或回环地址开放 DSH；不要用公网反向代理直接转发整个 `/api`。
- 分别监督 DSH 和 AstrBot，任何一方重启都不会改变群到 Session 的确定性映射。
- 备份 `DSH_HOME` 保存 Session 历史和 DSH 配置；备份 AstrBot 的 `data/` 保存平台与插件配置。
- 升级前先在一个测试群验证 DSH、QA Bundle、AstrBot 和本插件四者版本组合。
