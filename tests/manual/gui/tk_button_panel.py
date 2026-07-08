"""Small runnable example for the Tk button panel.

Run (from repo root):
    python -m airdc.tests.utils.example_tk_button_panel

This is an interactive example: click buttons in the window.
- Clicking "hello" triggers a per-button callback.
- Clicking any button triggers on_press.
- Clicking "quit" closes the window.
- Clicking "script" runs a demo script and shows its output.
- Clicking "cmd" runs a command and shows its output.
"""

from pathlib import Path

from airdc.common.utils.tk_keyboard import ButtonUILayout, Listener, TkButtonPanelConfig


def main() -> None:
    listener_holder: dict[str, Listener] = {}

    def on_press(name: str) -> None:
        print(f"on_press: {name}")
        if name == "quit":
            listener_holder["listener"].stop()

    def on_close() -> None:
        print("Window closed.")

    script_path = Path(__file__).with_name("demo_long_running_script.py")
    # script_path = "airdc.utils"

    config = TkButtonPanelConfig(
        layout=ButtonUILayout(
            title=None,
            button_width=12,
            button_height=2,
            n_cols=2,
        ),
        buttons=["hello", "world", "info", "script", "cmd", "quit"],
        button_callbacks={
            "hello": lambda: print("hello clicked"),
            "world": lambda: print("world clicked"),
            "info": "This is a popup message.\n\nString callbacks will show this window.",
            "script": f"script: {script_path}",
            "cmd": "cmd: python3 -V",
        },
        on_press=on_press,
        on_close=on_close,
    )

    listener = Listener(config=config)
    listener_holder["listener"] = listener

    listener.start()
    listener.join()


if __name__ == "__main__":
    main()
