# Backward-compatible entry — web server lives in battaglia_navale.py
from battaglia_navale import run_server_web

if __name__ == "__main__":
    import sys

    host = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"
    porta = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
    run_server_web(host, porta)
