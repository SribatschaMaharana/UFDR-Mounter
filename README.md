# UFDR-Mounter


A Python-based FUSE virtual filesystem that allows you to mount `.ufdr` and `.zip` archives as read-only directories. This tool lets you browse the contents of forensic archives (like Cellebrite UFDR exports) without extracting them.

Made for integration with RescueBox (UMass Amherst · Spring 2025).

# UFDR

A `.ufdr` file is a Cellebrite forensic export that combines an XML metadata blob and a ZIP archive of file contents. This project allows you to mount The ZIP portion as a virtual file structure.

(Note, at this moment the project only works with .zip files)

## Installation, Setup and Usage

### 1. Clone the Repository:
```bash
git clone https://github.com/SribatschaMaharana/UFDR-Mounter.git
cd UFDR-Mounter
```

### 2. Set Up a Virtual Environment
Create a new virtual environment using any tool you prefer. For the first example, I use Conda, but you can also use `pipenv` or Python's `venv` as alternatives.

#### Option 1: Using Conda

If you prefer using **Conda**, create and activate your environment with:

```bash
conda create --name myenv python=3.12
conda activate myenv
```

#### Option 2: Using venv
```bash
python -m venv venv
source venv/bin/activate  # For Mac/Linux
venv\Scripts\activate  # For Windows
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

macOS Setup Notes
Install macFUSE

Go to System Settings → Privacy & Security → Full Disk Access, and give macFUSE permissions, following: https://github.com/macfuse/macfuse/wiki/Getting-Started


### 4. Using the Command line interface

```bash
mkdir mnt
./mount.py <path_to.zip> mnt
```
You must create a fresh mountpoint folder every time.

Example:

```bash
mkdir /tmp/mountpoint
./mount.py test.ufdr /tmp/mountpoint
```

