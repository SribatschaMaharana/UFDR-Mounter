#!/usr/bin/env python3

import os
import stat
import sys
import errno
import zipfile
from fuse import FUSE, Operations, LoggingMixIn

class ZipFS(LoggingMixIn, Operations):
    def __init__(self, zip_path):
        self.zip_path = zip_path
        self.zip_file = zipfile.ZipFile(zip_path, 'r')
        self.files = {}
        for info in self.zip_file.infolist():
            self.files[info.filename] = info
        self.directories = self._build_directory_structure()

    def _build_directory_structure(self):
        dirs = {'/': []}
        for file in self.files:
            path_parts = file.strip('/').split('/')
            for i in range(1, len(path_parts)):
                dir_path = '/' + '/'.join(path_parts[:i]) + '/'
                if dir_path not in dirs:
                    dirs[dir_path] = []
            if file.endswith('/'):
                dirs['/' + '/'.join(path_parts) + '/'] = []
            else:
                parent_dir = '/' + '/'.join(path_parts[:-1]) + '/'
                if parent_dir not in dirs:
                    dirs[parent_dir] = []
                dirs[parent_dir].append(path_parts[-1])
        return dirs

    def getattr(self, path, fh=None):
        if path == '/':
            return dict(st_mode=(stat.S_IFDIR | 0o555), st_nlink=2)

        zip_path = path.lstrip('/')

        # Directory check
        if zip_path in self.directories:
            return dict(st_mode=(stat.S_IFDIR | 0o555), st_nlink=2)

        # File check
        if zip_path in self.files:
            info = self.files[zip_path]
            return dict(st_mode=(stat.S_IFREG | 0o444), st_nlink=1, st_size=info.file_size)

        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), path)


    def readdir(self, path, fh):
        yield '.'
        yield '..'
        normalized_path = path.lstrip('/')
        if normalized_path and not normalized_path.endswith('/'):
            normalized_path += '/'

        seen = set()

        for filename in self.files:
            if not filename.startswith(normalized_path):
                continue

            # Strip the current path part
            sub_path = filename[len(normalized_path):]
            # Grab the next part (file or dir) only
            next_entry = sub_path.split('/', 1)[0]

            if next_entry not in seen and next_entry:
                seen.add(next_entry)
                yield next_entry

    def open(self, path, flags):
        if flags & (os.O_WRONLY | os.O_RDWR):
            raise PermissionError(errno.EACCES, "Read-only filesystem")
        zip_path = path.lstrip('/')
        if zip_path in self.files:
            return 0
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), 
path)

    def read(self, path, size, offset, fh):
        zip_path = path.lstrip('/')
        if zip_path not in self.files:
            raise FileNotFoundError(errno.ENOENT, 
os.strerror(errno.ENOENT), path)
        with self.zip_file.open(zip_path) as f:
            f.seek(offset)
            return f.read(size)


def main(zip_file, mount_point):
    fuse = FUSE(ZipFS(zip_file), mount_point, 
foreground=True, ro=True)

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <zipfile> <mountpoint>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])