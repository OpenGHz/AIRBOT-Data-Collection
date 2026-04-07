set -ex

pip install -e ."[assis]"
mkdir -p third_party
git clone --depth 1 https://github.com/OpenGHz/auto-atomic-operation.git -b 0.2.3 third_party/

ln -s $PWD/third_party/auto-atomic-operation/aao_configs airbot_ie/configs/managers/auto_atom/

# TASK_NAME=pick_and_place airdc --name aao_config dataset.directory=aao_data/$TASK_NAME managers/auto_atom/task=$TASK_NAME
