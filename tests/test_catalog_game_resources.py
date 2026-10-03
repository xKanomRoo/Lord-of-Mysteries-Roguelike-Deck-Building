import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools import catalog_game_resources as catalog
from tools import decode_texture
from tools import read_ssra_manifest as ssra


class CatalogTests(unittest.TestCase):
    def fixture(self):
        data = b'non executable fixture'
        row = {'row': 0, 'path': 'card/a.sct', 'group_id': 12, 'stored_length': 11,
               'decoded_length': len(data), 'file_hash64': ssra.xxh64(data)}
        manifest = {'groups': [{'id': 12, 'name': 'base'}], 'files': [row]}
        receipt = {'source_manifest': {'sha256': catalog.MANIFEST_SHA}, 'files': [{
            'resource_path': row['path'], 'manifest_file_row': 0, 'group_id': 12,
            'stored_bytes': 11, 'decoded_bytes': len(data), 'archive_path': 'files/00.bin',
            'decoded_sha256': catalog.digest(data), 'stored_sha256': 'f' * 64, 'fhsh_verified': True}]}
        return data, manifest, receipt

    def test_names_are_not_received_payloads(self):
        _, manifest, _ = self.fixture()
        rows, summary = catalog.build_catalog(manifest, {}, {})
        self.assertEqual(rows[0]['status'], 'metadata_only')
        self.assertFalse(rows[0]['received'])
        self.assertEqual(summary['metadata_only_resources'], 1)

    def test_received_bytes_and_manifest_checks(self):
        data, manifest, receipt = self.fixture()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'files').mkdir(); (root / 'files/00.bin').write_bytes(data)
            received = catalog.check_decoded_receipt(manifest, receipt, root)
            rows, summary = catalog.build_catalog(manifest, received, {})
            self.assertEqual(rows[0]['status'], 'received_container')
            self.assertEqual(summary['received_manifest_resources'], 1)
            (root / 'files/00.bin').write_bytes(b'wrong received content')
            with self.assertRaises(catalog.CatalogError):
                catalog.check_decoded_receipt(manifest, receipt, root)

    def test_wrong_manifest_or_fhsh_rejected(self):
        data, manifest, receipt = self.fixture()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'files').mkdir(); (root / 'files/00.bin').write_bytes(data)
            receipt['source_manifest']['sha256'] = '0' * 64
            with self.assertRaises(catalog.CatalogError):
                catalog.check_decoded_receipt(manifest, receipt, root)
            receipt['source_manifest']['sha256'] = catalog.MANIFEST_SHA
            manifest['files'][0]['file_hash64'] += 1
            with self.assertRaises(catalog.CatalogError):
                catalog.check_decoded_receipt(manifest, receipt, root)

    def test_duplicate_names_and_unrelated_evidence_rejected(self):
        _, manifest, _ = self.fixture()
        manifest['files'].append(dict(manifest['files'][0]))
        with self.assertRaises(catalog.CatalogError):
            catalog.build_catalog(manifest, {}, {})
        manifest['files'].pop()
        with self.assertRaises(catalog.CatalogError):
            catalog.build_catalog(manifest, {'other/path.db': {}}, {})

    def test_png_crc_and_dimensions_checked(self):
        png = decode_texture.encode_png_rgba(1, 1, b'\x10\x20\x30\xff')
        self.assertEqual(catalog.png_dimensions(png), (1, 1))
        broken = bytearray(png); broken[-1] ^= 1
        with self.assertRaises(catalog.CatalogError):
            catalog.png_dimensions(bytes(broken))

    def test_metadata_html_escapes_embedded_script_label(self):
        _, manifest, _ = self.fixture()
        manifest['files'][0]['path'] = 'image/</script><script>alert(1)</script>.sct'
        rows, summary = catalog.build_catalog(manifest, {}, {})
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'index.html'; catalog.write_catalog_html(path, rows, summary)
            body = path.read_text()
            self.assertNotIn('</script><script>alert(1)', body)
            self.assertIn('\\u003c/script>', body)

    def test_unsafe_labels_symlinks_rejected(self):
        for label in ('../source', '/tmp/a', 'a\\b', 'a:b', 'a\n/b'):
            with self.assertRaises(catalog.CatalogError): catalog.source_label(label)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'source').write_bytes(b'bytes');(root/'alias').symlink_to(root/'source')
            with self.assertRaises(catalog.CatalogError): catalog.checked_bytes(root/'alias')

    def test_archive_contains_all_indexed_source_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'data').write_bytes(b'private inert data')
            result = catalog.archive_group(root, 'delivery.zip', [('data/00.bin', root/'data')], 'fixture')
            with zipfile.ZipFile(root / 'delivery.zip') as archive:
                self.assertEqual(result['verified_members'], len(archive.infolist()))
            self.assertEqual(result['verified_members'], 3)
            self.assertEqual(result['verified_source_members'], 1)
            self.assertLess(result['bytes'], catalog.MAX_ZIP)

    def test_duplicate_archive_labels_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'data').write_bytes(b'inert')
            with self.assertRaises(catalog.CatalogError):
                catalog.archive_group(root, 'delivery.zip', [('data.bin', root/'data'), ('data.bin', root/'data')], 'fixture')


if __name__ == '__main__':
    unittest.main()
