"""Start the Vanta Pilot web server."""

import argparse
import sys
from pathlib import Path

import uvicorn


# Ensure project root is importable.
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Vanta Pilot web server")
    parser.add_argument(
        "--prod",
        action="store_true",
        help="Run in production-style mode (no auto-reload)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind")
    args = parser.parse_args()

    reload_enabled = not args.prod
    mode = "PRODUCTION" if args.prod else "DEVELOPMENT"

    print(f"Starting Vanta Pilot Web Interface ({mode})...")
    print(f"Open http://localhost:{args.port} in your browser")
    print("=" * 50)

    uvicorn.run(
        "web.main:app",
        host=args.host,
        port=args.port,
        reload=reload_enabled,
        reload_dirs=[str(project_root / "web"), str(project_root / "services")]
        if reload_enabled
        else None,
    )
