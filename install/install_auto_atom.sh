set -ex

AAO_VERSION="0.3.0"
AAO_DIR="third_party/auto-atomic-operation"

mkdir -p third_party

if [ -d "$AAO_DIR" ]; then
    cd "$AAO_DIR"
    # 检查当前版本是否已经是目标版本
    CURRENT_TAG=$(git describe --tags --exact-match 2>/dev/null || echo "unknown")
    if [ "$CURRENT_TAG" != "$AAO_VERSION" ]; then
        echo "当前版本 $CURRENT_TAG，正在切换到 $AAO_VERSION ..."
        git fetch --tags --quiet
        git checkout "tags/$AAO_VERSION" --quiet
        echo "已切换到 $AAO_VERSION"
    else
        echo "已是目标版本 $AAO_VERSION，无需切换"
    fi
    cd - >/dev/null
else
    git clone --depth 1 https://github.com/OpenGHz/auto-atomic-operation.git -b "$AAO_VERSION" "$AAO_DIR"
fi

LINK_TARGET="airbot_ie/configs/managers/auto_atom/aao_configs"
if [ ! -e "$LINK_TARGET" ]; then
    ln -s "$PWD/$AAO_DIR/aao_configs" "$LINK_TARGET"
fi
