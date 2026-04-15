#!/usr/bin/env bash
set -euo pipefail

# tmux 会话名称
SESSION_NAME="dynamic_cluster"

# 每个窗口要执行的命令；增删这里的命令即可调整窗口数量
COMMANDS=(
    "echo 1"
    "echo 2"
    "echo 3"
)

# 窗口数量由命令列表自动决定
WINDOW_COUNT="${#COMMANDS[@]}"

if (( WINDOW_COUNT == 0 )); then
    echo "COMMANDS 不能为空，请至少配置一个要执行的命令。"
    exit 1
fi

if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "tmux 会话 '$SESSION_NAME' 已存在，直接附加到该会话。"
    tmux attach-session -t "$SESSION_NAME"
    exit 0
fi

# 创建会话和第一个窗口
tmux new-session -d -s "$SESSION_NAME" -n "Node-1"
tmux send-keys -t "$SESSION_NAME:Node-1" "${COMMANDS[0]}" Enter

# 从第二个命令开始，为每个命令创建一个窗口
for ((i = 1; i < WINDOW_COUNT; i++)); do
    node_index=$((i + 1))
    window_name="Node-${node_index}"

    tmux new-window -t "$SESSION_NAME" -n "$window_name"
    tmux send-keys -t "$SESSION_NAME:$window_name" "${COMMANDS[$i]}" Enter
done

# 最后附加到会话查看
tmux attach-session -t "$SESSION_NAME"
