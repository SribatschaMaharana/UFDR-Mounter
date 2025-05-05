import typer
import signal
import os
import logging
from fuse import FUSE
from ufdr_mounter.ufdr_fs import UFDRMount
from ufdr_mounter.core import validate_mount_point, unmount

log = logging.getLogger(__name__)

app = typer.Typer()
MOUNT_DIR = None

def handle_exit(signum, frame):
    global MOUNT_DIR
    if MOUNT_DIR:
        unmount(MOUNT_DIR)
    raise typer.Exit()

@app.command()
def mount(
    ufdr_file: str = typer.Argument(..., help="Path to the .ufdr file"),
    mount_point: str = typer.Argument(..., help="Directory to mount the UFDR into"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug logging"),
):
    """Mount a UFDR file at the specified mount point."""
    global MOUNT_DIR
    ufdr_file = os.path.abspath(ufdr_file)
    MOUNT_DIR = os.path.abspath(mount_point)

    # Set logging level
    log_level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(level=log_level)

    validate_mount_point(MOUNT_DIR)

    log.info(f"Mounting {ufdr_file} at {MOUNT_DIR}")
    print("Press Ctrl+C to unmount and exit.")

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    FUSE(UFDRMount(ufdr_file), MOUNT_DIR, foreground=True, ro=True, allow_other=False)

if __name__ == "__main__":
    app()
