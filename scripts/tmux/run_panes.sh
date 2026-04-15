#!/usr/bin/env bash
set -euo pipefail

# tmux 会话名称
SESSION_NAME="dynamic_cluster"
WINDOW_NAME="Node-1"

# 一个窗口中每个 pane 要执行的命令；增删这里的命令即可调整 pane 数量
COMMANDS=(
    "echo 1"
    "echo 2"
    "echo 3"
)

# 从第二个命令开始，每次新建 pane 的拆分方向：
# h = 左右拆分，v = 上下拆分
# 这里示例为：
# 1. 先把第一个 pane 左右拆成两个
# 2. 再把当前 pane 上下拆成两个
SPLIT_DIRECTIONS=(
    "h"
    "v"
)

PANE_COUNT="${#COMMANDS[@]}"

if (( PANE_COUNT == 0 )); then
    echo "COMMANDS 不能为空，请至少配置一个要执行的命令。"
    exit 1
fi

if (( ${#SPLIT_DIRECTIONS[@]} != PANE_COUNT - 1 )); then
    echo "SPLIT_DIRECTIONS 的数量必须等于 COMMANDS 数量减 1。"
    exit 1
fi

if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "tmux 会话 '$SESSION_NAME' 已存在，直接附加到该会话。"
    tmux attach-session -t "$SESSION_NAME"
    exit 0
fi

# 创建会话和第一个 pane
tmux new-session -d -s "$SESSION_NAME" -n "$WINDOW_NAME"
current_pane="$(tmux display-message -p -t "$SESSION_NAME:$WINDOW_NAME" '#{pane_id}')"
tmux send-keys -t "$current_pane" "${COMMANDS[0]}" Enter

for ((i = 1; i < PANE_COUNT; i++)); do
    split_direction="${SPLIT_DIRECTIONS[$((i - 1))]}"

    case "$split_direction" in
        h)
            new_pane="$(tmux split-window -h -P -F '#{pane_id}' -t "$current_pane")"
            ;;
        v)
            new_pane="$(tmux split-window -v -P -F '#{pane_id}' -t "$current_pane")"
            ;;
        *)
            echo "无效的拆分方向: $split_direction。仅支持 h 或 v。"
            exit 1
            ;;
    esac

    tmux send-keys -t "$new_pane" "${COMMANDS[$i]}" Enter
    current_pane="$new_pane"
done

# 最后附加到会话查看
tmux attach-session -t "$SESSION_NAME"
