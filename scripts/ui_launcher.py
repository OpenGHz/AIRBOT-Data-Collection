from cfgable.hydra_utils import hydra_instance_from_config_path
from airdc.common.utils.tk_keyboard import Listener


if __name__ == "__main__":
    path = "airbot_ie/configs/ui.yaml"

    listener: Listener = hydra_instance_from_config_path(path)

    listener.start()
    listener.join()
