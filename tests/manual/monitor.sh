#!/bin/bash

# 1. 定义要监控的目录
WATCH_DIR=$1

echo "开始监控目录: $WATCH_DIR"

# 2. 启动 inotifywait
# -m: 持续监控
# -r: 递归子目录
# -e create: 只监控创建事件
# --format '%w%f': 输出文件的绝对路径
inotifywait -m -r -e create --format '%w%f' "$WATCH_DIR" | while read NEW_FILE
do
    # 3. 在循环中处理事件
    echo "检测到新文件: $NEW_FILE"

    # 这里可以加入你的业务逻辑
    # 例如：如果是图片，就进行压缩；如果是日志，就进行归档
    if [[ "$NEW_FILE" == *.txt ]]; then
        echo "发现文本文件，正在处理..."
        # mv "$NEW_FILE" /backup/
    fi
done
