"""专用容器入口；只读取专用卷，不加载平台环境或配置。"""

import argparse
import os
from pathlib import Path

from document_research.config import init_config

DATA_DIR = Path("/var/lib/document-research")


def main():
    """显式初始化或启动一个容器私网服务进程。"""
    parser = argparse.ArgumentParser(description="独立文档研发容器")
    parser.add_argument(
        "operation", choices=("init", "serve"), default="serve", nargs="?"
    )
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.operation == "init":
            init_config(DATA_DIR)
            print("已创建专用配置；令牌仅保存在专用卷的 config.json 中。")
            return

        import uvicorn

        from document_research.service import create_app

        app = create_app(DATA_DIR)
    except (ValueError, FileExistsError) as exc:
        parser.error(str(exc))

    # 宿主 CLI 仍固定 loopback；此监听只由专用容器网络提供给 Web 代理。
    uvicorn.run(app, host="0.0.0.0", port=4198, workers=1, access_log=False)


if __name__ == "__main__":
    main()
