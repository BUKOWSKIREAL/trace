"""
配置文件读写
=================
.trace/config.json 的简单封装。

"""

import json
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "version": "0.1.0-week12",
    "tracking_enabled": True,
    "forced_agent": "auto",  # 'auto' 或具体 agent 名
    "high_precision_mode": False,  # 是否启用 sudo + fs_usage
    "ignore_patterns": [  # 用户自定义忽略规则（除默认外）
        # ".gitignore", "build/"
    ],
}


def load_config(config_path: Path) -> dict[str, Any]:
    """读配置，文件不存在则返回默认值。"""
    if not config_path.exists():
        return dict(DEFAULT_CONFIG)
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 合并默认值（让新字段在升级时也有合理默认）
        merged = dict(DEFAULT_CONFIG)
        merged.update(data)
        return merged
    except (json.JSONDecodeError, OSError):
        # 损坏的配置文件回退到默认
        return dict(DEFAULT_CONFIG)


def save_config(config_path: Path, config: dict[str, Any]) -> None:
    """写配置（带格式化，方便人工查看）。"""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
