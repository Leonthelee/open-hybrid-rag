import unittest
from fastapi.testclient import TestClient

from src.main import app
from src.telemetry import MetricsCollector

class TestTelemetryAndMetrics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_metrics_collector_counter_and_gauge(self):
        collector = MetricsCollector()
        collector.inc_counter("test_counter", 1.0, method="GET", status="200")
        collector.inc_counter("test_counter", 2.0, method="GET", status="200")
        collector.set_gauge("test_gauge", 42.0)

        output = collector.export_prometheus()
        self.assertIn('test_counter{method="GET",status="200"} 3.0', output)
        self.assertIn('test_gauge 42.0', output)

    def test_metrics_collector_percentiles(self):
        collector = MetricsCollector()
        for d in [0.010, 0.020, 0.030, 0.040, 0.050, 0.060, 0.070, 0.080, 0.090, 0.100]:
            collector.observe_duration("query_latency", d)

        output = collector.export_prometheus()
        self.assertIn('query_latency_seconds{quantile="0.5"}', output)
        self.assertIn('query_latency_seconds{quantile="0.99"}', output)
        self.assertIn('query_latency_seconds_count 10', output)

    def test_prometheus_endpoint_http_response(self):
        self.client.get("/health")
        res = self.client.get("/metrics")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/plain", res.headers.get("content-type", ""))
        self.assertIn("open_hybrid_rag_build_info", res.text)
        self.assertIn("indexed_documents_total", res.text)
        self.assertIn("http_requests_total", res.text)

if __name__ == "__main__":
    unittest.main()
