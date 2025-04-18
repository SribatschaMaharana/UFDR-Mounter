# tests/test_unit.py

import os
import zipfile
import pytest
import tempfile

from ufdr_mount import UFDRMount
from fuse import FuseOSError

def write_mock_ufdr(fileobj, metadata=b"<xml>Test metadata</xml>", zip_entries=None):
    """
    Write some metadata, then append a ZIP archive. Return the offset where the ZIP begins. If zip_entries isn't provided, we'll add a default file in 'folder/file.txt'.
    """
    fileobj.write(metadata)
    offset = fileobj.tell()

    with zipfile.ZipFile(fileobj, mode='w') as zf:
        if zip_entries is None:
            zip_entries = {"folder/file.txt": b"Hello from inside ZIP"}
        for path_in_zip, content in zip_entries.items():
            zf.writestr(path_in_zip, content)

    return offset


@pytest.fixture
def no_zip_signature_file():
    """
    Creates a file with no 'PK\x03\x04' sequence. Expect a RuntimeError when we try to mount it as UFDR.
    """
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(b"This file has no zip signature.\n")
        path = tmp.name
    yield path
    os.remove(path)


@pytest.fixture
def basic_ufdr_file():
    """
    A small UFDR with a single file in a 'folder' inside the ZIP portion.
    """
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        write_mock_ufdr(tmp)
        path = tmp.name
    yield path
    os.remove(path)


@pytest.fixture
def plain_zip_file():
    """
    Creates a file that starts immediately with 'PK\x03\x04', with no metadata block. 
    """
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        write_mock_ufdr(
            tmp, 
            metadata=b"", 
            zip_entries={"file.txt": b"Hello from a plain ZIP"}
        )
        path = tmp.name
    yield path
    os.remove(path)


@pytest.fixture
def nested_folders_file():
    """
    nested folders in ZIP.
    """
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        entries = {
            "dir1/dir2/dir3/deepfile.txt": b"Deep content",
            "dir1/anotherfile.log": b"Some log data"
        }
        write_mock_ufdr(
            tmp, 
            metadata=b"<xml>Nested test</xml>", 
            zip_entries=entries
        )
        path = tmp.name
    yield path
    os.remove(path)


def test_no_zip_signature(no_zip_signature_file):
    # Expect a RuntimeError with no ZIP signature.
    with pytest.raises(RuntimeError, match="No ZIP signature found"):
        UFDRMount(no_zip_signature_file)


def test_basic_ufdr(basic_ufdr_file):
    """
    Basic test: there's metadata.xml, a folder, and one file in that folder.
    """
    mount = UFDRMount(basic_ufdr_file)

    # Check that the ZIP starts after the metadata
    assert mount.zip_offset > 0, "Expected 'PK' signature after some metadata"

    # Ensure '/metadata.xml' is recognized
    assert "/metadata.xml" in mount.files_info
    meta_size = mount.files_info["/metadata.xml"]["size"]
    assert meta_size > 0, "metadata.xml should hold actual data"

    # Check the file we wrote in 'folder/file.txt'
    assert "/folder/file.txt" in mount.files_info
    file_info = mount.files_info["/folder/file.txt"]
    assert file_info["size"] == len(b"Hello from inside ZIP")

    # Make sure the directories were created
    assert "/" in mount.dirs
    assert "/folder" in mount.dirs


def test_plain_zip_as_ufdr(plain_zip_file):
    """
    If the file is ZIP at offset 0, metadata.xml should be empty, but ZIP contents should work.
    """
    mount = UFDRMount(plain_zip_file)
    assert mount.zip_offset == 0, "Plain ZIP offset should be 0"

    # '/metadata.xml' should exist but be empty
    meta_size = mount.files_info["/metadata.xml"]["size"]
    assert meta_size == 0

    # Verify the single file in the ZIP
    assert "/file.txt" in mount.files_info
    assert "/" in mount.dirs
    assert "/file.txt" not in mount.dirs  # It's a file, not a folder


def test_nested_folders(nested_folders_file):
    """
    Check a file with nested directories like dir1/dir2/dir3. Confirm they appear in mount.dirs and the files are recognized with same size.
    """
    mount = UFDRMount(nested_folders_file)

    assert "/metadata.xml" in mount.files_info

    # two files to assert
    assert "/dir1/dir2/dir3/deepfile.txt" in mount.files_info
    assert "/dir1/anotherfile.log" in mount.files_info

    # Check parent directories exist
    expected_dirs = ["/", "/dir1", "/dir1/dir2", "/dir1/dir2/dir3"]
    for d in expected_dirs:
        assert d in mount.dirs, f"Missing {d} in mount.dirs"

    # Validate file sizes
    deep_size = mount.files_info["/dir1/dir2/dir3/deepfile.txt"]["size"]
    log_size = mount.files_info["/dir1/anotherfile.log"]["size"]
    assert deep_size == len(b"Deep content")
    assert log_size == len(b"Some log data")
