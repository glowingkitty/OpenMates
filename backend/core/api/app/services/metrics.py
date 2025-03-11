import time
from prometheus_client import Counter, Histogram, Gauge, Summary
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

class MetricsService:
    """
    Service for tracking application metrics via Prometheus
    """
    def __init__(self):
        """Initialize all metric collectors"""
        # Authentication metrics
        self.invite_code_check_total = Counter(
            'invite_code_check_total', 
            'Total number of invite code checks',
            ['status']  # 'valid', 'invalid'
        )
        
        # TODO: Implement the following metrics:
        # self.login_attempts = Counter('login_attempts', 'Login attempts', ['status'])
        # self.logout_total = Counter('logout_total', 'Logout events')
        # self.signup_total = Counter('signup_total', 'New user signups')
        
        # API usage metrics
        self.api_requests = Counter(
            'api_requests_total', 
            'Total API requests',
            ['method', 'endpoint', 'status_code']
        )
        
        self.api_request_duration = Histogram(
            'api_request_duration_seconds',
            'API request duration in seconds',
            ['method', 'endpoint'],
            buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
        )
        
        self.api_rate_limit_hits = Counter(
            'api_rate_limit_hits_total',
            'Total number of rate limit hits',
            ['endpoint']
        )
        
        # TODO: Track these metrics as discussed:
        # - App skills used
        # - User metrics (active users, 2FA adoption)
        # - Chat metrics (new chats, messages, average length)
        # - System metrics (to be collected via node_exporter)
        # - Payment/income metrics
        
        logger.info("Metrics service initialized")
    
    def track_invite_code_check(self, is_valid: bool):
        """Track an invite code check with its result"""
        status = "valid" if is_valid else "invalid"
        self.invite_code_check_total.labels(status=status).inc()
        
    def track_api_request(self, method: str, endpoint: str, status_code: int):
        """Track an API request with method, endpoint, and status code"""
        self.api_requests.labels(
            method=method,
            endpoint=endpoint,
            status_code=status_code
        ).inc()
    
    def track_request_duration(self, method: str, endpoint: str, duration: float):
        """Track API request duration"""
        self.api_request_duration.labels(
            method=method,
            endpoint=endpoint
        ).observe(duration)
    
    def track_rate_limit_hit(self, endpoint: str):
        """Track when a rate limit is hit"""
        self.api_rate_limit_hits.labels(endpoint=endpoint).inc()
