# AstrBot DSH NOVA QA

[![AstrBot Plugin](https://img.shields.io/badge/AstrBot-plugin-6f42c1.svg)](https://github.com/topics/astrbot-plugin)
[![DSH](https://img.shields.io/badge/DeepSeek-Harness-2f81f7.svg)](https://github.com/deepseek-ai/deepseek-harness)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

一个独立的 AstrBot QQ 插件：把白名单群中直接 `@机器人` 的文本提问，以及白名单好友私聊发送的 `/cac <问题>`，转发给已经安装 NOVA QA Bundle 的 DeepSeek Harness，并把最终回答发回原会话。

插件不安装 DSH、不读取知识库文件，也不接管 DSH 的 Workspace、Preset、权限或工具路径。它只负责 QQ 会话分流、发送者元数据、顺序提交和回复投递。

## 行为

- 仅处理 `aiocqhttp`、QQ 官方机器人和 QQ 官方 Webhook 的群聊或好友私聊消息。
- 群 ID 必须出现在 `group_whitelist`；好友 QQ ID 必须出现在 `user_whitelist`。
- 群消息必须直接 `@机器人`；普通群消息、唤醒词、仅 `@其他人` 和没有显式 At 的回复消息不触发。
- 白名单好友私聊无需 @，但必须使用字面量 `/cac <问题>`；普通私聊、`cac <问题>` 和其他命令不触发。
- 群聊中的 `@机器人 /其他命令` 会放行给已有命令插件，不会被 NOVA QA 接管。
- 满足白名单及群触发条件的消息会先于普通优先级的通用问答处理器接管，避免其他插件拒绝该群后提前停止事件传播。
- 每个 `bot_id + group_id` 对应一个稳定的 DSH Session，同群上下文连续，不同群完全分开。
- 每个 `bot_id + sender_id` 对应另一个 `qq-private` Session；好友私聊不会与任何群聊共享上下文。
- 同一 Session 的消息严格按 FIFO 顺序逐条处理和回复，上一轮结束后才处理下一条；不同 Session 仍可并发。
- 群聊的正常回答、用法提示、限额提示和故障提示都会引用触发它们的原消息，便于多人同时提问时对应上下文。
- 每个 Session 默认最多接受最近 3600 秒内的 20 个问题；达到上限会自动回复提示，其他群和好友 Session 不受影响。
- DSH 必须只注册一个名为 `NOVA知识库` 的 Workspace，新 Session 必须解析为 `nova-qa` Preset，否则插件拒绝工作。
- DSH 失败或超时时，原会话只收到简短的暂不可用提示，详细错误留在 AstrBot 日志。

## 要求

- AstrBot `>=4.17,<5`，已配置一个受支持的 QQ 平台适配器
- Python 3.10+
- 可访问的 DeepSeek Harness Web RPC
- 已安装 [NOVA Knowledge QA Bundle](https://github.com/whyself/dsh-knowledge-qa-plugin)

## 从 AstrBot 控制台安装

打开 AstrBot WebUI 的插件管理页面，选择从 GitHub 仓库安装，填写：

```text
https://github.com/whyself/astrbot_plugin_dsh_nova_qa
```

AstrBot 会读取 `metadata.yaml` 并自动安装 `requirements.txt` 中的 `httpx`。安装完成后进入插件配置页面填写群白名单和 DSH 地址，然后重载插件。

## 控制面板配置

| 字段 | 默认值 | 用途 |
| --- | --- | --- |
| `dsh_base_url` | 空 | 优先使用控制台值；留空读取 `DSH_BASE_URL`；仍为空则使用 `http://127.0.0.1:3081` |
| `group_whitelist` | `[]` | 允许触发的 QQ 群 ID。QQ 官方机器人填写事件提供的 `group_openid` |
| `user_whitelist` | `[]` | 允许通过私聊 `/cac <问题>` 触发的 QQ 用户 ID；QQ 官方机器人填写发送者 `openid` |
| `session_hourly_limit` | `20` | 每个群或好友 Session 最近 3600 秒内允许的问题数；`0` 表示关闭限额 |
| `request_timeout_seconds` | `15` | 单次 DSH HTTP RPC 的网络超时 |
| `response_timeout_seconds` | `180` | 等待一轮 DSH 回答完成的总时限 |
| `poll_interval_seconds` | `0.5` | 查询 Session 历史的间隔 |

两个白名单都为空时插件不会处理任何消息。DSH 地址也可以在 AstrBot 进程环境中设置：

```bash
export DSH_BASE_URL=http://127.0.0.1:3081
```

限额只保存在 AstrBot 插件进程内存中；插件重载或 AstrBot 重启后重新计数。只有通过限额检查、准备提交给 DSH 的有效问题才计数，空问题和未触发消息不计数。

`DSH_HOME`、`DSH_QA_WORKSPACE` 和 `DEEPSEEK_API_KEY` 属于 DSH 服务，不应填入 AstrBot 插件配置。

## 发送给 NOVA QA 的消息

每次提问使用两个 DSH text content block。第一个是群消息来源：

```json
{
  "source_type": "qq_group",
  "platform": "aiocqhttp",
  "platform_id": "qq-main",
  "bot_id": "机器人账号",
  "group_id": "群号或 group_openid",
  "message_id": "原消息 ID",
  "timestamp": 1786975200,
  "sender_id": "发送用户 ID",
  "sender_name": "发送用户昵称",
  "trigger": "at_bot",
  "mentions": [
    {
      "user_id": "被 At 用户的 QQ 号",
      "display_name": "适配器解析出的群昵称"
    }
  ],
  "reply_to": {
    "message_id": "被引用消息 ID",
    "sender_id": "被引用消息作者 ID",
    "sender_name": "被引用消息作者昵称",
    "sender_role": "assistant 或 user",
    "text": "被引用的旧消息"
  }
}
```

`trigger` 为 `at_bot`。`mentions` 只包含机器人之外的被 At 用户；aiocqhttp 适配器会解析其 QQ 号和群昵称，插件不会保留 `@Novabot`。`reply_to` 仅在原消息同时含 Reply 段和显式机器人 At 时出现，表示被引用的旧消息及其作者；没有显式 `@Novabot` 的回复不会触发插件。第二个 block 是当前发送者的原始文本。`nova-qa` Persona 使用稳定的 `sender_id` 区分参与者，用 `sender_name` 称呼对方；插件不会把用户 ID 直接写进群回复。

好友私聊使用相同的两块结构，但第一块标签是 `private_message_metadata`，来源字段为：

```json
{
  "source_type": "qq_private",
  "platform": "aiocqhttp",
  "platform_id": "qq-main",
  "bot_id": "机器人账号",
  "peer_id": "发送用户 ID",
  "message_id": "原消息 ID",
  "timestamp": 1787011200,
  "sender_id": "发送用户 ID",
  "sender_name": "发送用户昵称",
  "trigger": "slash_cac"
}
```

第二块只包含去掉 `/cac` 后的原始问题。群聊和私聊 Session ID 分别以 `qq-group-`、`qq-private-` 开头，避免上下文混合。

## DSH 调用流程

1. `workspace.list` 验证唯一的 `NOVA知识库`。
2. `session.create` 用稳定 Session ID 幂等创建或恢复群聊/私聊会话，并验证 `agentPreset: nova-qa`。
3. `session.history` 记录提交前的最后序号。
4. `session.prompt` 提交来源元数据和用户问题。
5. 轮询 `session.history`，等待新的 `turn/end: completed`，提取该边界内最后一条 `assistant/message` 文本。

## 安全

DSH 原生 `/api` 同时包含 Settings、Credentials、Workspace 等管理接口，不能直接暴露到公网。AstrBot 与 DSH 在同一服务器时优先使用 `127.0.0.1`；容器部署应放在仅两个服务可访问的私有网络中，不要把 DSH 端口映射到公网。

## 开发验证

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

完整服务器部署顺序见 [部署清单](docs/deployment.md)。

## License

[MIT](LICENSE)
