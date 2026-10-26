//! Experimental benchmark policy only; does not activate product settings.
//!
//! `total_bytes` is usable system RAM, optionally capped by cgroup memory.max.
//! Nominal 4/8/16 GiB tiers tolerate at most 12.5% kernel-reserved RAM:
//! thresholds are 3.5/7/14 GiB. Intermediate machines retain the lower known
//! budget, and effective RAM <= 2 GiB always disables enhanced scanning.
//! At most one quarter of available RAM is eligible, leaving >=75% untouched.
//! Worker estimates are conservative benchmark estimates, not enforced limits.
//! Resource eligibility alone never proves the 2500 ms full-scan target.

use std::env;
use std::process;

pub const MIB: u64 = 1024 * 1024;
pub const GIB: u64 = 1024 * MIB;
pub const LATENCY_BUDGET_MS: u64 = 2500;
const BASE_BYTES: u64 = 96 * MIB;
const WORKER_BYTES: u64 = 48 * MIB;
const MAX_WORKERS: u32 = 8;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ResourcePolicy {
    pub enabled: bool,
    pub budget_bytes: u64,
    pub workers: u32,
    pub threads: u32,
    pub reason: &'static str,
}

fn disabled(budget_bytes: u64, reason: &'static str) -> ResourcePolicy {
    ResourcePolicy { enabled: false, budget_bytes, workers: 0, threads: 0, reason }
}

/// Predictive allocation for an isolated native benchmark. No file-size gate.
/// A cgroup cap applies to total and available because host meminfo can exceed
/// container memory. Available values above effective total are clamped.
/// With a cgroup cap, remaining cgroup headroom is required; an unknown value
/// fails closed. Eligibility uses min(host available, effective total, cgroup
/// remaining) / 4. A platform adapter must supply current remaining bytes
/// (cap minus usage, accounting for its applicable hierarchy), not the cap.
pub fn resource_policy(total_bytes: u64, available_bytes: u64, cpus: u32,
                       cgroup_cap_bytes: Option<u64>,
                       cgroup_remaining_bytes: Option<u64>) -> Result<ResourcePolicy, &'static str> {
    if total_bytes == 0 || cpus == 0 {
        return Err("total bytes and CPU count must be positive");
    }
    if cgroup_cap_bytes == Some(0) {
        return Err("cgroup cap must be positive");
    }
    let total = cgroup_cap_bytes.map_or(total_bytes, |cap| total_bytes.min(cap));
    if total <= 2 * GIB {
        return Ok(disabled(0, "effective_ram_at_most_2gib_regex_only"));
    }
    // All arithmetic uses bounded constants; no multiplication of input values.
    let tier_budget = if total >= 14 * GIB { 1536 * MIB }
                      else if total >= 7 * GIB { 800 * MIB }
                      else if total >= 7 * GIB / 2 { 300 * MIB }
                      else { 0 };
    if tier_budget == 0 {
        return Ok(disabled(0, "below_reserved_4gib_tier_regex_only"));
    }
    if cgroup_cap_bytes.is_some() && cgroup_remaining_bytes.is_none() {
        return Ok(disabled(0, "cgroup_remaining_unknown_regex_only"));
    }
    let available = available_bytes.min(total)
        .min(cgroup_remaining_bytes.unwrap_or(u64::MAX));
    let budget = tier_budget.min(available / 4);
    let capacity = budget.saturating_sub(BASE_BYTES) / WORKER_BYTES;
    if capacity == 0 || budget < BASE_BYTES + WORKER_BYTES {
        return Ok(disabled(budget, "available_memory_headroom_regex_only"));
    }
    // One CPU remains usable: a one-CPU host can run one single-thread worker.
    // Otherwise use at most half the CPU count for independent sessions.
    let workers = capacity.min(u64::from(MAX_WORKERS))
        .min(u64::from((cpus / 2).max(1))) as u32;
    let threads = (cpus / workers).min(2);
    Ok(ResourcePolicy { enabled: true, budget_bytes: budget, workers, threads,
        reason: "resource_eligible_latency_not_validated" })
}

/// A calibration must predict the *entire file* scan, not an individual chunk.
/// Unknown or slow estimates retain regex scanning. An explicit full-scan
/// benchmark override bypasses only latency, never memory/CPU restrictions.
pub fn latency_policy(resources: ResourcePolicy, calibrated_prediction_ms: Option<u64>,
                      explicit_full_scan: bool) -> ResourcePolicy {
    if !resources.enabled { return resources; }
    if explicit_full_scan {
        return ResourcePolicy { reason: "explicit_full_scan_latency_override", ..resources };
    }
    match calibrated_prediction_ms {
        Some(ms) if ms <= LATENCY_BUDGET_MS => ResourcePolicy {
            reason: "calibrated_full_scan_prediction_within_2500ms", ..resources },
        Some(_) => disabled(resources.budget_bytes, "prediction_exceeds_2500ms_regex_only"),
        None => disabled(resources.budget_bytes, "no_full_scan_calibration_regex_only"),
    }
}

#[derive(Default)]
struct Args {
    total: Option<u64>, available: Option<u64>, cpus: Option<u32>,
    cgroup: Option<u64>, cgroup_remaining: Option<u64>, predicted_ms: Option<u64>, full_scan: bool,
    latency_gate: bool,
}

fn parse_args(values: impl IntoIterator<Item=String>) -> Result<Args, &'static str> {
    let mut args = Args::default();
    let mut values = values.into_iter();
    while let Some(flag) = values.next() {
        if flag == "--full-scan" {
            if args.full_scan { return Err("duplicate full-scan flag"); }
            args.full_scan = true;
            args.latency_gate = true;
            continue;
        }
        if flag == "--latency-gate" {
            args.latency_gate = true;
            continue;
        }
        if !matches!(flag.as_str(), "--total-bytes" | "--available-bytes" | "--cpus"
                     | "--cgroup-cap-bytes" | "--cgroup-remaining-bytes" | "--predicted-ms") {
            return Err("unknown option");
        }
        let value = values.next().ok_or("option requires an unsigned integer")?
            .parse::<u64>().map_err(|_| "invalid or overflowing unsigned integer")?;
        match flag.as_str() {
            "--total-bytes" => {
                if args.total.replace(value).is_some() { return Err("duplicate total-bytes"); }
            }
            "--available-bytes" => {
                if args.available.replace(value).is_some() { return Err("duplicate available-bytes"); }
            }
            "--cpus" => {
                let cpus = u32::try_from(value).map_err(|_| "CPU count overflow")?;
                if args.cpus.replace(cpus).is_some() { return Err("duplicate cpus"); }
            }
            "--cgroup-cap-bytes" => {
                if args.cgroup.replace(value).is_some() { return Err("duplicate cgroup cap"); }
            }
            "--cgroup-remaining-bytes" => {
                if args.cgroup_remaining.replace(value).is_some() {
                    return Err("duplicate cgroup remaining bytes");
                }
            }
            "--predicted-ms" => {
                if args.predicted_ms.replace(value).is_some() { return Err("duplicate prediction"); }
                args.latency_gate = true;
            }
            _ => return Err("unknown option"),
        }
    }
    Ok(args)
}

fn run() -> Result<(), &'static str> {
    let args = parse_args(env::args().skip(1))?;
    let mut policy = resource_policy(args.total.ok_or("--total-bytes required")?,
        args.available.ok_or("--available-bytes required")?,
        args.cpus.ok_or("--cpus required")?, args.cgroup, args.cgroup_remaining)?;
    if args.latency_gate {
        policy = latency_policy(policy, args.predicted_ms, args.full_scan);
    }
    println!("{{\"enabled\":{},\"budget_bytes\":{},\"workers\":{},\"threads\":{},\"reason\":\"{}\"}}",
        policy.enabled, policy.budget_bytes, policy.workers, policy.threads, policy.reason);
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        // Static error strings contain no user input or private document text.
        eprintln!("{{\"error\":\"{}\"}}", error);
        process::exit(2);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    #[test]
    fn nominal_tiers_and_worker_estimates_respect_memory_and_cpu() {
        for (ram, budget, cpus, workers) in [(2, 0, 8, 0), (4, 300, 8, 4),
                                           (8, 800, 16, 8), (16, 1536, 16, 8)] {
            let p = resource_policy(ram * GIB, ram * GIB, cpus, None, None).unwrap();
            assert_eq!(p.budget_bytes, budget * MIB);
            assert_eq!(p.workers, workers);
            assert_eq!(p.enabled, workers > 0);
            if p.enabled {
                assert!(BASE_BYTES + u64::from(p.workers) * WORKER_BYTES <= p.budget_bytes);
                assert!(p.workers * p.threads <= cpus);
            }
        }
    }

    // contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    #[test]
    fn kernel_reservations_and_intermediate_tiers_are_conservative() {
        assert_eq!(resource_policy(15 * GIB / 2, 6 * GIB, 8, None, None).unwrap().budget_bytes, 800 * MIB);
        assert_eq!(resource_policy(7 * GIB - 1, 6 * GIB, 8, None, None).unwrap().budget_bytes, 300 * MIB);
        assert!(!resource_policy(7 * GIB / 2 - 1, 3 * GIB, 8, None, None).unwrap().enabled);
        assert_eq!(resource_policy(14 * GIB, 12 * GIB, 16, None, None).unwrap().budget_bytes, 1536 * MIB);
        assert!(!resource_policy(2 * GIB, 2 * GIB, 8, None, None).unwrap().enabled);
    }

    // contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    #[test]
    fn busy_memory_cgroup_and_cpu_caps() {
        let busy = resource_policy(4 * GIB, 400 * MIB, 8, None, None).unwrap();
        assert!(!busy.enabled);
        assert_eq!(busy.budget_bytes, 100 * MIB);
        let one = resource_policy(4 * GIB, 600 * MIB, 8, None, None).unwrap();
        assert_eq!((one.budget_bytes, one.workers, one.threads), (150 * MIB, 1, 2));
        assert!(!resource_policy(16 * GIB, 12 * GIB, 16, Some(2 * GIB), None).unwrap().enabled);
        let busy_cgroup = resource_policy(16 * GIB, 10 * GIB, 8,
            Some(4 * GIB), Some(200 * MIB)).unwrap();
        assert!(!busy_cgroup.enabled);
        assert_eq!(busy_cgroup.budget_bytes, 50 * MIB);
        let unknown_cgroup = resource_policy(16 * GIB, 10 * GIB, 8,
            Some(4 * GIB), None).unwrap();
        assert!(!unknown_cgroup.enabled);
        assert_eq!(unknown_cgroup.reason, "cgroup_remaining_unknown_regex_only");
        let free_cgroup = resource_policy(16 * GIB, 10 * GIB, 8,
            Some(4 * GIB), Some(3 * GIB)).unwrap();
        assert_eq!((free_cgroup.budget_bytes, free_cgroup.workers), (300 * MIB, 4));
        for cpus in 1..=32 {
            let p = resource_policy(16 * GIB, 16 * GIB, cpus, None, None).unwrap();
            assert!(p.workers <= (cpus / 2).max(1));
            assert!(p.workers <= 8 && p.threads <= 2 && p.workers * p.threads <= cpus);
        }
    }

    // contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    #[test]
    fn checked_inputs_and_extreme_values() {
        assert!(resource_policy(0, 0, 1, None, None).is_err());
        assert!(resource_policy(GIB, GIB, 0, None, None).is_err());
        assert!(resource_policy(GIB, GIB, 1, Some(0), None).is_err());
        let p = resource_policy(u64::MAX, u64::MAX, u32::MAX, None, None).unwrap();
        assert_eq!((p.budget_bytes, p.workers, p.threads), (1536 * MIB, 8, 2));
        for text in ["18446744073709551616", "-1", "junk"] {
            assert!(parse_args(["--total-bytes".into(), text.into()]).is_err());
        }
        assert!(parse_args(["--cpus".into(), "4294967296".into()]).is_err());
        assert!(parse_args(["--cpus".into()]).is_err());
        assert!(parse_args(["--unknown".into()]).is_err());
    }

    // contract-test: supporting surface=cli assertions=pii.surface.semantic-parity
    #[test]
    fn full_file_latency_gate_requires_calibration_or_explicit_override() {
        let p = resource_policy(8 * GIB, 8 * GIB, 8, None, None).unwrap();
        assert!(!latency_policy(p, None, false).enabled);
        assert!(latency_policy(p, Some(2500), false).enabled);
        assert!(!latency_policy(p, Some(2501), false).enabled);
        assert!(!latency_policy(p, Some(u64::MAX), false).enabled);
        assert!(latency_policy(p, None, true).enabled);
        let off = resource_policy(2 * GIB, 2 * GIB, 8, None, None).unwrap();
        assert!(!latency_policy(off, Some(1), true).enabled);
    }
}
