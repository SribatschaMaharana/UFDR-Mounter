import os #imports os for filesystem calls
import sys
import zipfile #imports zipfile for zip archive reading
import signal
import subprocess
import errno
import platform #for os detection

from fuse import FUSE, FuseOSError, Operations

mountDir = None #global var to store mount point

def handle_exit(signum, frame): #this function handles termination when CTRL+C occurs
    if mountDir and os.path.ismount(mountDir): #checks if mountDir is a valid path and is currently an active mount point
        print(f"\nUnmounting {mountDir} as program was terminated.")
        try:
            if platform.system() == "Darwin":
                subprocess.run(["diskutil", "unmount", mountDir], check=False, timeout=5)
            elif platform.system() == "Linux":
                subprocess.run(["fusermount", "-u", mountDir], check=False)
            else:
                print("OS is not supported")
        except Exception as e:
            print(f"Failed to unmount due to error {e}")
    sys.exit(0) #exit the program

signal.signal(signal.SIGINT, handle_exit) #attaches handle_exit to SIGINT 
signal.signal(signal.SIGTERM, handle_exit)

class UFDRMount(Operations):

    def __init__(self, UFDRPath):
        super().__init__() #constructor of parent class
        self.UFDRPath = os.path.abspath(UFDRPath) #absolute path of UFDR file
        if not os.path.isfile(self.UFDRPath): #throw error if not found
            raise ValueError(f"UFDR file not found")
        self.zipOffset = -1
        self.XMLdata = b""
        self.fileInfo = {}  #stores file paths
        self.dirs = set()     #stores directory paths
        self.parseUFDR() 

    def parseUFDR(self):
        with open(self.UFDRPath, "rb") as f:
            head = f.read(16384) #reads the first 16kb bc assuming that zip signature will be found in this area
            signature = b"PK\x03\x04" #zip signature that marks the beginning of a local file header
            self.zipOffset = head.find(signature) #finds the point in the provided zip file where the metadata ends + zip portion starts
            if self.zipOffset < 0: #if it returns -1 => not found
                raise RuntimeError(" ZIP signature not found in UFDR file.")
            self.XMLData = head[: self.zipOffset]
            print(f"Found ZIP at offset {self.zipOffset}")
            f.seek(self.zipOffset) #move file ptr to the part where the zipfile starts
            with zipfile.ZipFile(f, "r") as z: 
                allItems = z.infolist() #list of all items in zipfile - just metadata, not actual content
                numItems = len(allItems)
                print(f"ZIP has {numItems} entries")
                self.dirs.add("/") #add root directory
                for info in allItems: #for every item
                    if info.is_dir() or info.filename.endswith("/"): #if it's a directory, then it's added to self.dirs 
                        dirpath = "/" + info.filename.rstrip("/") 
                        self.dirs.add(dirpath)
                    else: #if it's a file, its metadata is added to self.fileInfo
                        filepath = "/" + info.filename
                        self.fileInfo[filepath] = {
                            "filename": info.filename,
                            "size": info.file_size,
                            "mtime": info.date_time,
                        }
                        self.ensureParentsExist(filepath) #make sure all parent directories for this file are also added
                self.fileInfo["/metadata.xml"] = { #create entry for metadata.xml file
                    "filename": None,  
                    "size": len(self.XMLData),
                    "mtime": (2023, 1, 1, 0, 0, 0),
                    "isMetadata": True,
                }
        numFiles = len(self.fileInfo)
        numDirs = len(self.dirs)
        print(f"Parsed {numFiles} files and {numDirs} directories in input UFDR file")

    def ensureParentsExist(self, path):
        parts = path.strip("/").split("/") #splits a path into its component folders and files
        cumulative = ""
        for part in parts[:-1]: #except the filename, takes all the folders
            cumulative += "/" + part #adds to the dir
            self.dirs.add(cumulative)

#the following are FUSE core methods
    def getattr(self, path, fh=None): #returns appropriate metadata, like stat()
        if path == "/" or path in self.dirs: #checks if requested path is root directory or is in list of directories
            return self.makeDirStat()
        elif path in self.fileInfo: #checks if it's a known file
            size = self.fileInfo[path]["size"]
            return self.makeFileStat(size)
        else: raise FuseOSError(errno.ENOENT) #raises error if the file doesn't exist in the filesystem

    def readdir(self, path, fh=None): #reading a directory, equivalent of ls
        contents = [".", ".."] #this is the array that holds the contents of the directory
        print(f"Reading path: ({path})") 
        withSlash = path
        if not withSlash.endswith("/"):
            withSlash += "/"
        for dir in self.dirs:
            if dir.startswith(withSlash) and dir != path:
                suffix = dir[len(withSlash) :] #get the remainder of the directory path – that's the part that's in this directory
                if "/" not in suffix: #if it's a child directory, not a grandchild directory – because we want to only print children
                    contents.append(suffix) #add the child directory to the array of contents
        for file in self.fileInfo:
            if file.startswith(withSlash) and file != path:
                suffix = file[len(withSlash) :] 
                if "/" not in suffix: #only get children files, not grandchildren!
                    contents.append(suffix)
        return set(contents)

    def read(self, path, size, offset, fh=None): #read a certain amount (size) of a file from the provided point (offset)
        print(f"Reading file:({path}")
        if path in self.fileInfo and self.fileInfo[path].get("isMetadata"): #if it is metadata, read from the XMLdata file
            return self.XMLData[offset:offset+size]
        if path in self.fileInfo and self.fileInfo[path]["filename"] is not None: #if it's not metadata and is an existing file
            with open(self.UFDRPath, "rb") as file:
                file.seek(self.zipOffset)
                with zipfile.ZipFile(file, "r") as zipBuffer:
                    filename = self.fileInfo[path]["filename"]
                    with zipBuffer.open(filename) as superZipBuffer:
                        if offset > 0:
                            superZipBuffer.read(offset)  
                        return superZipBuffer.read(size)
        raise FuseOSError(errno.ENOENT)        

    def open(self, path, flags): #open a file or directory! This method merely checks if the path is valid and the file/directory exist. Then, the appropriate read method is called
        print(f"Opening({path}")
        if path not in self.fileInfo and path not in self.dirs: 
            raise FuseOSError(errno.ENOENT)
        return 0

    @staticmethod
    def makeFileStat(size):
        import time
        currTime = int(time.time())
        return {
            "st_mode": 0o100444,  
            "st_size": size,
            "st_uid": os.getuid(),
            "st_gid": os.getgid(),
            "st_nlink": 1,
            "st_atime": currTime,
            "st_mtime": currTime,
            "st_ctime": currTime,
        }

    @staticmethod
    def makeDirStat():
        import time
        currTime = int(time.time())
        return {
            "st_mode": 0o040555,  
            "st_size": 0,
            "st_uid": os.getuid(),
            "st_gid": os.getgid(),
            "st_nlink": 2,
            "st_atime": currTime,
            "st_mtime": currTime,
            "st_ctime": currTime,
        }

def main():
    if len(sys.argv) < 3:
        print("Please input 2 parameters: the UFDR file to be mounted and the mount point (path)")
        sys.exit(1)
    UFDRFile = os.path.abspath(sys.argv[1])
    global mountDir
    mountDir = os.path.abspath(sys.argv[2])
    if not os.path.isfile(UFDRFile):
        print(f"Error: UFDR file {UFDRFile} not found.")
        sys.exit(1)
    if not os.path.exists(mountDir): #if there's no folder, we make a folder! 
        os.makedirs(mountDir)
    print(f"Beginning process of mounting {UFDRFile} at {mountDir}, press Ctrl+C to unmount and exit")
    fuse = FUSE(UFDRMount(UFDRFile), mountDir, foreground=True, ro=True, allow_other=True)

if __name__ == "__main__":
    main()
