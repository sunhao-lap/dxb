#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API 集成测试（对应设计说明书 §8.3），使用 FastAPI TestClient 验证
/api/* 全部接口的正常路径。

运行：python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from backend.main import app  # noqa: E402


class TestAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        # 先求解一次，供后续接口复用
        resp = cls.client.post("/api/solve", json={
            "instance_name": "ft06",
            "config": {"algorithm": "ga", "random_seed": 42},
        })
        assert resp.status_code == 200, resp.text
        cls.solve_data = resp.json()
        cls.schedule_id = cls.solve_data["schedule_id"]

    def test_01_list_instances(self):
        resp = self.client.get("/api/instances")
        self.assertEqual(resp.status_code, 200)
        names = [m["name"] for m in resp.json()]
        self.assertIn("ft06", names)
        self.assertIn("mk01", names)

    def test_02_solve(self):
        self.assertEqual(self.solve_data["algorithm"], "ga")
        self.assertLessEqual(self.solve_data["makespan"], 60)
        self.assertTrue(self.solve_data["history"])
        self.assertGreater(len(self.solve_data["schedule"]["items"]), 0)

    def test_03_get_schedule(self):
        resp = self.client.get(f"/api/schedule/{self.schedule_id}")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["schedule_id"], self.schedule_id)
        self.assertEqual(len(body["schedule"]["items"]), 36)

    def test_04_solve_unknown_instance_404(self):
        resp = self.client.post("/api/solve", json={
            "instance_name": "no_such", "config": {"algorithm": "ga"},
        })
        self.assertEqual(resp.status_code, 404)

    def test_05_invalid_algorithm_422(self):
        resp = self.client.post("/api/solve", json={
            "instance_name": "ft06", "config": {"algorithm": "xxx"},
        })
        self.assertEqual(resp.status_code, 422)

    def test_06_compare(self):
        resp = self.client.post("/api/compare", json={
            "schedule_ids": [self.schedule_id],
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body["schedules"]), 1)
        self.assertEqual(body["schedules"][0]["schedule_id"], self.schedule_id)

    def test_07_reschedule(self):
        resp = self.client.post("/api/reschedule", json={
            "schedule_id": self.schedule_id,
            "new_job": {
                "job_id": 6,
                "due_date": 100.0,
                "operations": [
                    {"eligible_machines": [0, 1], "processing_times": [3.0, 4.0]},
                    {"eligible_machines": [2, 3], "processing_times": [5.0, 6.0]},
                ],
            },
            "current_time": 10.0,
            "mode": "freeze",
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("diff", body)
        self.assertIn("summary", body["diff"])
        self.assertGreater(len(body["schedule"]["items"]), 36)  # 原 36 + 新 2

    def test_08_export_csv(self):
        resp = self.client.get(f"/api/export/{self.schedule_id}/csv")
        self.assertEqual(resp.status_code, 200)
        text = resp.text
        self.assertIn("job_id", text)
        self.assertIn("start_time", text)
        self.assertIn("duration", text)

    def test_09_export_png(self):
        resp = self.client.get(f"/api/export/{self.schedule_id}/png")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content[:8], b"\x89PNG\r\n\x1a\n")   # PNG 魔数

    def test_10_export_html(self):
        resp = self.client.get(f"/api/export/{self.schedule_id}/html")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("<html", resp.text.lower())
        self.assertIn("makespan", resp.text.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
