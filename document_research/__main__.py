"""Loopback-only launcher; no platform environment or configuration loading."""

import argparse

from .config import init_config, validate_data_dir


def main():
    parser = argparse.ArgumentParser(description="本地通用文档解析研发服务")
    parser.add_argument(
        "--data-dir", required=True, help="源码及平台数据之外的独立绝对目录"
    )
    parser.add_argument("--port", type=int, default=4198)
    parser.add_argument(
        "--init", action="store_true", help="创建专用配置并退出，不覆盖已有文件"
    )
    args = parser.parse_args()
    try:
        directory = validate_data_dir(args.data_dir)
        if not 1024 <= args.port <= 65535:
            raise ValueError("端口必须在 1024 到 65535 之间。")
        if args.init:
            path = init_config(directory)
            print(
                f"已创建独立配置：{path}\n请在本机读取 tokens.local，并按需填写模型配置。令牌不会输出到日志。"
            )
            return
        import uvicorn

        from .service import create_app

        app = create_app(directory)
    except (ValueError, FileExistsError) as exc:
        parser.error(str(exc))
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
