#!/usr/bin/env python3

import os
import sys
import errno
import zipfile
from fuse import FUSE, Operations, LoggingMixIn

class ZipFS(LoggingMixIn, Operations):
    def __init__(self, zip_path):
        self.zip_path = zip_path
        self.zip_file = zipfile.ZipFile(zip_path, 'r')
        self.files = {info.filename: info for info in self.zip_file.infolist()}
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
            return dict(st_mode=(0o40555), st_nlink=2)
        if path.endswith('/'):
            if path in self.directories:
                return dict(st_mode=(0o40555), st_nlink=2)
            else:
                raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), path)

        zip_path = path.lstrip('/')
        if zip_path in self.files:
            info = self.files[zip_path]
            return dict(st_mode=(0o100444), st_nlink=1, st_size=info.file_size)
        else:
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), path)

    def readdir(self, path, fh):
        yield '.'
        yield '..'
        if path == '/':
            entries = [name.strip('/') for name in self.directories['/']]
            entries += [d.strip('/').split('/')[-1] for d in self.directories if d != '/']
            for entry in sorted(set(entries)):
                yield entry
        elif path in self.directories:
            for entry in self.directories[path]:
                yield entry
            subdirs = [d for d in self.directories if d.startswith(path) and d != path]
            for subdir in subdirs:
                subdir_name = subdir[len(path):].strip('/').split('/')[0]
                yield subdir_name
        else:
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), path)

    def open(self, path, flags):
        if flags & (os.O_WRONLY | os.O_RDWR):
            raise PermissionError(errno.EACCES, "Read-only filesystem")
        zip_path = path.lstrip('/')
        if zip_path in self.files:
            return 0
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), path)

    def read(self, path, size, offset, fh):
        zip_path = path.lstrip('/')
        if zip_path not in self.files:
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), path)
        with self.zip_file.open(zip_path) as f:
            f.seek(offset)
            return f.read(size)


def main(zip_file, mount_point):
    fuse = FUSE(ZipFS(zip_file), mount_point, nothreads=True, foreground=True, ro=True)

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <zipfile> <mountpoint>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])