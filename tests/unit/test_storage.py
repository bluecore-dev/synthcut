import base64
import hashlib
import uuid

import pytest
from synthcut_storage import (
    MAX_PARTS,
    MIB,
    Area,
    ImmutableOriginalError,
    InvalidKeyError,
    Storage,
    StorageConfig,
    assert_writable,
    derived_key,
    expected_part_size,
    is_original,
    md5_b64_to_hex,
    normalize_extension,
    original_key,
    parse_key,
    plan_parts,
)

P = uuid.UUID("0199a5d0-0000-7000-8000-000000000001")
A = uuid.UUID("0199a5d0-0000-7000-8000-000000000002")


def test_original_key_layout():
    assert original_key(P, A, "mov") == f"projects/{P}/originals/{A}/source.mov"
    parsed = parse_key(original_key(P, A, "mov"))
    assert parsed.is_original and parsed.project_id == P and parsed.owner_id == A


@pytest.mark.parametrize(
    ("filename", "ext"),
    [
        ("clip.MOV", "mov"),
        ("a.b.mp4", "mp4"),
        ("noext", "bin"),
        ("../../etc/passwd", "bin"),
        ("x.m2ts", "m2ts"),
        ("evil.mp4/../../x", "bin"),
        ("weird.ab cd", "bin"),
        ("long.extensionxx", "bin"),
    ],
)
def test_extension_never_carries_a_path(filename, ext):
    assert normalize_extension(filename) == ext


@pytest.mark.parametrize("name", ["../x", "a/b", "", ".hidden", "A.JPG", "x" * 200, "a..b"])
def test_derived_names_are_strict(name):
    with pytest.raises(InvalidKeyError):
        derived_key(P, Area.PROXIES, A, name)


def test_derived_key_cannot_target_originals():
    with pytest.raises(ImmutableOriginalError):
        derived_key(P, Area.ORIGINALS, A, "source.mov")


def test_non_uuid_components_rejected():
    with pytest.raises(InvalidKeyError):
        original_key("../../", A, "mov")


def test_writes_to_originals_are_refused():
    with pytest.raises(ImmutableOriginalError):
        assert_writable(original_key(P, A, "mov"))
    assert assert_writable(derived_key(P, Area.PROXIES, A, "proxy_720p.mp4")).area is Area.PROXIES


def test_unparseable_keys_count_as_protected():
    assert is_original("something/else")
    assert is_original(f"projects/{P}/originals/{A}/source.mov")
    assert not is_original(derived_key(P, Area.THUMBNAILS, A, "poster.jpg"))


def test_storage_client_refuses_original_writes(tmp_path):
    storage = Storage(StorageConfig("http://127.0.0.1:1", "http://127.0.0.1:1", "us-east-1", "b", "k", "s"))
    with pytest.raises(ImmutableOriginalError):
        storage.put_derived_bytes(original_key(P, A, "mov"), b"x", "video/quicktime")
    with pytest.raises(ImmutableOriginalError):
        storage.delete_derived(original_key(P, A, "mov"))


def test_presigned_part_signs_content_md5():
    storage = Storage(
        StorageConfig("http://storage:3900", "https://synthcut.example", "us-east-1", "media", "k", "s")
    )
    md5 = base64.b64encode(hashlib.md5(b"data").digest()).decode()
    url, headers, _ = storage.presign_part(original_key(P, A, "mov"), "upload-1", 3, md5, 600)
    assert url.startswith("https://synthcut.example/media/projects/")
    assert "content-md5" in url.lower() and "partNumber=3" in url
    assert headers == {"Content-MD5": md5}


def test_md5_conversion():
    raw = hashlib.md5(b"data").digest()
    assert md5_b64_to_hex(base64.b64encode(raw).decode()) == raw.hex()


@pytest.mark.parametrize("size", [1, 5 * MIB, 16 * MIB, 16 * MIB + 1, 5 * 10**9, 50 * 10**9, 200 * 10**9])
def test_part_plan_stays_within_s3_limits(size):
    plan = plan_parts(size)
    assert plan.part_count <= 9000 < MAX_PARTS
    assert plan.part_size >= 5 * MIB and plan.part_size % MIB == 0
    sizes = [
        expected_part_size(n, size, plan.part_size, plan.part_count) for n in range(1, plan.part_count + 1)
    ]
    assert sum(sizes) == size and all(s > 0 for s in sizes)


def test_part_plan_examples_from_docstring():
    assert (plan_parts(5 * 10**9).part_size, plan_parts(5 * 10**9).part_count) == (16 * MIB, 299)
    assert (plan_parts(200 * 10**9).part_size, plan_parts(200 * 10**9).part_count) == (22 * MIB, 8670)
