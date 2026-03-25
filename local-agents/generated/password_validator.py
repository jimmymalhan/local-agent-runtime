import unittest


def validate_password(pwd: str) -> tuple[bool, list[str]]:
    violations = []

    if len(pwd) < 8:
        violations.append("Password must be at least 8 characters")
    if not any(c.isupper() for c in pwd):
        violations.append("Password must contain at least one uppercase letter")
    if not any(c.islower() for c in pwd):
        violations.append("Password must contain at least one lowercase letter")
    if not any(c.isdigit() for c in pwd):
        violations.append("Password must contain at least one digit")
    if not any(c in "!@#$%^&*()-_=+[]{}|;:',.<>?/`~" for c in pwd):
        violations.append("Password must contain at least one special character")

    return (len(violations) == 0, violations)


class TestPasswordValidator(unittest.TestCase):

    def test_valid_password(self):
        is_valid, violations = validate_password("Abcdef1!")
        self.assertTrue(is_valid)
        self.assertEqual(violations, [])

    def test_too_short(self):
        is_valid, violations = validate_password("Ab1!")
        self.assertFalse(is_valid)
        self.assertIn("Password must be at least 8 characters", violations)

    def test_missing_uppercase(self):
        is_valid, violations = validate_password("abcdef1!")
        self.assertFalse(is_valid)
        self.assertIn("Password must contain at least one uppercase letter", violations)

    def test_missing_lowercase(self):
        is_valid, violations = validate_password("ABCDEF1!")
        self.assertFalse(is_valid)
        self.assertIn("Password must contain at least one lowercase letter", violations)

    def test_missing_digit(self):
        is_valid, violations = validate_password("Abcdefg!")
        self.assertFalse(is_valid)
        self.assertIn("Password must contain at least one digit", violations)

    def test_missing_special_char(self):
        is_valid, violations = validate_password("Abcdefg1")
        self.assertFalse(is_valid)
        self.assertIn("Password must contain at least one special character", violations)

    def test_empty_string(self):
        is_valid, violations = validate_password("")
        self.assertFalse(is_valid)
        self.assertEqual(len(violations), 5)

    def test_all_violations(self):
        is_valid, violations = validate_password("")
        self.assertFalse(is_valid)
        self.assertIn("Password must be at least 8 characters", violations)
        self.assertIn("Password must contain at least one uppercase letter", violations)
        self.assertIn("Password must contain at least one lowercase letter", violations)
        self.assertIn("Password must contain at least one digit", violations)
        self.assertIn("Password must contain at least one special character", violations)

    def test_exactly_8_chars_valid(self):
        is_valid, violations = validate_password("Abcdef1!")
        self.assertTrue(is_valid)
        self.assertEqual(violations, [])

    def test_7_chars_too_short(self):
        is_valid, violations = validate_password("Abcde1!")
        self.assertFalse(is_valid)
        self.assertIn("Password must be at least 8 characters", violations)

    def test_long_valid_password(self):
        is_valid, violations = validate_password("Abcdefghijklmnop1!")
        self.assertTrue(is_valid)
        self.assertEqual(violations, [])

    def test_only_digits(self):
        is_valid, violations = validate_password("12345678")
        self.assertFalse(is_valid)
        self.assertNotIn("Password must be at least 8 characters", violations)
        self.assertIn("Password must contain at least one uppercase letter", violations)
        self.assertIn("Password must contain at least one lowercase letter", violations)
        self.assertIn("Password must contain at least one special character", violations)

    def test_multiple_special_chars(self):
        is_valid, violations = validate_password("Aa1!@#$%")
        self.assertTrue(is_valid)
        self.assertEqual(violations, [])

    def test_returns_tuple(self):
        result = validate_password("Abcdef1!")
        self.assertIsInstance(result, tuple)
        self.assertIsInstance(result[0], bool)
        self.assertIsInstance(result[1], list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
