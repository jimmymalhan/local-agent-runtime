"""TDD tests for ReportGenerator: a CSV/JSON report generation utility."""

import csv
import io
import json
import unittest


class ReportGenerator:
    """Generates reports from tabular data with filtering, sorting, and export."""

    def __init__(self):
        self._headers = []
        self._rows = []

    def set_headers(self, headers):
        if not headers:
            raise ValueError("Headers cannot be empty")
        if len(headers) != len(set(headers)):
            raise ValueError("Duplicate headers are not allowed")
        self._headers = list(headers)

    def add_row(self, row):
        if not self._headers:
            raise ValueError("Headers must be set before adding rows")
        if len(row) != len(self._headers):
            raise ValueError(
                f"Row length {len(row)} does not match header length {len(self._headers)}"
            )
        self._rows.append(list(row))

    def filter_rows(self, predicate):
        if not callable(predicate):
            raise TypeError("Predicate must be callable")
        filtered = ReportGenerator()
        filtered.set_headers(self._headers)
        for row in self._rows:
            row_dict = dict(zip(self._headers, row))
            if predicate(row_dict):
                filtered.add_row(row)
        return filtered

    def sort_by(self, col, reverse=False):
        if col not in self._headers:
            raise KeyError(f"Column '{col}' not found in headers")
        idx = self._headers.index(col)
        sorted_gen = ReportGenerator()
        sorted_gen.set_headers(self._headers)
        for row in sorted(self._rows, key=lambda r: r[idx], reverse=reverse):
            sorted_gen.add_row(row)
        return sorted_gen

    def export_csv(self):
        if not self._headers:
            raise ValueError("No headers set")
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(self._headers)
        writer.writerows(self._rows)
        return output.getvalue()

    def export_json(self):
        if not self._headers:
            raise ValueError("No headers set")
        records = [dict(zip(self._headers, row)) for row in self._rows]
        return json.dumps(records, indent=2)


class TestReportGeneratorSetHeaders(unittest.TestCase):

    def test_set_headers_stores_headers(self):
        rg = ReportGenerator()
        rg.set_headers(["name", "age", "city"])
        self.assertEqual(rg._headers, ["name", "age", "city"])

    def test_set_headers_empty_raises(self):
        rg = ReportGenerator()
        with self.assertRaises(ValueError):
            rg.set_headers([])

    def test_set_headers_duplicates_raises(self):
        rg = ReportGenerator()
        with self.assertRaises(ValueError):
            rg.set_headers(["name", "name"])

    def test_set_headers_overwrites_previous(self):
        rg = ReportGenerator()
        rg.set_headers(["a", "b"])
        rg.set_headers(["x", "y", "z"])
        self.assertEqual(rg._headers, ["x", "y", "z"])


class TestReportGeneratorAddRow(unittest.TestCase):

    def setUp(self):
        self.rg = ReportGenerator()
        self.rg.set_headers(["name", "age", "city"])

    def test_add_row_stores_data(self):
        self.rg.add_row(["Alice", 30, "NYC"])
        self.assertEqual(len(self.rg._rows), 1)
        self.assertEqual(self.rg._rows[0], ["Alice", 30, "NYC"])

    def test_add_multiple_rows(self):
        self.rg.add_row(["Alice", 30, "NYC"])
        self.rg.add_row(["Bob", 25, "LA"])
        self.assertEqual(len(self.rg._rows), 2)

    def test_add_row_without_headers_raises(self):
        rg = ReportGenerator()
        with self.assertRaises(ValueError):
            rg.add_row(["Alice", 30, "NYC"])

    def test_add_row_wrong_length_raises(self):
        with self.assertRaises(ValueError):
            self.rg.add_row(["Alice", 30])

    def test_add_row_too_many_columns_raises(self):
        with self.assertRaises(ValueError):
            self.rg.add_row(["Alice", 30, "NYC", "extra"])


class TestReportGeneratorFilterRows(unittest.TestCase):

    def setUp(self):
        self.rg = ReportGenerator()
        self.rg.set_headers(["name", "age", "city"])
        self.rg.add_row(["Alice", 30, "NYC"])
        self.rg.add_row(["Bob", 25, "LA"])
        self.rg.add_row(["Charlie", 35, "NYC"])

    def test_filter_returns_matching_rows(self):
        result = self.rg.filter_rows(lambda r: r["city"] == "NYC")
        self.assertEqual(len(result._rows), 2)
        self.assertEqual(result._rows[0][0], "Alice")
        self.assertEqual(result._rows[1][0], "Charlie")

    def test_filter_no_match_returns_empty(self):
        result = self.rg.filter_rows(lambda r: r["city"] == "Chicago")
        self.assertEqual(len(result._rows), 0)

    def test_filter_all_match(self):
        result = self.rg.filter_rows(lambda r: r["age"] > 20)
        self.assertEqual(len(result._rows), 3)

    def test_filter_preserves_headers(self):
        result = self.rg.filter_rows(lambda r: r["city"] == "NYC")
        self.assertEqual(result._headers, ["name", "age", "city"])

    def test_filter_returns_new_instance(self):
        result = self.rg.filter_rows(lambda r: True)
        self.assertIsNot(result, self.rg)

    def test_filter_does_not_mutate_original(self):
        original_count = len(self.rg._rows)
        self.rg.filter_rows(lambda r: r["city"] == "NYC")
        self.assertEqual(len(self.rg._rows), original_count)

    def test_filter_non_callable_raises(self):
        with self.assertRaises(TypeError):
            self.rg.filter_rows("not a function")

    def test_filter_by_numeric_comparison(self):
        result = self.rg.filter_rows(lambda r: r["age"] >= 30)
        self.assertEqual(len(result._rows), 2)
        names = [row[0] for row in result._rows]
        self.assertIn("Alice", names)
        self.assertIn("Charlie", names)


class TestReportGeneratorSortBy(unittest.TestCase):

    def setUp(self):
        self.rg = ReportGenerator()
        self.rg.set_headers(["name", "age", "city"])
        self.rg.add_row(["Charlie", 35, "NYC"])
        self.rg.add_row(["Alice", 30, "LA"])
        self.rg.add_row(["Bob", 25, "Chicago"])

    def test_sort_by_string_column(self):
        result = self.rg.sort_by("name")
        names = [row[0] for row in result._rows]
        self.assertEqual(names, ["Alice", "Bob", "Charlie"])

    def test_sort_by_numeric_column(self):
        result = self.rg.sort_by("age")
        ages = [row[1] for row in result._rows]
        self.assertEqual(ages, [25, 30, 35])

    def test_sort_by_reverse(self):
        result = self.rg.sort_by("age", reverse=True)
        ages = [row[1] for row in result._rows]
        self.assertEqual(ages, [35, 30, 25])

    def test_sort_by_invalid_column_raises(self):
        with self.assertRaises(KeyError):
            self.rg.sort_by("nonexistent")

    def test_sort_returns_new_instance(self):
        result = self.rg.sort_by("name")
        self.assertIsNot(result, self.rg)

    def test_sort_does_not_mutate_original(self):
        original_first = self.rg._rows[0][0]
        self.rg.sort_by("name")
        self.assertEqual(self.rg._rows[0][0], original_first)

    def test_sort_preserves_headers(self):
        result = self.rg.sort_by("name")
        self.assertEqual(result._headers, ["name", "age", "city"])

    def test_sort_empty_rows(self):
        rg = ReportGenerator()
        rg.set_headers(["a", "b"])
        result = rg.sort_by("a")
        self.assertEqual(len(result._rows), 0)


class TestReportGeneratorExportCSV(unittest.TestCase):

    def setUp(self):
        self.rg = ReportGenerator()
        self.rg.set_headers(["name", "age", "city"])
        self.rg.add_row(["Alice", 30, "NYC"])
        self.rg.add_row(["Bob", 25, "LA"])

    def test_export_csv_contains_headers(self):
        output = self.rg.export_csv()
        lines = output.strip().splitlines()
        self.assertEqual(lines[0].strip(), "name,age,city")

    def test_export_csv_contains_rows(self):
        output = self.rg.export_csv()
        lines = output.strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[1].strip(), "Alice,30,NYC")
        self.assertEqual(lines[2].strip(), "Bob,25,LA")

    def test_export_csv_is_valid_csv(self):
        output = self.rg.export_csv()
        reader = csv.reader(io.StringIO(output))
        rows = list(reader)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], ["name", "age", "city"])
        self.assertEqual(rows[1], ["Alice", "30", "NYC"])

    def test_export_csv_empty_rows(self):
        rg = ReportGenerator()
        rg.set_headers(["x", "y"])
        output = rg.export_csv()
        lines = output.strip().split("\n")
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0], "x,y")

    def test_export_csv_no_headers_raises(self):
        rg = ReportGenerator()
        with self.assertRaises(ValueError):
            rg.export_csv()

    def test_export_csv_with_commas_in_data(self):
        rg = ReportGenerator()
        rg.set_headers(["name", "note"])
        rg.add_row(["Alice", "hello, world"])
        output = rg.export_csv()
        reader = csv.reader(io.StringIO(output))
        rows = list(reader)
        self.assertEqual(rows[1], ["Alice", "hello, world"])

    def test_export_csv_with_quotes_in_data(self):
        rg = ReportGenerator()
        rg.set_headers(["name", "note"])
        rg.add_row(["Alice", 'said "hi"'])
        output = rg.export_csv()
        reader = csv.reader(io.StringIO(output))
        rows = list(reader)
        self.assertEqual(rows[1], ["Alice", 'said "hi"'])


class TestReportGeneratorExportJSON(unittest.TestCase):

    def setUp(self):
        self.rg = ReportGenerator()
        self.rg.set_headers(["name", "age", "city"])
        self.rg.add_row(["Alice", 30, "NYC"])
        self.rg.add_row(["Bob", 25, "LA"])

    def test_export_json_is_valid_json(self):
        output = self.rg.export_json()
        data = json.loads(output)
        self.assertIsInstance(data, list)

    def test_export_json_contains_correct_records(self):
        output = self.rg.export_json()
        data = json.loads(output)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0], {"name": "Alice", "age": 30, "city": "NYC"})
        self.assertEqual(data[1], {"name": "Bob", "age": 25, "city": "LA"})

    def test_export_json_empty_rows(self):
        rg = ReportGenerator()
        rg.set_headers(["x", "y"])
        output = rg.export_json()
        data = json.loads(output)
        self.assertEqual(data, [])

    def test_export_json_no_headers_raises(self):
        rg = ReportGenerator()
        with self.assertRaises(ValueError):
            rg.export_json()

    def test_export_json_keys_match_headers(self):
        output = self.rg.export_json()
        data = json.loads(output)
        for record in data:
            self.assertEqual(sorted(record.keys()), sorted(["name", "age", "city"]))


class TestReportGeneratorIntegration(unittest.TestCase):
    """End-to-end workflows combining multiple operations."""

    def test_filter_then_sort_then_export_csv(self):
        rg = ReportGenerator()
        rg.set_headers(["product", "price", "qty"])
        rg.add_row(["Widget", 9.99, 100])
        rg.add_row(["Gadget", 24.99, 50])
        rg.add_row(["Widget", 9.99, 200])
        rg.add_row(["Doohickey", 4.99, 75])

        result = rg.filter_rows(lambda r: r["price"] < 20).sort_by("qty")
        output = result.export_csv()
        reader = csv.reader(io.StringIO(output))
        rows = list(reader)

        self.assertEqual(rows[0], ["product", "price", "qty"])
        self.assertEqual(len(rows), 4)  # header + 3 data rows
        qtys = [int(row[2]) for row in rows[1:]]
        self.assertEqual(qtys, [75, 100, 200])

    def test_sort_then_export_json(self):
        rg = ReportGenerator()
        rg.set_headers(["name", "score"])
        rg.add_row(["Zara", 88])
        rg.add_row(["Amy", 95])
        rg.add_row(["Mia", 72])

        result = rg.sort_by("score", reverse=True)
        data = json.loads(result.export_json())

        self.assertEqual(data[0]["name"], "Amy")
        self.assertEqual(data[1]["name"], "Zara")
        self.assertEqual(data[2]["name"], "Mia")

    def test_filter_then_export_json(self):
        rg = ReportGenerator()
        rg.set_headers(["status", "count"])
        rg.add_row(["active", 10])
        rg.add_row(["inactive", 3])
        rg.add_row(["active", 7])

        result = rg.filter_rows(lambda r: r["status"] == "active")
        data = json.loads(result.export_json())

        self.assertEqual(len(data), 2)
        self.assertTrue(all(d["status"] == "active" for d in data))

    def test_chained_filters(self):
        rg = ReportGenerator()
        rg.set_headers(["name", "age", "dept"])
        rg.add_row(["Alice", 30, "Eng"])
        rg.add_row(["Bob", 40, "Eng"])
        rg.add_row(["Charlie", 25, "Sales"])
        rg.add_row(["Diana", 35, "Eng"])

        result = (
            rg.filter_rows(lambda r: r["dept"] == "Eng")
              .filter_rows(lambda r: r["age"] >= 35)
        )
        self.assertEqual(len(result._rows), 2)
        names = [row[0] for row in result._rows]
        self.assertIn("Bob", names)
        self.assertIn("Diana", names)


if __name__ == "__main__":
    # Run unittest suite
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(__import__(__name__))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Additional standalone assertions
    print("\n--- Standalone assertions ---")

    rg = ReportGenerator()
    rg.set_headers(["a", "b"])
    rg.add_row([1, 2])
    rg.add_row([3, 4])

    csv_out = rg.export_csv()
    assert "a,b" in csv_out, "CSV must contain headers"
    assert "1,2" in csv_out, "CSV must contain first row"
    assert "3,4" in csv_out, "CSV must contain second row"

    json_out = rg.export_json()
    parsed = json.loads(json_out)
    assert len(parsed) == 2, "JSON must have 2 records"
    assert parsed[0] == {"a": 1, "b": 2}, "First JSON record must match"
    assert parsed[1] == {"a": 3, "b": 4}, "Second JSON record must match"

    sorted_rg = rg.sort_by("a", reverse=True)
    assert sorted_rg._rows[0] == [3, 4], "Sort descending must put 3 first"

    filtered_rg = rg.filter_rows(lambda r: r["a"] > 1)
    assert len(filtered_rg._rows) == 1, "Filter must return 1 matching row"
    assert filtered_rg._rows[0] == [3, 4], "Filtered row must be [3, 4]"

    print("All standalone assertions passed!")

    # Exit with proper code
    exit(0 if result.wasSuccessful() else 1)
