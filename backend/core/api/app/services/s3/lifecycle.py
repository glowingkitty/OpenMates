"""Lifecycle policy management for S3 buckets.

Rules are grouped by physical bucket so logical surfaces that share a bucket do
not overwrite each other's retention. Prefix-specific compliance retention is
defined in config.py and reconciled in one deterministic update.
"""
import logging
import re
from collections import defaultdict
from typing import Dict

from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
MANAGED_RULE_ID_PREFIX = 'OpenMates-'
LEGACY_MANAGED_RULE_ID = re.compile(r'^ExpireAfter\d+Days$')


def build_lifecycle_rules(bucket_configs: Dict[str, Dict]) -> list[dict]:
    """Build deterministic lifecycle rules for logical configs in one bucket."""
    rules = []
    for bucket_key, bucket_config in sorted(bucket_configs.items()):
        lifecycle_days = bucket_config.get('lifecycle_policy')
        if not isinstance(lifecycle_days, int) or lifecycle_days <= 0:
            continue
        prefix = bucket_config.get('lifecycle_prefix', '')
        label = ''.join(part.capitalize() for part in bucket_key.replace('_logs', '').split('_'))
        rules.append({
            'ID': f'{MANAGED_RULE_ID_PREFIX}Expire{label}After{lifecycle_days}Days',
            'Status': 'Enabled',
            'Filter': {'Prefix': prefix},
            'Expiration': {'Days': lifecycle_days},
        })
    return sorted(rules, key=lambda rule: (rule['Filter']['Prefix'], rule['ID']))


def apply_lifecycle_policies(s3_client, bucket_configs: Dict[str, Dict], environment: str = 'production'):
    """Apply grouped lifecycle policies while preserving unmanaged rules."""
    try:
        grouped_configs = defaultdict(dict)
        name_field = 'dev_name' if environment == 'development' else 'name'
        for bucket_key, bucket_config in bucket_configs.items():
            grouped_configs[bucket_config[name_field]][bucket_key] = bucket_config

        for bucket_name, logical_configs in sorted(grouped_configs.items()):
            rules = build_lifecycle_rules(logical_configs)
            if not rules:
                continue
            try:
                unmanaged_rules = _get_unmanaged_lifecycle_rules(s3_client, bucket_name)
                combined_rules = unmanaged_rules + rules
                logger.info(
                    "Applying %s managed lifecycle rule(s) while preserving %s unmanaged rule(s)",
                    len(rules),
                    len(unmanaged_rules),
                )
                s3_client.put_bucket_lifecycle_configuration(
                    Bucket=bucket_name,
                    LifecycleConfiguration={'Rules': combined_rules},
                )
                logger.info("Successfully applied lifecycle policy")
            except ClientError as e:
                error_code = e.response['Error']['Code']
                logger.warning("Failed to apply lifecycle policy: error_code=%s", error_code)
            except Exception as e:
                logger.error("Error applying lifecycle policy: error_class=%s", type(e).__name__)
    except Exception as e:
        logger.error("Error applying lifecycle policies: error_class=%s", type(e).__name__)


def _get_unmanaged_lifecycle_rules(s3_client, bucket_name: str) -> list[dict]:
    """Read existing rules and retain everything not owned by OpenMates."""
    try:
        response = s3_client.get_bucket_lifecycle_configuration(Bucket=bucket_name)
    except ClientError as exc:
        error_code = str(exc.response.get('Error', {}).get('Code', ''))
        if error_code in {'404', 'NoSuchLifecycleConfiguration'}:
            return []
        raise
    rules = response.get('Rules', [])
    return [
        rule
        for rule in rules
        if not str(rule.get('ID', '')).startswith(MANAGED_RULE_ID_PREFIX)
        and not LEGACY_MANAGED_RULE_ID.fullmatch(str(rule.get('ID', '')))
    ]
