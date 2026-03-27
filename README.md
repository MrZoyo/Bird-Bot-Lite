# Birt-Bot-Lite

一个独立的精简版 Bird Bot，只保留以下能力：

- 进入指定语音入口后自动建房
- 房间控制面板：解锁、上锁、满员、声音板
- 关键词自动回复组队消息
- 手动发送组队邀请 `/invt`
- 组队展示板
- 个性签名
- 相关管理命令

## 项目结构

```text
Birt-Bot-Lite/
├── config/
│   ├── messages.yaml
│   └── settings.yaml
├── data/
├── run.py
└── src/birt_bot_lite/
    ├── bot.py
    ├── config.py
    ├── repository.py
    ├── cogs/
    └── utils/
```

## 配置设计

- `config/settings.yaml`
  - 所有运行设置、频道 ID、开关、正则、颜色、日志、刷新间隔
- `config/messages.yaml`
  - 所有用户可见文案、embed 标题、footer、按钮文字、提示语

配置使用 `ruamel.yaml` 读取和回写，目的是在命令更新配置时尽量保留 YAML 注释和分组结构。

## 启动

1. 安装依赖：`pip install -r requirements.txt`
2. 修改 `config/settings.yaml` 中的 `discord.token`、`discord.guild_id`、各频道 ID
3. 运行：`python run.py`

## 主要命令

- `/vc_add`
- `/vc_remove`
- `/vc_list`
- `/check_temp_channel_records`
- `/invt`
- `/invt_addignorelist`
- `/invt_removeignorelist`
- `/invt_checkignorelist`
- `/teamup_init`
- `/teamup_type_add`
- `/teamup_type_delete`
- `/teamup_type_list`
- `/signature_set`
- `/signature_clear`
- `/signature_view`
- `/signature_toggle`
