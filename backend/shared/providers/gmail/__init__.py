# backend/shared/providers/gmail/__init__.py
#
# Gmail provider wrapper over Google's official Gmail REST API (read, search,
# create drafts). There is deliberately no send code path: drafts are created
# only, by owner decision (2026-11-22).
# Provider code has no dependency on Mail skills or permission policy; callers
# supply short-lived access tokens after authorization.
# Spec: specifications/features/app-skills/mail-gmail/specification.yml
# contract-test-file: infrastructure
