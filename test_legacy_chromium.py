import unittest

from sanitize_legacy_chromium import sanitize_source


class LegacyChromiumSanitizerTests(unittest.TestCase):
    def test_removes_only_the_two_i18next_banner_glyphs(self):
        source = 'console.info("' + chr(0x1F310) + ' i18next banner 💙")'
        self.assertEqual(
            sanitize_source(source),
            'console.info("[web] i18next banner ")'
        )

    def test_rejects_an_unexpected_non_bmp_character(self):
        source = 'banner ' + chr(0x1F310) + ' 💙 ' + chr(0x1F9EA)
        with self.assertRaisesRegex(ValueError, "Unexpected non-BMP"):
            sanitize_source(source)

    def test_rejects_changed_upstream_banner(self):
        source = 'console.info("' + chr(0x1F310) + ' no heart")'
        with self.assertRaisesRegex(ValueError, "Expected exactly one"):
            sanitize_source(source)


if __name__ == "__main__":
    unittest.main()
