// Scalar performance signals for Apple diagnostics: main-thread stalls from the
// display-link frame clock, one-minute frame and memory windows, and MetricKit
// hang, crash, launch and exit figures. Every value is a number or a fixed
// numeric code; call stacks, symbol names, binary paths and termination strings
// are never read, so nothing here can carry user data.
// No web source: the web app has no MetricKit or display-link equivalent.

// Specification: specifications/features/issue-reporting/specification.yml
// Assertions: issue-reporting.logs.native-performance-metadata

import Foundation
#if canImport(MetricKit)
import MetricKit
#endif

enum NativePerformanceSignals {
    /// A frame gap at or above this blocked the main thread long enough to feel stuck.
    static let stallThresholdMS = 250
    /// Gaps at or above this are suspensions (lock screen, app switcher), not stalls.
    static let suspensionThresholdMS = 10_000
    /// Most hang or crash events kept from one MetricKit payload.
    static let maxEventsPerPayload = 10

    /// Records a `main_thread_stall` warning for a frame gap that is a stall.
    static func recordFrameGap(durationMS: Int) {
        guard isStall(durationMS: durationMS) else { return }
        NativeDiagnostics.event("main_thread_stall", category: "performance", level: .warning,
                                counts: ["duration_ms": durationMS])
    }

    static func isStall(durationMS: Int) -> Bool {
        durationMS >= stallThresholdMS && durationMS < suspensionThresholdMS
    }

    /// The app's physical memory footprint (what iOS uses for memory limits), in MB.
    static func memoryFootprintMB() -> Int? {
        var info = task_vm_info_data_t()
        var count = mach_msg_type_number_t(MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<integer_t>.size)
        let status = withUnsafeMutablePointer(to: &info) { pointer in
            pointer.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), $0, &count)
            }
        }
        return status == KERN_SUCCESS ? Int(info.phys_footprint / 1_048_576) : nil
    }

    /// Counts for one finished frame window: frames, hitch frames, hitch rate
    /// per thousand frames, worst frame and memory.
    static func windowCounts(frames: Int, hitchFrames: Int, worstFrameMS: Int, memoryMB: Int?) -> [String: Int] {
        var counts = [
            "frames": frames,
            "hitch_frames": hitchFrames,
            "hitch_permille": frames > 0 ? hitchFrames * 1000 / frames : 0,
            "worst_frame_ms": worstFrameMS,
        ]
        if let memoryMB { counts["memory_mb"] = memoryMB }
        return counts
    }

    /// One MetricKit histogram bucket in milliseconds.
    struct Bucket: Equatable {
        let startMS: Int
        let endMS: Int
        let count: Int
    }

    /// Sample count, median bucket end and highest non-empty bucket end, under
    /// `prefix_` keys; empty when the histogram has no samples.
    static func histogramCounts(_ buckets: [Bucket], prefix: String) -> [String: Int] {
        let filled = buckets.filter { $0.count > 0 }.sorted { $0.startMS < $1.startMS }
        let total = filled.reduce(0) { $0 + $1.count }
        guard total > 0 else { return [:] }
        var running = 0
        var median = filled.last?.endMS ?? 0
        for bucket in filled {
            running += bucket.count
            if running * 2 >= total { median = bucket.endMS; break }
        }
        return [
            "\(prefix)_count": total,
            "\(prefix)_p50_ms": median,
            "\(prefix)_max_ms": filled.map(\.endMS).max() ?? 0,
        ]
    }

    /// Daily MetricKit metrics: launch, resume and hang histograms, peak memory
    /// and abnormal exits. Recorded at info level and returned for the issue context.
    @discardableResult
    static func recordMetricReport(launch: [Bucket], resume: [Bucket], hang: [Bucket],
                                   peakMemoryMB: Int?, exits: [String: Int]) -> [String: Int] {
        var counts = histogramCounts(launch, prefix: "launch")
        counts.merge(histogramCounts(resume, prefix: "resume")) { _, new in new }
        counts.merge(histogramCounts(hang, prefix: "hang")) { _, new in new }
        if let peakMemoryMB { counts["peak_memory_mb"] = peakMemoryMB }
        counts.merge(exits.filter { $0.value > 0 }) { _, new in new }
        NativeDiagnostics.event("metrickit_metrics", category: "performance", counts: counts)
        return counts
    }

    /// One crash as numeric Mach exception type and POSIX signal only.
    struct Crash: Equatable {
        let exceptionType: Int?
        let signal: Int?
    }

    /// MetricKit diagnostics: one warning per hang, crash and slow launch (at
    /// most `maxEventsPerPayload` each) plus a count summary that is returned.
    @discardableResult
    static func recordDiagnosticReport(hangDurationsMS: [Int], crashes: [Crash], launchDurationsMS: [Int],
                                       cpuExceptions: Int, diskWriteExceptions: Int) -> [String: Int] {
        for duration in hangDurationsMS.prefix(maxEventsPerPayload) {
            NativeDiagnostics.event("metrickit_hang", category: "performance", level: .warning,
                                    counts: ["duration_ms": duration])
        }
        for crash in crashes.prefix(maxEventsPerPayload) {
            var counts: [String: Int] = [:]
            if let type = crash.exceptionType { counts["exception_type"] = type }
            if let signal = crash.signal { counts["signal"] = signal }
            NativeDiagnostics.event("metrickit_crash", category: "performance", level: .error, counts: counts)
        }
        for duration in launchDurationsMS.prefix(maxEventsPerPayload) {
            NativeDiagnostics.event("metrickit_slow_launch", category: "performance", level: .warning,
                                    counts: ["duration_ms": duration])
        }
        let summary = [
            "hang_count": hangDurationsMS.count,
            "hang_max_ms": hangDurationsMS.max() ?? 0,
            "crash_count": crashes.count,
            "slow_launch_count": launchDurationsMS.count,
            "cpu_exception_count": cpuExceptions,
            "disk_write_exception_count": diskWriteExceptions,
        ]
        NativeDiagnostics.event("metrickit_diagnostics", category: "performance", level: .warning, counts: summary)
        return summary
    }
}

#if canImport(MetricKit)
extension NativePerformanceSignals {
    static func milliseconds(_ measurement: Measurement<UnitDuration>) -> Int {
        Int(measurement.converted(to: .milliseconds).value.rounded())
    }

    static func buckets(_ histogram: MXHistogram<UnitDuration>?) -> [Bucket] {
        guard let histogram else { return [] }
        return histogram.bucketEnumerator.allObjects.compactMap { item in
            guard let bucket = item as? MXHistogramBucket<UnitDuration> else { return nil }
            return Bucket(startMS: milliseconds(bucket.bucketStart), endMS: milliseconds(bucket.bucketEnd),
                          count: bucket.bucketCount)
        }
    }

    @discardableResult
    static func record(_ payload: MXMetricPayload) -> [String: Int] {
        var exits: [String: Int] = [:]
        #if os(iOS)
        if let foreground = payload.applicationExitMetrics?.foregroundExitData {
            exits["fg_abnormal_exits"] = foreground.cumulativeAbnormalExitCount
            exits["fg_watchdog_exits"] = foreground.cumulativeAppWatchdogExitCount
            exits["fg_memory_limit_exits"] = foreground.cumulativeMemoryResourceLimitExitCount
        }
        if let background = payload.applicationExitMetrics?.backgroundExitData {
            exits["bg_memory_limit_exits"] = background.cumulativeMemoryResourceLimitExitCount
            exits["bg_memory_pressure_exits"] = background.cumulativeMemoryPressureExitCount
            exits["bg_watchdog_exits"] = background.cumulativeAppWatchdogExitCount
        }
        #endif
        let peak = payload.memoryMetrics.map {
            Int($0.peakMemoryUsage.converted(to: .megabytes).value.rounded())
        }
        #if os(iOS)
        let resume = buckets(payload.applicationLaunchMetrics?.histogrammedApplicationResumeTime)
        #else
        let resume: [Bucket] = []
        #endif
        return recordMetricReport(
            launch: buckets(payload.applicationLaunchMetrics?.histogrammedTimeToFirstDraw),
            resume: resume,
            hang: buckets(payload.applicationResponsivenessMetrics?.histogrammedApplicationHangTime),
            peakMemoryMB: peak,
            exits: exits
        )
    }

    @discardableResult
    static func record(_ payload: MXDiagnosticPayload) -> [String: Int] {
        // Only numeric fields: callStackTree, terminationReason and
        // virtualMemoryRegionInfo hold symbols, paths and free text.
        let crashes = (payload.crashDiagnostics ?? []).map {
            Crash(exceptionType: $0.exceptionType?.intValue, signal: $0.signal?.intValue)
        }
        #if os(iOS)
        let launches = (payload.appLaunchDiagnostics ?? []).map { milliseconds($0.launchDuration) }
        #else
        let launches: [Int] = []
        #endif
        return recordDiagnosticReport(
            hangDurationsMS: (payload.hangDiagnostics ?? []).map { milliseconds($0.hangDuration) },
            crashes: crashes,
            launchDurationsMS: launches,
            cpuExceptions: payload.cpuExceptionDiagnostics?.count ?? 0,
            diskWriteExceptions: payload.diskWriteExceptionDiagnostics?.count ?? 0
        )
    }
}
#endif
