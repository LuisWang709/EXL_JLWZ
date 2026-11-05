"""Human review queue: H1, H2 and manual-review items.

Owner: A1. Endpoints (see openapi.yaml for request/response schemas):
    GET  /api/v1/reviews?status=pending                 200
    GET  /api/v1/reviews/{review_id}                    200
    POST /api/v1/reviews/{review_id}/decision           200  approve | reject | edit -> resumes pipeline
"""

from fastapi import APIRouter

router = APIRouter(prefix="/reviews", tags=["reviews"])
