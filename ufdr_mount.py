#!/usr/bin/env python3

import os
import sys
import zipfile
import logging
import signal
import subprocess
import errno

from fuse import FUSE, FuseOSError, Operations, LoggingMixIn

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Global so our signal handler can unmount if needed
MOUNT_DIR = None


def handle_exit(signum, frame):
    """Gracefully unmount on Ctrl+C or kill."""
    if MOUNT_DIR and os.path.ismount(MOUNT_DIR):
        print(f"\nUnmounting {MOUNT_DIR}...")
        try:
            # On macOS, attempt diskutil first
            subprocess.run(["diskutil", "unmount", MOUNT_DIR], check=False, timeout=5)
        except (FileNotFoundError, subprocess.SubprocessError):
            # Fallback: use umount
            subprocess.run(["umount", MOUNT_DIR], check=False)
    sys.exit(0)


# Attach our signal handler for Ctrl+C, kill, etc.
signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)


class UFDRMount(LoggingMixIn, Operations):
    """
    FUSE filesystem that:
     - Reads a .ufdr file
     - Finds an embedded ZIP at the 'PK\x03\x04' signature
     - Exposes everything before that as 'metadata.xml'
     - Exposes the ZIP contents as subdirectories/files
    """

    def __init__(self, ufdr_path):
        super().__init__()
        self.ufdr_path = os.path.abspath(ufdr_path)
        if not os.path.isfile(self.ufdr_path):
            raise ValueError(f"UFDR file not found: {self.ufdr_path}")

        self.zip_offset = -1
        self.xml_data = b""
        self.files_info = {}  # path -> dict of metadata
        self.dirs = set()     # set of directory paths

        # Ensure we parse the .ufdr structure
        self._parse_ufdr()

    def _parse_ufdr(self):
        """
        Scan the UFDR file for an embedded ZIP. The portion before the ZIP
        is treated as 'metadata.xml'. The ZIP portion is read (but not extracted)
        to populate the internal file tree.
        """
        log.info("Scanning UFDR file for embedded ZIP...")
        with open(self.ufdr_path, "rb") as f:
            # Read a chunk to find the ZIP signature
            head = f.read(16384)  # read 16KB
            signature = b"PK\x03\x04"
            self.zip_offset = head.find(signature)
            if self.zip_offset < 0:
                raise RuntimeError("No ZIP signature found in UFDR file.")

            # The bytes before the ZIP are our 'metadata.xml'
            self.xml_data = head[: self.zip_offset]
            # Potentially, if the XML is bigger than 16KB, you might read further,
            # but usually UFDR XML is small enough to fit in that chunk.

            log.info(f"Found ZIP at offset {self.zip_offset}. Metadata size: {len(self.xml_data)}")

            # Move file pointer to start of ZIP
            f.seek(self.zip_offset)

            # Now read the ZIP structure
            with zipfile.ZipFile(f, "r") as z:
                all_items = z.infolist()
                log.info(f"ZIP has {len(all_items)} entries")

                # We'll track directories separately. We'll create the root dir "/".
                self.dirs.add("/")
                for info in all_items:
                    # If it's a directory, record it in self.dirs.
                    if info.is_dir() or info.filename.endswith("/"):
                        dirpath = "/" + info.filename.rstrip("/")
                        self.dirs.add(dirpath)
                    else:
                        # It's a file
                        filepath = "/" + info.filename
                        self.files_info[filepath] = {
                            "filename": info.filename,
                            "size": info.file_size,
                            "mtime": info.date_time,
                        }
                        # Mark any parent directories
                        self._ensure_parents(filepath)

                # Also add our 'metadata.xml' as a pseudo-file
                self.files_info["/metadata.xml"] = {
                    "filename": None,  # indicates it's not in the ZIP
                    "size": len(self.xml_data),
                    "mtime": (2023, 1, 1, 0, 0, 0),
                    "is_metadata": True,
                }

        log.info(f"Parsed {len(self.files_info)} files and {len(self.dirs)} directories in UFDR")

    def _ensure_parents(self, path):
        """Given '/folder/subfolder/file.txt', register '/folder' and '/folder/subfolder' as dirs."""
        parts = path.strip("/").split("/")
        cumulative = ""
        for part in parts[:-1]:  # skip the final, which is the file
            cumulative += "/" + part
            self.dirs.add(cumulative)

    # ============= FUSE Methods =============

    def getattr(self, path, fh=None):
        """
        Return file/dir metadata. If path is in our dirs, treat it as a directory;
        if path is in files_info, treat it as a file; else fallback check on disk
        (though normally the UFDR is a single file).
        """
        log.debug(f"getattr({path})")

        if path == "/":
            # Root: treat it like a directory
            return self._make_dir_stat()

        if path in self.dirs:
            return self._make_dir_stat()

        if path in self.files_info:
            # It's a "virtual" file from the ZIP or the metadata chunk
            size = self.files_info[path]["size"]
            return self._make_file_stat(size)

        # If there's some fallback? Usually not needed, but you can implement
        # a real file check if you want. We'll just say ENOENT.
        raise FuseOSError(errno.ENOENT)

    def readdir(self, path, fh):
        """
        List children for a directory. We'll find immediate subpaths
        that share our directory prefix (plus one level).
        """
        log.debug(f"readdir({path})")
        # '.' and '..' are standard
        entries = [".", ".."]

        # At root, anything that is top-level (like "/something")
        # If at "/dir", then we want the next segment after "/dir/"
        prefix = path
        if not prefix.endswith("/"):
            prefix += "/"

        # For directories, gather direct children
        # 1) Child directories
        for d in self.dirs:
            if d.startswith(prefix) and d != path:
                # Example: path="/foo", prefix="/foo/", d="/foo/bar"
                # We'll extract "bar"
                suffix = d[len(prefix) :]
                if "/" not in suffix:  # direct child, not deeper subdir
                    entries.append(suffix)

        # 2) Child files
        for fpath in self.files_info:
            if fpath.startswith(prefix) and fpath != path:
                suffix = fpath[len(prefix) :]
                if "/" not in suffix:
                    entries.append(suffix)

        return sorted(set(entries))

    def read(self, path, size, offset, fh):
        """
        Return the requested slice of data from either:
         - The 'metadata.xml' chunk
         - The ZIP content (by seeking to zip_offset and reading from the embedded file)
        """
        log.debug(f"read({path}, size={size}, offset={offset})")

        # Is it the pseudo metadata.xml file?
        if path in self.files_info and self.files_info[path].get("is_metadata"):
            return self.xml_data[offset : offset + size]

        # If it's a file from the ZIP
        if path in self.files_info and self.files_info[path]["filename"] is not None:
            return self._read_from_zip(path, size, offset)

        # Not found
        raise FuseOSError(errno.ENOENT)

    def _read_from_zip(self, path, size, offset):
        """Helper to open the UFDR, seek to the ZIP offset, open the file in the ZIP, and read data."""
        with open(self.ufdr_path, "rb") as f:
            f.seek(self.zip_offset)
            with zipfile.ZipFile(f, "r") as z:
                filename = self.files_info[path]["filename"]
                with z.open(filename) as zf:
                    if offset > 0:
                        zf.read(offset)  # skip to 'offset'
                    return zf.read(size)

    def open(self, path, flags):
        """We don't do real file handles, so return a dummy integer."""
        log.debug(f"open({path}, flags={flags})")
        if path not in self.files_info and path not in self.dirs:
            raise FuseOSError(errno.ENOENT)
        # 0 is a dummy handle
        return 0

    ### HELPERS

    @staticmethod
    def _make_file_stat(size):
        """
        Returns a dict of typical st_ fields for a read-only file.
        Fake them as needed, or read from your system if you prefer.
        """
        import time
        # We'll just set times to "now" for demonstration
        now = int(time.time())
        return {
            "st_mode": 0o100444,  # Regular file, read-only
            "st_size": size,
            "st_uid": os.getuid(),
            "st_gid": os.getgid(),
            "st_nlink": 1,
            "st_atime": now,
            "st_mtime": now,
            "st_ctime": now,
        }

    @staticmethod
    def _make_dir_stat():
        """
        Returns a dict of typical st_ fields for a directory.
        """
        import time
        now = int(time.time())
        return {
            "st_mode": 0o040555,  # Directory, read/execute
            "st_size": 0,
            "st_uid": os.getuid(),
            "st_gid": os.getgid(),
            "st_nlink": 2,
            "st_atime": now,
            "st_mtime": now,
            "st_ctime": now,
        }


def main():
    if len(sys.argv) < 3:
        print("Usage: ufdr_mount.py <ufdr_file> <mount_dir>")
        sys.exit(1)

    ufdr_file = os.path.abspath(sys.argv[1])
    global MOUNT_DIR
    MOUNT_DIR = os.path.abspath(sys.argv[2])

    if not os.path.exists(MOUNT_DIR):
        os.makedirs(MOUNT_DIR)

    if not os.path.isfile(ufdr_file):
        print(f"Error: UFDR file {ufdr_file} not found.")
        sys.exit(1)

    print(f"Mounting {ufdr_file} at {MOUNT_DIR}")
    print("Press Ctrl+C to unmount and exit.")

    # FUSE in foreground
    fuse = FUSE(UFDRMount(ufdr_file), MOUNT_DIR, foreground=True, ro=True, allow_other=False)


if __name__ == "__main__":
    main()
