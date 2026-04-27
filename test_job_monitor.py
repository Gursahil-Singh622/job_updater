import tempfile
import unittest
from pathlib import Path

import job_monitor


class JobMonitorTests(unittest.TestCase):
    def test_extract_links_filters_and_normalizes_urls(self):
        site = job_monitor.SiteConfig(
            name="Test",
            urls=["https://example.com/careers"],
            include_patterns=["job"],
            exclude_patterns=["privacy"],
        )
        html = """
        <a href="/jobs/123#apply">Summer Intern</a>
        <a href="/privacy">Privacy</a>
        <a href="/about">About</a>
        """

        links = job_monitor.extract_links(site, "https://example.com/careers", html)

        self.assertEqual(
            links,
            [{"title": "Summer Intern", "url": "https://example.com/jobs/123"}],
        )

    def test_find_matches_checks_title_and_url_case_insensitively(self):
        site = job_monitor.SiteConfig("Test", ["https://example.com"], [], [])
        links = [
            {"title": "Finance Role", "url": "https://example.com/jobs/analyst-1"},
            {"title": "Seasonal Associate", "url": "https://example.com/jobs/2"},
            {"title": "Engineer", "url": "https://example.com/jobs/3"},
        ]

        matches = job_monitor.find_matches(site, links, ["analyst", "seasonal"])

        self.assertEqual([match.title for match in matches], ["Finance Role", "Seasonal Associate"])
        self.assertEqual(matches[0].matched_keywords, ["analyst"])
        self.assertEqual(matches[1].matched_keywords, ["seasonal"])

    def test_build_site_urls_supports_url_list_and_pagination(self):
        site = {
            "url": "https://example.com/jobs",
            "urls": ["https://example.com/jobs?department=finance"],
            "pagination": {
                "url_template": "https://example.com/jobs?page={page}",
                "start": 2,
                "end": 4,
            },
        }

        urls = job_monitor.build_site_urls(site)

        self.assertEqual(
            urls,
            [
                "https://example.com/jobs",
                "https://example.com/jobs?department=finance",
                "https://example.com/jobs?page=2",
                "https://example.com/jobs?page=3",
                "https://example.com/jobs?page=4",
            ],
        )

    def test_seen_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "seen_jobs.json"

            job_monitor.save_seen(path, {"abc", "def"})

            self.assertEqual(job_monitor.load_seen(path), {"abc", "def"})


if __name__ == "__main__":
    unittest.main()
