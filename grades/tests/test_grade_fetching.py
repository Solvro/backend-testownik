from unittest.mock import AsyncMock

from django.test import TestCase

from grades.views import get_user_courses_ects_safe


class GetUserCoursesEctsSafeTestCase(TestCase):
    """Test the safe ECTS wrapper function that fixes the None ECTS bug"""

    async def test_filters_none_values(self):
        """
        Test that None values are filtered out.

        This is the main bug fix - USOS API returns None for courses without
        assigned ECTS points, which caused: TypeError: float() argument must
        be a string or a real number, not 'NoneType'
        """
        mock_client = AsyncMock()
        mock_client.request.return_value = {
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

        # Verify that None values were filtered out
        self.assertIn("2023Z", result)
        self.assertEqual(result["2023Z"]["COURSE123"], 5.0)
        self.assertEqual(result["2023Z"]["COURSE789"], 3.5)
        self.assertNotIn("COURSE456", result["2023Z"])  # None should be filtered

        self.assertIn("2024L", result)
        self.assertEqual(result["2024L"]["COURSE888"], 6.0)
        self.assertNotIn("COURSE999", result["2024L"])  # None should be filtered

        # Verify correct API endpoint was called
        mock_client.request.assert_called_once_with("services/courses/user_ects_points", {})

    async def test_handles_term_with_all_none_values(self):
        """Test that terms with all None ECTS values are excluded from result"""
        mock_client = AsyncMock()
        mock_client.request.return_value = {
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

        # Term with all None values should not be in result
        self.assertNotIn("2024L", result)

    async def test_handles_empty_response(self):
        """Test that empty API response is handled correctly"""
        mock_client = AsyncMock()
        mock_client.request.return_value = {}

        result = await get_user_courses_ects_safe(mock_client)

        self.assertEqual(result, {})
        self.assertIsInstance(result, dict)

    async def test_converts_string_ects_to_float(self):
        """Test that string ECTS values are properly converted to float"""
        mock_client = AsyncMock()
        mock_client.request.return_value = {
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
        mock_client.request.return_value = {
            "2023Z": {
                "MAT101": "5.0",
                "FIZ201": None,  # Course without ECTS assigned
                "INF301": "4.0",
                "CHE102": None,  # Another course without ECTS
                "ENG401": "3.0",
            },
        }

        result = await get_user_courses_ects_safe(mock_client)

        # Should only contain courses with valid ECTS
        self.assertEqual(len(result["2023Z"]), 3)
        self.assertIn("MAT101", result["2023Z"])
        self.assertIn("INF301", result["2023Z"])
        self.assertIn("ENG401", result["2023Z"])

        # Courses with None should be filtered out
        self.assertNotIn("FIZ201", result["2023Z"])
        self.assertNotIn("CHE102", result["2023Z"])
