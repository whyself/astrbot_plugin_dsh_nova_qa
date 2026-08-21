# AstrBot DSH NOVA QA

[![AstrBot Plugin](https://img.shields.io/badge/AstrBot-plugin-6f42c1.svg)](https://github.com/topics/astrbot-plugin)
[![DSH](https://img.shields.io/badge/DeepSeek-Harness-2f81f7.svg)](https://github.com/deepseek-ai/deepseek-harness)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

一个独立的 AstrBot QQ 插件：把白名单群中直接 `@机器人` 的图文提问，以及白名单好友私聊发送的 `/cac <问题>` 与图片，转发给已经安装 NOVA QA Bundle 的 DeepSeek Harness，并把最终回答发回原会话。

插件不安装 DSH、不读取知识库文件，也不接管 DSH 的 Workspace、Preset、权限或工具路径。它只负责 QQ 会话分流、发送者元数据、顺序提交和回复投递。

## 行为

- 仅处理 `aiocqhttp`、QQ 官方机器人和 QQ 官方 Webhook 的群聊或好友私聊消息。
- 群 ID 必须出现在 `group_whitelist`；好友 QQ ID 必须出现在 `user_whitelist`。
- 群消息必须直接 `@机器人`；普通群消息、唤醒词、仅 `@其他人` 和没有显式 At 的回复消息不触发。
- 群图片可以与 `@机器人`、问题放在同一条消息里；aiocqhttp 还可以先引用含图片的消息再显式 `@机器人`。未 @ 的群图片不会下载、缓存或发送给 DSH。
- 白名单好友私聊无需 @，但必须使用字面量 `/cac <问题>`；普通私聊、`cac <问题>` 和其他命令不触发。
- 群聊中的 `@机器人 /其他命令` 会放行给已有命令插件，不会被 NOVA QA 接管。
- 满足白名单及群触发条件的消息会先于普通优先级的通用问答处理器接管，避免其他插件拒绝该群后提前停止事件传播。
- 白名单群消息在已有插件完成处理后会被标记为不再调用 AstrBot 核心默认 LLM；没有显式 `@机器人` 的引用消息因此不会产生默认模型回答。
- 每个 `bot_id + group_id` 对应一个稳定的 DSH Session，同群上下文连续，不同群完全分开。
- 每个 `bot_id + sender_id` 对应另一个 `qq-private` Session；好友私聊不会与任何群聊共享上下文。
- 同一 Session 的消息严格按 FIFO 顺序逐条处理和回复，上一轮结束后才处理下一条；不同 Session 仍可并发。
- 群聊的短回答、用法提示、限额提示和故障提示都会引用触发它们的原消息，便于多人同时提问时对应上下文。
- aiocqhttp 下超过配置阈值的正常回答会作为单条 QQ 合并转发发送，在客户端显示为可展开的聊天记录；群聊长回答不再附带引用，因为 QQ 不允许把 Reply 和合并转发混在同一条消息中。私聊长回答同样折叠，其他 QQ 适配器继续发送普通文本。
- 每个 Session 默认最多接受最近 3600 秒内的 20 个问题；达到上限会自动回复提示，其他群和好友 Session 不受影响。
- DSH 必须只注册一个名为 `NOVA知识库` 的 Workspace，新 Session 必须解析为 `nova-qa` Preset，否则插件拒绝工作。
- 每次有效提问都会通过 `session.selectModel` 使用控制面板配置的模型，默认是支持图片的 `deepseek-v4-flash-vision-exp`，因此已有 QQ Session 也会迁移。
- DSH 失败或超时时，原会话只收到简短的暂不可用提示，详细错误留在 AstrBot 日志。

## 要求

- AstrBot `>=4.24.1,<5`，已配置一个受支持的 QQ 平台适配器
- Python 3.10+
- 可访问的 DeepSeek Harness `>=0.1.1-rc.1,<0.2.0` Web RPC
- 已安装 [NOVA Knowledge QA Bundle](https://github.com/whyself/dsh-knowledge-qa-plugin) `>=0.2.0`

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
| `dsh_model_name` | `deepseek-v4-flash-vision-exp` | 每次提问前通过 `session.selectModel` 应用于对应 QQ Session；图片需要支持 `image` 输入的模型 |
| `group_whitelist` | `[]` | 允许触发的 QQ 群 ID。QQ 官方机器人填写事件提供的 `group_openid` |
| `user_whitelist` | `[]` | 允许通过私聊 `/cac <问题>` 触发的 QQ 用户 ID；QQ 官方机器人填写发送者 `openid` |
| `max_images_per_message` | `20` | 单条提问最多转换的图片数；超限时不会开始下载 |
| `max_image_bytes` | `3670016` | 单张图片字节上限，默认 3.5 MiB |
| `max_total_image_bytes` | `20971520` | 单条提问全部图片的总字节上限，默认 20 MiB |
| `image_conversion_timeout_seconds` | `30` | 下载并转换该条提问全部图片的总时限 |
| `session_hourly_limit` | `20` | 每个群或好友 Session 最近 3600 秒内允许的问题数；`0` 表示关闭限额 |
| `fold_long_responses` | `true` | aiocqhttp 下是否把过长的正常回答折叠成 QQ 合并转发 |
| `fold_response_threshold` | `800` | 正常回答严格超过此 Unicode 字符数时折叠；`0` 表示折叠所有非空正常回答 |
| `request_timeout_seconds` | `15` | 单次 DSH HTTP RPC 的网络超时 |
| `response_timeout_seconds` | `180` | 等待一轮 DSH 回答完成的总时限 |
| `poll_interval_seconds` | `0.5` | 查询 Session 历史的间隔 |

两个白名单都为空时插件不会处理任何消息。DSH 地址也可以在 AstrBot 进程环境中设置：

```bash
export DSH_BASE_URL=http://127.0.0.1:3081
```

DSH 的 `session.selectModel` 同时会把成功选择保存为后续新 Session 的默认模型；因此 `dsh_model_name` 不只是当前 QQ Session 的临时覆盖。固定 NOVA 部署应让这里与 `$DSH_HOME/settings.yaml` 的 `agent-default-model.model` 保持一致。

限额只保存在 AstrBot 插件进程内存中；插件重载或 AstrBot 重启后重新计数。只有通过限额检查、准备提交给 DSH 的有效问题才计数，空问题和未触发消息不计数。

折叠只应用于 DSH 返回的正常回答。空问题用法、小时限额和服务故障提示始终保持短文本，以免简单提示被包装成聊天记录。字符数按 Python `len()` 计算；阈值内的群回答继续引用原提问。

图片限制在 AstrBot 侧先于 DSH 调用执行，防止超量图片占用 Session 队列和请求内存。DSH 仍会按自身的附件尺寸、格式、像素和边长规则再次校验；服务器若收紧 DSH 限制，应同步收紧这里的值。

`DSH_HOME`、`DSH_QA_WORKSPACE` 和 `DEEPSEEK_API_KEY` 属于 DSH 服务，不应填入 AstrBot 插件配置。

## 发送给 NOVA QA 的消息

每次提问至少使用两个 DSH text content block。第一个是群消息来源：

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

`trigger` 为 `at_bot`。`mentions` 只包含机器人之外的被 At 用户；aiocqhttp 适配器会解析其 QQ 号和群昵称，插件不会保留 `@Novabot`。`reply_to` 仅在原消息同时含 Reply 段和显式机器人 At 时出现，表示被引用的旧消息及其作者；没有显式 `@Novabot` 的回复不会触发插件。第二个 block 是当前发送者的原始文本。若同一消息或 `Reply.chain` 中含图片，后面追加 DSH 原生 image content block，支持 PNG、JPEG、WebP 和 GIF。只有图片、没有文字时，问题使用“请描述并分析这张图片。”。`nova-qa` Persona 使用稳定的 `sender_id` 区分参与者，用 `sender_name` 称呼对方；插件不会把用户 ID 直接写进群回复。

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

第二块只包含去掉 `/cac` 后的原始问题，后面可以追加同条私聊消息的图片。群聊和私聊 Session ID 分别以 `qq-group-`、`qq-private-` 开头，避免上下文混合。

## DSH 调用流程

1. `workspace.list` 验证唯一的 `NOVA知识库`。
2. `session.create` 用稳定 Session ID 幂等创建或恢复群聊/私聊会话，并验证 `agentPreset: nova-qa`。
3. `session.selectModel` 把该 Session 切换到 `dsh_model_name`。
4. `session.history` 记录提交前的最后序号。
5. `session.prompt` 提交来源元数据、用户问题和可选 Base64 图片。
6. 轮询 `session.history`，等待新的 `turn/end: completed`，提取该边界内最后一条 `assistant/message` 文本。

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
