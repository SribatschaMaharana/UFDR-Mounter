import os
import platform
import subprocess
import logging

log = logging.getLogger(__name__)

def get_uid():
    if platform.system() == "Windows":
        return 1000  # Dummy 
    return os.getuid()

def get_gid():
    if platform.system() == "Windows":
        return 1000  # Dummy 
    return os.getgid()

def validate_mount_point(mount_point: str):
    if not os.path.exists(mount_point):
        os.makedirs(mount_point)
    if not os.path.isdir(mount_point):
        raise ValueError(f"Mount point {mount_point} is not a directory.")

def unmount(mount_point: str):
    system = platform.system()
    log.info(f"Unmounting {mount_point} on {system}")
    try:
        if system == "Darwin":
            subprocess.run(["diskutil", "unmount", mount_point], check=True)
        elif system == "Linux":
            subprocess.run(["fusermount", "-u", mount_point], check=True)
        elif system == "Windows":
            print("Unmounting is not supported on Windows in this context.")
        else:
            raise RuntimeError(f"Unsupported platform: {system}")
    except subprocess.CalledProcessError as e:
        log.warning(f"Unmount failed: {e}")
