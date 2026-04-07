#!/bin/bash

# 定义颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 1. 同步远程 Tags (静默模式，避免刷屏)
echo -e "${CYAN}正在同步远程 Tags...${NC}"
git fetch --tags --quiet

# 2. 获取最新的 Tag (按版本号排序，取最新的)
LATEST_TAG=$(git tag --sort=-v:refname | head -1)

if [ -z "$LATEST_TAG" ]; then
    echo -e "${RED}错误: 仓库中没有任何 Tags${NC}"
    exit 1
fi

# 3. 确定目标 Tag
TARGET_TAG=""

if [ -z "$1" ]; then
    # 情况 A: 未提供参数，默认使用最新的 Tag
    TARGET_TAG=$LATEST_TAG
    echo -e "${YELLOW}未指定 Tag，将自动检测并切换到最新版本: ${GREEN}$TARGET_TAG${NC}"
else
    # 情况 B: 提供了参数，使用指定的 Tag
    TARGET_TAG=$1
    echo -e "${YELLOW}正在查找指定 Tag: ${GREEN}$TARGET_TAG${NC}"
fi

# 4. 验证 Tag 是否存在
if ! git rev-parse --verify "tags/$TARGET_TAG" >/dev/null 2>&1; then
    echo -e "${RED}错误: 找不到 Tag '$TARGET_TAG'${NC}"
    echo "提示: 最新的可用 Tag 是 '$LATEST_TAG'"
    exit 1
fi

# 5. 检查当前状态 (可选优化)
CURRENT_CHECKOUT=$(git describe --tags --exact-match 2>/dev/null)
if [ "$CURRENT_CHECKOUT" == "$TARGET_TAG" ]; then
    echo -e "${GREEN}当前已经在 Tag '$TARGET_TAG' 上，无需切换。${NC}"
    exit 0
fi

# 6. 暂存本地修改并执行切换
echo -e "${CYAN}正在切换到: $TARGET_TAG${NC}"

STASHED=false
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo -e "${YELLOW}检测到本地修改，自动暂存 (git stash)...${NC}"
    git stash --quiet
    STASHED=true
fi

if ! git checkout "tags/$TARGET_TAG" --quiet; then
    echo -e "${RED}错误: 切换到 '$TARGET_TAG' 失败${NC}"
    if [ "$STASHED" = true ]; then
        echo -e "${YELLOW}正在恢复暂存的修改...${NC}"
        git stash pop --quiet
    fi
    exit 1
fi

# 7. 恢复暂存的修改
if [ "$STASHED" = true ]; then
    echo -e "${YELLOW}正在恢复暂存的本地修改...${NC}"
    if ! git stash pop --quiet; then
        echo -e "${RED}警告: 恢复暂存修改时有冲突，请手动处理 (git stash pop)${NC}"
    fi
fi

# 8. 完成提示
echo ""
echo -e "${GREEN}成功切换到 $TARGET_TAG${NC}"
echo -e "${YELLOW}提示: 你现在处于 'Detached HEAD' 状态。${NC}"
echo "如需修改代码，请运行: git checkout -b <新分支名>"
