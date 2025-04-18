# tests/test_integration.py

import os
import zipfile
import tempfile
import subprocess
import time
import pytest
import signal

def create_mock_ufdr_file(path, metadata=b"<xml>Integration Test</xml>", zip_entries=None):
    """
    Write some optional metadata plus a small ZIP portion to the given path.
    If zip_entries isn't provided, we add one file by default.
    """
    with open(path, "wb") as f:
        # Write metadata first
        f.write(metadata)

        if zip_entries is None:
            zip_entries = {"folder/file.txt": b"Hello from integration test"}

        with zipfile.ZipFile(f, mode='w') as zf:
            for entry_name, content in zip_entries.items():
                zf.writestr(entry_name, content)

@pytest.mark.integration
def test_integration_basic():
    """
    Launch ufdr_mount.py with a small UFDR file containing one folder/file.
    Verify 'metadata.xml' and the embedded file are visible at the mount point.
    Then unmount by sending Ctrl+C to the process.
    """
    with tempfile.TemporaryDirectory() as tempdir:
        # Create a mount directory
        mount_dir = os.path.join(tempdir, "mnt")
        os.mkdir(mount_dir)

        # Create a test .ufdr file
        ufdr_file = os.path.join(tempdir, "test.ufdr")
        create_mock_ufdr_file(
            path=ufdr_file,
            metadata=b"<xml>Integration metadata</xml>",
            zip_entries={"folder/file.txt": b"Hello from integration test!"}
        )

        # Run ufdr_mount.py in foreground as a subprocess
        proc = subprocess.Popen([
            "python3",        # or just "python" if that's your interpreter
            "ufdr_mount.py",
            ufdr_file,
            mount_dir
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Give FUSE time to mount (2 seconds is arbitrary; adjust as needed)
        time.sleep(2)

        # Check that something is mounted at mount_dir
        # On macOS or Linux, 'mount' command should list the mount point
        with open("/proc/mounts", "r") as f:
            mounts = f.read()
        assert mount_dir in mounts, f"Mount point {mount_dir} not found in /proc/mounts"

        # Check the files we expect
        # The script always creates 'metadata.xml', plus any ZIP entries
        items_in_root = os.listdir(mount_dir)
        assert "metadata.xml" in items_in_root, "Missing metadata.xml in the mount root"
        assert "folder" in items_in_root, "Missing 'folder' directory in the mount root"

        # Check file content by reading from the mount
        with open(os.path.join(mount_dir, "metadata.xml"), "r") as meta_fp:
            meta_content = meta_fp.read()
            assert "Integration metadata" in meta_content, "Wrong or missing metadata content"

        folder_contents = os.listdir(os.path.join(mount_dir, "folder"))
        assert "file.txt" in folder_contents, "Missing file.txt inside the 'folder' directory"

        # Read the file content
        with open(os.path.join(mount_dir, "folder", "file.txt"), "rb") as f:
            content = f.read()
            assert content == b"Hello from integration test!", "File content mismatch in folder/file.txt"

        # Clean up: simulate Ctrl+C to unmount
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=5)

        # Verify it's no longer mounted
        with open("/proc/mounts", "r") as f:
            mounts_after = f.read()
        assert mount_dir not in mounts_after, "Mount directory still present after killing the process"



@pytest.mark.integration
def test_integration_plain_zip():
    """
    Test scenario where there's no metadata offset; the file is a pure ZIP 
    (PK signature at offset 0). We'll still see a /metadata.xml but it's empty.
    """
    with tempfile.TemporaryDirectory() as tempdir:
        mount_dir = os.path.join(tempdir, "mnt")
        os.mkdir(mount_dir)

        # A "plain ZIP" with no metadata
        ufdr_file = os.path.join(tempdir, "plain.zip")
        create_mock_ufdr_file(path=ufdr_file, metadata=b"", zip_entries={"testfile.txt": b"Plain zip content"})

        proc = subprocess.Popen([
            "python3",
            "ufdr_mount.py",
            ufdr_file,
            mount_dir
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        time.sleep(2)

        # Check mount
        mount_output = subprocess.check_output(["mount"]).decode("utf-8")
        assert mount_dir in mount_output, f"Failed to mount plain ZIP at {mount_dir}"

        # Check root
        root_items = os.listdir(mount_dir)
        # Even though there's no metadata, the script produces an empty '/metadata.xml'
        assert "metadata.xml" in root_items, "Missing metadata.xml in a plain ZIP scenario"
        assert "testfile.txt" in root_items, "Missing testfile.txt in a plain ZIP scenario"

        # Confirm metadata.xml is empty
        meta_size = os.path.getsize(os.path.join(mount_dir, "metadata.xml"))
        assert meta_size == 0, "Expected an empty metadata.xml for a plain ZIP"

        # Confirm the file's content
        with open(os.path.join(mount_dir, "testfile.txt"), "rb") as f:
            content = f.read()
            assert content == b"Plain zip content", "Wrong content in testfile.txt"

        # Kill process
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=5)

        # Verify unmount
        mount_output_after = subprocess.check_output(["mount"]).decode("utf-8")
        assert mount_dir not in mount_output_after, "Mount directory still present after process exit"
