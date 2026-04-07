set -ex

mkdir -p third_party
git clone --depth 1 https://github.com/OpenGHz/auto-atomic-operation.git -b 0.2.3 third_party/auto-atomic-operation

ln -s $PWD/third_party/auto-atomic-operation/aao_configs airbot_ie/configs/managers/auto_atom/
