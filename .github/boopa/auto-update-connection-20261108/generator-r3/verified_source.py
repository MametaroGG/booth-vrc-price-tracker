"""Verified prepared-source v1. Exact consumed bytes, no mutable snapshot copies.

This local profile requires an externally trusted completion digest. It is not a
source selector, acquisition proof or production execution authorization.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import unicodedata
from types import MappingProxyType

PROFILE = 'boopa-verified-prepared-source-v1'
SHA = re.compile(r'[0-9a-f]{64}\Z')
HISTORICAL_FIELDS = frozenset(('schema', 'price_source_commit', 'metadata_source_commit', 'source_receipt_sha256', 'collection_completion_verified', 'whole_catalog_complete', 'price_source_is_latest'))


def historical_provenance(manifest):
    if 'historical_composition' not in manifest:
        return None
    value = manifest['historical_composition']
    if (type(value) is not dict or set(value) != HISTORICAL_FIELDS or
            value['schema'] != 'boopa-historical-composition-v1' or
            value['price_source_commit'] != 'f70df65e6875a8f74eb513201f852151d4b96379' or
            type(value['metadata_source_commit']) is not str or
            re.fullmatch('[0-9a-f]{40}', value['metadata_source_commit']) is None or
            type(value['source_receipt_sha256']) is not str or
            SHA.fullmatch(value['source_receipt_sha256']) is None or
            any(value[k] is not False for k in ('collection_completion_verified', 'whole_catalog_complete', 'price_source_is_latest'))):
        raise ValueError('Explicit fixed-price historical provenance and three false flags required')
    # This validates an externally pinned input assertion. It does not promote
    # the receipt digest to proof of source acquisition or independent review.
    return MappingProxyType(dict(value))


def strict_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError('Duplicate JSON key: ' + key)
            out[key] = value
        return out
    def bad(value):
        raise ValueError('Nonfinite JSON: ' + value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)


def safe_name(name):
    if (not isinstance(name, str) or not name or '\\' in name or
            any(ord(c) < 32 or ord(c) == 127 for c in name)):
        raise ValueError('Unsafe source path')
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or path.as_posix() != name or name == '.':
        raise ValueError('Unsafe source path')
    return path


def canonical_absolute(path):
    raw = os.fspath(path)
    if not isinstance(raw, str) or any(part in ('.', '..') for part in raw.split('/')):
        raise ValueError('Lexical dot path component forbidden')
    return Path(os.path.abspath(raw))


def open_directory(path):
    """Open every component using O_NOFOLLOW, including the root ancestors."""
    path = canonical_absolute(path)
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in path.parts[1:]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def exact_read(root_fd, name, limit):
    parts = safe_name(name).parts
    fd = os.dup(root_fd)
    try:
        for component in parts[:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            info = os.fstat(file_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError('Nonregular or over-budget source record: ' + name)
            chunks = []
            size = 0
            while True:
                chunk = os.read(file_fd, min(1024 * 1024, limit + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > limit:
                    raise ValueError('Source read exceeded explicit memory budget: ' + name)
            return b''.join(chunks)
        finally:
            os.close(file_fd)
    finally:
        os.close(fd)


class VerifiedSource:
    def __init__(self, root, completion_sha256, *, maximum_record_bytes=128 * 1024 * 1024, run_bindings=None):
        if not isinstance(completion_sha256, str) or not SHA.fullmatch(completion_sha256):
            raise ValueError('Externally pinned completion SHA256 required')
        if type(maximum_record_bytes) is not int or maximum_record_bytes <= 0:
            raise ValueError('Explicit positive record memory budget required')
        self.root = canonical_absolute(root)
        self.maximum_record_bytes = maximum_record_bytes
        self.fd = open_directory(self.root)
        try:
            raw = exact_read(self.fd, 'completion.json', maximum_record_bytes)
            if hashlib.sha256(raw).hexdigest() != completion_sha256:
                raise ValueError('Trusted completion commitment mismatch')
            manifest = strict_json(raw)
            from datetime import date
            if (type(manifest.get('schema')) is not int or manifest['schema'] != 1 or
                    manifest.get('status') != 'complete' or type(manifest.get('fixture')) is not bool or
                    not isinstance(manifest.get('collection_id'), str) or not manifest['collection_id'] or
                    date.fromisoformat(manifest['expected_date']).isoformat() != manifest['expected_date']):
                raise ValueError('Explicit complete producer manifest required')
            hashes = manifest.get('files')
            if not isinstance(hashes, dict) or not hashes or 'charts.json' not in hashes:
                raise ValueError('Complete input inventory and charts required')
            folded = set()
            for name, sha in hashes.items():
                path = safe_name(name)
                if not (name in ('charts.json', 'metadata.json') or
                        (path.parts[0] in ('data', 'tracker_meta') and len(path.parts) >= 2)):
                    raise ValueError('Unknown source namespace: ' + name)
                if not (name.endswith('.json') or path.name == '.gitkeep') or not isinstance(sha, str) or not SHA.fullmatch(sha):
                    raise ValueError('Invalid input commitment: ' + name)
                key = unicodedata.normalize('NFC', name).casefold()
                if key in folded:
                    raise ValueError('Normalized source path collision')
                folded.add(key)
            self.hashes = MappingProxyType(dict(hashes))
            self.historical_composition = historical_provenance(manifest)
            from saved_snapshot_policy import provenance
            self.saved_snapshot_composition = provenance(manifest,run_bindings)
            self.run_bindings = run_bindings
            self.manifest_bytes = raw
            self.completion_sha256 = completion_sha256
            self.manifest = manifest
            self.manifest['_source_manifest_sha256'] = completion_sha256
            self.read_count = 0
            self.read_bytes_count = 0
            self.consumed = set()
            self.assert_inventory()
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def relative(self, path):
        path = canonical_absolute(path)
        try:
            name = path.relative_to(self.root).as_posix()
        except ValueError:
            raise ValueError('Source read escapes pinned root') from None
        safe_name(name)
        if name not in self.hashes:
            raise ValueError('Uncommitted source read: ' + name)
        return name

    def paths(self, directory, *, products_only=False):
        if directory not in ('data', 'tracker_meta'):
            raise ValueError('Invalid source namespace')
        for name in self.hashes:
            path = PurePosixPath(name)
            if path.parts[0] == directory and (not products_only or (len(path.parts) == 3 and path.suffix == '.json')):
                yield self.root / name

    def read_bytes(self, path):
        name = self.relative(path)
        raw = exact_read(self.fd, name, self.maximum_record_bytes)
        if hashlib.sha256(raw).hexdigest() != self.hashes[name]:
            raise ValueError('Consumed bytes differ from trusted commitment: ' + name)
        if name.endswith('.gitkeep') and raw:
            raise ValueError('Nonempty placeholder')
        self.read_count += 1
        self.read_bytes_count += len(raw)
        self.consumed.add(name)
        return raw

    def read_json(self, path):
        return strict_json(self.read_bytes(path))

    def assert_disjoint(self, output):
        output = canonical_absolute(output)
        # All existing output ancestors must also be non-symlink directories.
        existing = output
        while not existing.exists():
            if existing.is_symlink():
                raise ValueError('Linked output ancestor')
            existing = existing.parent
        fd = open_directory(existing)
        os.close(fd)
        if output == self.root or self.root in output.parents or output in self.root.parents:
            raise ValueError('Output and verified source must be disjoint')

    def assert_inventory(self):
        actual = set()
        actual_dirs = set()
        def visit(fd, prefix=''):
            for entry in os.scandir(fd):
                name = prefix + entry.name
                safe_name(name)
                mode = os.stat(entry.name, dir_fd=fd, follow_symlinks=False).st_mode
                if stat.S_ISDIR(mode):
                    actual_dirs.add(name)
                    child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        visit(child, name + '/')
                    finally:
                        os.close(child)
                elif stat.S_ISREG(mode):
                    actual.add(name)
                else:
                    raise ValueError('Linked/nonregular source entry: ' + name)
        visit(self.fd)
        expected_dirs = {'data', 'tracker_meta'}
        for name in self.hashes:
            expected_dirs.update(str(p) for p in PurePosixPath(name).parents if str(p) != '.')
        if actual != set(self.hashes) | {'completion.json'} or actual_dirs != expected_dirs:
            raise ValueError('Exact source file/directory inventory differs')
        # A renamed/replaced root cannot silently change the namespace scanned.
        check = open_directory(self.root)
        try:
            if (os.fstat(check).st_dev, os.fstat(check).st_ino) != (os.fstat(self.fd).st_dev, os.fstat(self.fd).st_ino):
                raise ValueError('Verified source root replaced')
        finally:
            os.close(check)
        if exact_read(self.fd, 'completion.json', self.maximum_record_bytes) != self.manifest_bytes:
            raise ValueError('Completion changed')

    def verify_all(self):
        for name in self.hashes:
            raw = self.read_bytes(self.root / name)
            if name.endswith('.json'):
                strict_json(raw)
        self.assert_inventory()

    def finish(self):
        self.verify_all()
        if self.consumed != set(self.hashes):
            raise ValueError('Unverified source entries')
        return {'schema': PROFILE, 'completion_sha256': self.completion_sha256,
                'inventory_files': len(self.hashes), 'read_operations': self.read_count,
                'verified_read_bytes': self.read_bytes_count, 'raw_copy_files': 0}


def verify_artifact_directory(fd, expected_hashes, maximum_file_bytes=128 * 1024 * 1024):
    """Check the exact non-serving output behind a held directory descriptor."""
    actual = set()
    directories = set()
    def visit(current_fd, prefix=''):
        for entry in os.scandir(current_fd):
            name = prefix + entry.name
            safe_name(name)
            mode = os.stat(entry.name, dir_fd=current_fd, follow_symlinks=False).st_mode
            if stat.S_ISDIR(mode):
                directories.add(name)
                child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current_fd)
                try:
                    visit(child, name + '/')
                finally:
                    os.close(child)
            elif stat.S_ISREG(mode):
                if name not in expected_hashes:
                    raise ValueError('Unexpected artifact file: ' + name)
                raw = exact_read(fd, name, maximum_file_bytes)
                if hashlib.sha256(raw).hexdigest() != expected_hashes[name]:
                    raise ValueError('Artifact bytes changed: ' + name)
                actual.add(name)
            else:
                raise ValueError('Linked/nonregular artifact entry: ' + name)
    visit(fd)
    wanted_dirs = {str(p) for name in expected_hashes for p in PurePosixPath(name).parents if str(p) != '.'}
    if actual != set(expected_hashes) or directories != wanted_dirs:
        raise ValueError('Artifact namespace changed')


class VerifiedOutput:
    """Narrow internal capability for the newly created candidate directory.

    No arbitrary /proc-prefix exemption. Reads are relative to this retained fd,
    with no-follow components; the supplied output path must name this inode.
    """
    def __init__(self, fd):
        self.fd = os.dup(fd)
        self.expected_hashes = None
        if not stat.S_ISDIR(os.fstat(self.fd).st_mode):
            self.close()
            raise ValueError('Candidate directory descriptor required')

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def assert_root(self, root):
        actual = os.stat(root)
        expected = os.fstat(self.fd)
        if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
            raise ValueError('Candidate output capability/root mismatch')

    def bind_expected(self, hashes):
        if self.expected_hashes is not None:
            raise ValueError('Output approval binding cannot be replaced')
        for name, value in hashes.items():
            safe_name(name)
            if not isinstance(value, str) or not SHA.fullmatch(value):
                raise ValueError('Explicit approved output digest required')
        self.expected_hashes = MappingProxyType(dict(hashes))

    def read_bytes(self, name):
        if self.expected_hashes is None or name not in self.expected_hashes:
            raise ValueError('Unbound candidate validation read')
        raw = exact_read(self.fd, name, 128 * 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != self.expected_hashes[name]:
            raise ValueError('Candidate validation bytes differ from approval: ' + name)
        return raw

    def exists(self, name):
        try:
            self.read_bytes(name)
            return True
        except FileNotFoundError:
            return False
