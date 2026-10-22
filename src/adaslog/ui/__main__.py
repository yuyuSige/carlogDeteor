"""Launch the Streamlit workbench: python -m adaslog.ui"""
from __future__ import annotations

import sys


def main() -> int:
    try:
        from streamlit.web import cli as stcli
    except ImportError:
        print(
            "未安装 Streamlit。请执行：pip install 'adaslog[ui]'\n"
            "然后：python -m adaslog.ui  或  streamlit run src/adaslog/ui/app.py --server.address 127.0.0.1",
            file=sys.stderr,
        )
        return 1
    from adaslog.ui.settings import DEFAULT_HOST, DEFAULT_PORT

    app = str(__file__).replace("__main__.py", "app.py")
    sys.argv = [
        "streamlit",
        "run",
        app,
        f"--server.address={DEFAULT_HOST}",
        f"--server.port={str(DEFAULT_PORT)}",
        "--browser.gatherUsageStats=false",
    ]
    stcli.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
