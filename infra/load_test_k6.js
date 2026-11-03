// infra/load_test_k6.js
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

// === Custom Metrics for Day 10 AgentOps ===
const searchLatencyTrend = new Trend('vector_search_latency_ms');
const errorRate = new Rate('error_rate');
const successfulQueries = new Counter('successful_search_queries');

// === Load Test Configuration & Concurrency Stages ===
export const options = {
    // Target URL from environment variable or default to localhost
    // Run with: k6 run -e TARGET_URL="https://your-cloud-run-url" infra/load_test_k6.js
    stages: [
        { duration: '15s', target: 5 },   // Ramp-up to 5 concurrent users
        { duration: '30s', target: 10 },  // Maintain 10 concurrent users (peak load)
        { duration: '15s', target: 0 },   // Ramp-down to 0 users
    ],
    thresholds: {
        // SLA criteria: 95% of requests must complete under 2.5s (BigQuery Vector Search)
        http_req_duration: ['p(95)<2500'],
        // Error rate must stay below 2%
        error_rate: ['rate<0.02'],
        http_req_failed: ['rate<0.02'],
    },
};

const BASE_URL = __ENV.TARGET_URL || 'http://localhost:8080';

// Rotating queries to simulate realistic user traffic and avoid client-side caching
const CLINICAL_PROMPTS = [
    'What are the inclusion criteria for adult oncology patients?',
    'What are the primary endpoints and overall response rates?',
    'List common exclusion criteria for patients with prior cardiac history.',
    'What is the dosing schedule and administration regimen?',
    'What adverse events or toxicity thresholds are documented in phase 2?',
];

export default function () {
    // 1. Pick a random query
    const query = CLINICAL_PROMPTS[Math.floor(Math.random() * CLINICAL_PROMPTS.length)];
    const sessionId = `k6-session-${__VU}`; // Unique session per virtual user

    const payload = JSON.stringify({
        query: query,
        top_k: 3,
        session_id: sessionId,
    });

    const params = {
        headers: {
            'Content-Type': 'application/json',
            'User-Agent': 'k6-load-tester/1.0',
        },
        timeout: '10s',
    };

    const startTime = new Date();
    const response = http.post(`${BASE_URL}/search`, payload, params);
    const latency = new Date() - startTime;

    // 2. Validate Response
    const success = check(response, {
        'status is 200': (r) => r.status === 200,
        'has results array': (r) => {
            try {
                const body = JSON.parse(r.body);
                return Array.isArray(body.results) && body.results.length > 0;
            } catch (e) {
                return false;
            }
        },
        'first hit has cosine_similarity': (r) => {
            try {
                const body = JSON.parse(r.body);
                return body.results[0] && typeof body.results[0].cosine_similarity === 'number';
            } catch (e) {
                return false;
            }
        },
    });

    // 3. Record Telemetry Metrics
    searchLatencyTrend.add(latency);
    if (success) {
        successfulQueries.add(1);
        errorRate.add(0);
    } else {
        errorRate.add(1);
    }

    // Pacing: Pause between 0.5s and 1.5s per virtual user
    sleep(Math.random() * 1.0 + 0.5);
}
