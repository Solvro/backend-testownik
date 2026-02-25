from unittest.mock import AsyncMock

from django.test import SimpleTestCase

from grades.views import get_user_courses_ects_safe


class GetUserCoursesEctsSafeTestCase(SimpleTestCase):
    """Test the safe ECTS wrapper function that fixes the None ECTS bug"""

    async def test_filters_none_values(self):
        """
        Test that None values are handled safely.

        This is the main bug fix - USOS API returns None for courses without
        assigned ECTS points, which caused: TypeError: float() argument must
        be a string or a real number, not 'NoneType'

        Our solution: Convert None to 0.0 so courses are still visible.
        """
        mock_client = AsyncMock()
        mock_client.connection.get.return_value = {
            "2023Z": {
                "COURSE123": "5.0",
                "COURSE456": None,  # This caused TypeError in original code
                "COURSE789": "3.5",
            },
            "2024L": {
                "COURSE999": None,  # Another None value
                "COURSE888": "6.0",
            },
        }

        # This should not raise TypeError
        result = await get_user_courses_ects_safe(mock_client)

        # Verify that None values were converted to 0.0 (not filtered out)
        self.assertIn("2023Z", result)
        self.assertEqual(result["2023Z"]["COURSE123"], 5.0)
        self.assertEqual(result["2023Z"]["COURSE789"], 3.5)
        self.assertEqual(result["2023Z"]["COURSE456"], 0.0)  # None → 0.0

        self.assertIn("2024L", result)
        self.assertEqual(result["2024L"]["COURSE888"], 6.0)
        self.assertEqual(result["2024L"]["COURSE999"], 0.0)  # None → 0.0

        # Verify correct API endpoint was called
        mock_client.connection.get.assert_called_once_with("services/courses/user_ects_points", params={})

    async def test_handles_term_with_all_none_values(self):
        """Test that terms with all None ECTS values are still included with 0.0"""
        mock_client = AsyncMock()
        mock_client.connection.get.return_value = {
            "2023Z": {
                "COURSE123": "5.0",
                "COURSE456": "3.0",
            },
            "2024L": {
                "COURSE999": None,
                "COURSE888": None,
            },
        }

        result = await get_user_courses_ects_safe(mock_client)

        # Term with valid ECTS should be present
        self.assertIn("2023Z", result)
        self.assertEqual(len(result["2023Z"]), 2)

        # Term with all None values should still be present with 0.0
        self.assertIn("2024L", result)
        self.assertEqual(len(result["2024L"]), 2)
        self.assertEqual(result["2024L"]["COURSE999"], 0.0)
        self.assertEqual(result["2024L"]["COURSE888"], 0.0)

    async def test_handles_empty_response(self):
        """Test that empty API response is handled correctly"""
        mock_client = AsyncMock()
        mock_client.connection.get.return_value = {}

        result = await get_user_courses_ects_safe(mock_client)

        self.assertEqual(result, {})
        self.assertIsInstance(result, dict)

    async def test_converts_string_ects_to_float(self):
        """Test that string ECTS values are properly converted to float"""
        mock_client = AsyncMock()
        mock_client.connection.get.return_value = {
            "2023Z": {
                "COURSE123": "5.0",
                "COURSE456": "3.5",
                "COURSE789": "6",  # Integer as string
            },
        }

        result = await get_user_courses_ects_safe(mock_client)

        # All values should be floats
        self.assertIsInstance(result["2023Z"]["COURSE123"], float)
        self.assertIsInstance(result["2023Z"]["COURSE456"], float)
        self.assertIsInstance(result["2023Z"]["COURSE789"], float)
        self.assertEqual(result["2023Z"]["COURSE789"], 6.0)

    async def test_handles_mixed_valid_and_none_courses(self):
        """Test realistic scenario with mix of valid ECTS and None values"""
        mock_client = AsyncMock()
        mock_client.connection.get.return_value = {
            "2023Z": {
                "MAT101": "5.0",
                "FIZ201": None,  # Course without ECTS assigned
                "INF301": "4.0",
                "CHE102": None,  # Another course without ECTS
                "ENG401": "3.0",
            },
        }

        result = await get_user_courses_ects_safe(mock_client)

        # Should contain all courses (None converted to 0.0)
        self.assertEqual(len(result["2023Z"]), 5)
        self.assertIn("MAT101", result["2023Z"])
        self.assertIn("INF301", result["2023Z"])
        self.assertIn("ENG401", result["2023Z"])
        self.assertIn("FIZ201", result["2023Z"])
        self.assertIn("CHE102", result["2023Z"])

        # Courses with valid ECTS
        self.assertEqual(result["2023Z"]["MAT101"], 5.0)
        self.assertEqual(result["2023Z"]["INF301"], 4.0)
        self.assertEqual(result["2023Z"]["ENG401"], 3.0)

        # Courses with None should be 0.0
        self.assertEqual(result["2023Z"]["FIZ201"], 0.0)
        self.assertEqual(result["2023Z"]["CHE102"], 0.0)

    async def test_handles_invalid_ects_conversion(self):
        """Test that invalid ECTS values (non-numeric strings, objects) are handled gracefully"""
        mock_client = AsyncMock()
        mock_client.connection.get.return_value = {
            "2023Z": {
                "COURSE123": "5.0",
                "COURSE456": "invalid_string",  # Invalid - can't convert to float
                "COURSE789": "3.5",
                "COURSE999": {"nested": "object"},  # Invalid - object instead of string
                "COURSE000": [1, 2, 3],  # Invalid - list instead of string
            },
        }

        # Should not crash, should convert invalid values to 0.0
        result = await get_user_courses_ects_safe(mock_client)

        # Valid ECTS should be present
        self.assertIn("2023Z", result)
        self.assertEqual(result["2023Z"]["COURSE123"], 5.0)
        self.assertEqual(result["2023Z"]["COURSE789"], 3.5)

        # Invalid ECTS should be converted to 0.0
        self.assertEqual(result["2023Z"]["COURSE456"], 0.0)
        self.assertEqual(result["2023Z"]["COURSE999"], 0.0)
        self.assertEqual(result["2023Z"]["COURSE000"], 0.0)

        # All courses should still be in result
        self.assertEqual(len(result["2023Z"]), 5)
