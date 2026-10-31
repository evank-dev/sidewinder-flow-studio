"""PyInstaller entry point for the desktop backend sidecar (see app/desktop.py)."""
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from app.desktop import main
    raise SystemExit(main())
