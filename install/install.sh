# Install common used dependencies for AIRDC (system-python / non-pixi path).
#
# PREFERRED: use pixi instead — it reproduces this exact stack with no sudo/apt:
#   bash install/install_pixi.sh              # install pixi (once)
#   pixi install -e collect                   # == this script (airdc[all,airbot] + libturbojpeg)
#   pixi shell -e collect                     # enter the data-collection env
# The `collect` pixi environment installs airdc[all,airbot] editable plus
# libjpeg-turbo (the libturbojpeg runtime), so `apt`/`gcc`/`libturbojpeg` below
# are not needed there. See pixi.toml [feature.collect].
#
# The script below remains for a plain system-python install without pixi.

set -e

if [ $# -eq 0 ]; then
    set -- sudo apt install -y
fi

# TODO: is gcc necessary?
"$@" pip python3 libturbojpeg gcc
python3 -m pip install --upgrade pip -i https://pypi.mirrors.ustc.edu.cn/simple
python3 -m pip install -e ."[all,airbot]" -i https://pypi.mirrors.ustc.edu.cn/simple
