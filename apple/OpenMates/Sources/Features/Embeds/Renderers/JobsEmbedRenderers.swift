// JobsEmbedRenderers — native counterpart for jobs search and job result embeds.
// Renders the search preview/fullscreen grid and the job listing preview and
// detail views from the embed's decoded fields.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/jobs/JobsSearchEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/jobs/JobsSearchEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/jobs/JobsResultEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/jobs/JobsResultEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

// Native counterparts of the Jobs search and Jobs result embeds. The outer
// EmbedPreviewCard and fullscreen shell supply app chrome; this file renders only
// from the decoded embed payload (no fetching, decryption or sync logic).

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/jobs/JobsSearchEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/jobs/JobsSearchEmbedFullscreen.svelte
//          frontend/packages/ui/src/components/embeds/jobs/JobsResultEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/jobs/JobsResultEmbedFullscreen.svelte
// Data:    frontend/packages/ui/src/components/embeds/jobs/jobsEmbedData.ts
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity

import SwiftUI

// MARK: - Strings (web i18n keys, embeds.jobs.search.*)

extension AppStrings {
    private static func jobs(_ key: String, _ replacements: [String: String] = [:]) -> String {
        LocalizationManager.shared.text("embeds.jobs.search.\(key)", replacements: replacements)
    }

    static var jobsSearchTitle: String { LocalizationManager.shared.text("app_skills.jobs.search") }
    static func jobsResultCount(_ count: Int) -> String { jobs("result_count", ["count": String(count)]) }
    static var jobsPartialResults: String { jobs("partial_results") }
    static var jobsResultTitle: String { jobs("result.title") }
    static var jobsRemote: String { jobs("result.remote") }
    static var jobsPublished: String { jobs("result.published") }
    static func jobsSource(_ provider: String) -> String { jobs("result.source", ["provider": provider]) }
    static var jobsListingSource: String { jobs("result.listing") }
    static var jobsApply: String { jobs("result.apply") }
    static var jobsCompany: String { jobs("result.company") }
    static var jobsEmploymentType: String { jobs("result.employment_type") }
    static var jobsSalary: String { jobs("result.salary") }
    static var jobsDescription: String { jobs("result.description") }
    static var jobsSector: String { jobs("result.sector") }
    static var jobsRole: String { jobs("result.role") }
    static var jobsSeniority: String { jobs("result.seniority") }
    static var jobsOrganizationType: String { jobs("result.organization_type") }
    static var jobsWorkArrangement: String { jobs("result.work_arrangement") }
    static var jobsValidThrough: String { jobs("result.valid_through") }
    static var jobsImpact: String { jobs("result.impact") }
    static var jobsDetailsUnavailable: String { jobs("result.details_unavailable") }
    static var jobsLocation: String { LocalizationManager.shared.text("common.location") }
    static var jobsProcessing: String { LocalizationManager.shared.text("embeds.processing") }
    static var jobsCancelled: String { LocalizationManager.shared.text("embeds.cancelled") }
    static var jobsNoResults: String { LocalizationManager.shared.text("embeds.search_no_results") }
}

// MARK: - Model (mirrors jobsEmbedData.ts normalizeJob / jobSalary)

@MainActor
struct JobListingModel {
    let title: String?
    let company: String?
    let location: String?
    let url: URL?
    let applyURL: URL?
    let remote: Bool?
    let employmentType: String?
    let publishedAt: String?
    let validThrough: String?
    let description: String?
    let provider: String?
    let sector: String?
    let role: String?
    let seniority: String?
    let organizationType: String?
    let workArrangement: String?
    let impact: String?
    let detailStatus: String?
    let salary: String?

    init(data: [String: AnyCodable]) {
        func string(_ key: String) -> String? {
            let value = EmbedFieldReader.string(data, keys: [key])?.trimmingCharacters(in: .whitespacesAndNewlines)
            return value?.isEmpty == false ? value : nil
        }
        title = string("title")
        company = string("company")
        location = string("location")
        url = Self.secureURL(string("url"))
        applyURL = Self.secureURL(string("apply_url"))
        remote = data["remote"]?.value as? Bool
        employmentType = string("employment_type")
        publishedAt = string("published_at")
        validThrough = string("valid_through")
        description = string("description")
        provider = Self.providerLabel(string("provider"))
        sector = string("sector")
        role = string("role")
        seniority = string("seniority")
        organizationType = string("organization_type")
        workArrangement = string("work_arrangement")
        impact = string("impact")
        detailStatus = string("detail_status")

        let nested = (data["salary"]?.value as? [String: Any]).map { $0.mapValues(AnyCodable.init) } ?? [:]
        let minimum = EmbedFieldReader.double(data, keys: ["salary_min"]) ?? EmbedFieldReader.double(nested, keys: ["min"])
        let maximum = EmbedFieldReader.double(data, keys: ["salary_max"]) ?? EmbedFieldReader.double(nested, keys: ["max"])
        let currency = string("salary_currency") ?? EmbedFieldReader.string(nested, keys: ["currency"])
        let period = string("salary_period") ?? EmbedFieldReader.string(nested, keys: ["basis"])
        let label = string("salary_text") ?? (data["salary"]?.value as? String) ?? EmbedFieldReader.string(nested, keys: ["label"])
        salary = Self.salaryText(minimum: minimum, maximum: maximum, currency: currency, period: period, fallback: label)
    }

    var isRemoteLabel: String? {
        if let workArrangement { return workArrangement }
        return remote == true ? AppStrings.jobsRemote : nil
    }

    var subtitle: String {
        [company, location].compactMap { $0 }.joined(separator: " · ")
    }

    var publishedLabel: String? { Self.dateLabel(publishedAt) }
    var validThroughLabel: String? { Self.dateLabel(validThrough) }

    private static func secureURL(_ raw: String?) -> URL? {
        guard let raw, let url = URL(string: raw), url.scheme == "https",
              url.user == nil, url.password == nil else { return nil }
        return url
    }

    private static func providerLabel(_ value: String?) -> String? {
        guard let value else { return nil }
        return value.lowercased() == "jobtech" ? "JobTech" : value
    }

    private static func dateLabel(_ raw: String?) -> String? {
        guard let raw else { return nil }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let plain = ISO8601DateFormatter()
        let dayOnly = ISO8601DateFormatter()
        dayOnly.formatOptions = [.withFullDate]
        guard let date = formatter.date(from: raw) ?? plain.date(from: raw) ?? dayOnly.date(from: raw) else { return nil }
        return date.formatted(date: .abbreviated, time: .omitted)
    }

    private static func salaryText(minimum: Double?, maximum: Double?, currency: String?, period: String?, fallback: String?) -> String? {
        guard minimum != nil || maximum != nil else { return fallback }
        guard let currency else { return nil }
        func format(_ value: Double) -> String {
            value.formatted(.currency(code: currency).precision(.fractionLength(0)))
        }
        let amount: String
        if let minimum, let maximum {
            amount = minimum == maximum ? format(minimum) : "\(format(minimum))–\(format(maximum))"
        } else {
            amount = format((minimum ?? maximum) ?? 0)
        }
        return period.map { "\(amount) / \($0)" } ?? amount
    }
}

/// Parent search metadata (mirrors jobSearchScope / provider label in the web preview).
@MainActor
struct JobsSearchModel {
    let query: String
    let scope: String
    let providerLabel: String
    let count: Int
    let firstTitle: String?
    let firstCompany: String?
    let hasWarnings: Bool
    let error: String?
    let results: [EmbedRecord]

    init(embed: EmbedRecord, allEmbedRecords: [String: EmbedRecord]) {
        let raw = embed.rawData ?? [:]
        func pipeList(_ key: String) -> [String] {
            EmbedFieldReader.stringArray(raw, keys: [key]).flatMap {
                $0.split(separator: "|").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
            }
        }
        query = EmbedFieldReader.string(raw, keys: ["query"]) ?? AppStrings.jobsSearchTitle
        let countries = pipeList("countries").filter { $0 == "DE" || $0 == "SE" }
        let fallbackCountry = EmbedFieldReader.string(raw, keys: ["country"]).flatMap { $0.count == 2 ? [$0] : nil } ?? []
        var seen = Set<String>()
        let uniqueCountries = (countries.isEmpty ? fallbackCountry : countries).filter { seen.insert($0).inserted }
        scope = [EmbedFieldReader.string(raw, keys: ["location"]), uniqueCountries.isEmpty ? nil : uniqueCountries.joined(separator: ", ")]
            .compactMap { $0 }.joined(separator: " · ")

        let previews = EmbedFieldReader.dictionaryArray(raw, key: "preview_results")
        let previewModels = previews.map { JobListingModel(data: $0.mapValues(AnyCodable.init)) }
        var providerSeen = Set<String>()
        let providers = pipeList("providers").filter { providerSeen.insert($0).inserted }
        let selected = EmbedFieldReader.string(raw, keys: ["provider"])
        if !providers.isEmpty {
            providerLabel = providers.map { $0.lowercased() == "jobtech" ? "JobTech" : $0 }.joined(separator: ", ")
        } else if let selected, selected != "auto" {
            providerLabel = selected.lowercased() == "jobtech" ? "JobTech" : selected
        } else {
            providerLabel = previewModels.first?.provider ?? ""
        }
        firstTitle = previewModels.first?.title
        firstCompany = previewModels.first?.company
        hasWarnings = !(raw["warnings"]?.value as? [Any] ?? []).isEmpty
        error = EmbedFieldReader.string(raw, keys: ["error"])

        let inline = previews.enumerated().map { index, row in
            EmbedRecord(
                id: EmbedFieldReader.string(row.mapValues(AnyCodable.init), keys: ["embed_id", "id"])
                    ?? (embed.childEmbedIds.indices.contains(index) ? embed.childEmbedIds[index] : nil)
                    ?? "\(embed.id)-result-\(index)",
                type: EmbedType.jobsResult.rawValue,
                status: .finished,
                data: .raw(row.mapValues(AnyCodable.init)),
                parentEmbedId: embed.id,
                appId: "jobs",
                skillId: nil,
                embedIds: nil,
                createdAt: embed.createdAt
            )
        }
        let explicit = embed.childEmbedIds.compactMap { allEmbedRecords[$0] }
        let parented = allEmbedRecords.values
            .filter { $0.parentEmbedId == embed.id }
            .sorted { ($0.createdAt ?? $0.id) < ($1.createdAt ?? $1.id) }
        results = SearchSkillPreviewModel.mergedRecords(
            parentOrder: embed.childEmbedIds,
            inlineRecords: inline,
            hydratedRecords: explicit + parented
        )
        count = EmbedFieldReader.int(raw, keys: ["result_count"]) ?? results.count
    }
}

// MARK: - Search parent

struct JobsSearchEmbedRenderer: View {
    let embed: EmbedRecord
    let mode: EmbedDisplayMode
    let allEmbedRecords: [String: EmbedRecord]
    let onOpenEmbed: (EmbedRecord) -> Void

    private var model: JobsSearchModel { JobsSearchModel(embed: embed, allEmbedRecords: allEmbedRecords) }

    var body: some View {
        switch mode {
        case .preview: preview
        case .fullscreen: fullscreen
        }
    }

    private var preview: some View {
        let model = model
        return VStack(alignment: .leading, spacing: .spacing2) {
            Text(model.query)
                .font(.omP.weight(.semibold)).foregroundStyle(Color.fontPrimary)
                .lineLimit(3).fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("jobs-search-query")
            if !model.scope.isEmpty {
                Text(model.scope).font(.omSmall).foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("jobs-search-scope")
            }
            if !model.providerLabel.isEmpty {
                Text("\(AppStrings.via) \(model.providerLabel)")
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
            }
            switch embed.status {
            case .processing:
                stateText(AppStrings.jobsProcessing, isError: false)
            case .cancelled:
                stateText(AppStrings.jobsCancelled, isError: false)
            case .error:
                stateText(model.error ?? AppStrings.searchFailed, isError: true)
            default:
                if model.count == 0 {
                    stateText(AppStrings.jobsNoResults, isError: false)
                } else {
                    Text(AppStrings.jobsResultCount(model.count))
                        .font(.omSmall.weight(.semibold)).foregroundStyle(Color.fontPrimary)
                    if let title = model.firstTitle {
                        VStack(alignment: .leading, spacing: 0) {
                            Text(title).font(.omSmall.weight(.semibold)).foregroundStyle(Color.fontPrimary).lineLimit(1)
                            if let company = model.firstCompany {
                                Text(company).font(.omSmall).foregroundStyle(Color.fontSecondary).lineLimit(1)
                            }
                        }
                    }
                    if model.hasWarnings {
                        Text(AppStrings.jobsPartialResults).font(.omSmall).foregroundStyle(Color.warning)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .padding(.top, .spacing4)
        .accessibilityIdentifier("jobs-search-preview")
    }

    private func stateText(_ text: String, isError: Bool) -> some View {
        Text(text).font(.omSmall).foregroundStyle(isError ? Color.error : Color.fontSecondary)
    }

    @ViewBuilder private var fullscreen: some View {
        let model = model
        if embed.status == .finished {
            if model.results.isEmpty {
                Text(AppStrings.jobsNoResults)
                    .font(.omP).foregroundStyle(Color.fontSecondary)
                    .frame(maxWidth: .infinity)
                    .padding(.spacing10)
                    .accessibilityIdentifier("jobs-search-empty")
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 280, maximum: 320), spacing: .spacing8)], spacing: .spacing8) {
                    ForEach(model.results) { child in
                        EmbedPreviewCard(embed: child, allEmbedRecords: allEmbedRecords, variant: .compact) {
                            onOpenEmbed(child)
                        }
                        .environment(\.embedPreviewFillsGridCell, true)
                        .accessibilityIdentifier("embed-preview-\(child.id)")
                    }
                }
                .frame(maxWidth: .infinity, alignment: .topLeading)
                .accessibilityIdentifier("jobs-search-fullscreen")
            }
        } else {
            let text = embed.status == .processing ? AppStrings.jobsProcessing
                : embed.status == .cancelled ? AppStrings.jobsCancelled
                : (model.error ?? AppStrings.searchFailed)
            Text(text)
                .font(.omP).foregroundStyle(Color.fontSecondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 700)
                .padding(.spacing10)
                .frame(maxWidth: .infinity)
                .accessibilityIdentifier("jobs-search-state")
        }
    }
}

// MARK: - Result

struct JobsResultEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var job: JobListingModel { JobListingModel(data: data ?? [:]) }

    var body: some View {
        switch mode {
        case .preview: preview
        case .fullscreen: fullscreen
        }
    }

    private var preview: some View {
        let job = job
        return VStack(alignment: .leading, spacing: .spacing2) {
            Text(job.title ?? AppStrings.jobsResultTitle)
                .font(.omP.weight(.semibold)).foregroundStyle(Color.fontPrimary)
                .lineLimit(2).fixedSize(horizontal: false, vertical: true)
            if !job.subtitle.isEmpty {
                Text(job.subtitle).font(.omSmall).foregroundStyle(Color.fontSecondary).lineLimit(1)
            }
            if let description = job.description {
                Text(description).font(.omSmall).foregroundStyle(Color.fontSecondary).lineLimit(3)
            }
            HStack(spacing: .spacing3) {
                if let salary = job.salary {
                    JobFactPill(salary).accessibilityIdentifier("jobs-salary")
                }
                if let remote = job.isRemoteLabel {
                    JobFactPill(remote).accessibilityIdentifier("jobs-remote-badge")
                }
                if let published = job.publishedLabel {
                    JobFactPill(published)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .padding(.spacing6)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("jobs-result-card")
    }

    private var fullscreen: some View {
        let job = job
        return VStack(alignment: .leading, spacing: .spacing6) {
            Text(job.title ?? AppStrings.jobsResultTitle)
                .font(.omH2.weight(.semibold)).foregroundStyle(Color.fontPrimary)
            if !job.subtitle.isEmpty {
                Text([job.subtitle, job.provider].compactMap { $0 }.joined(separator: " · "))
                    .font(.omP).foregroundStyle(Color.fontSecondary)
            }
            if let applyURL = job.applyURL {
                Link(AppStrings.jobsApply, destination: applyURL)
                    .font(.omP.weight(.semibold)).foregroundStyle(Color.buttonPrimary)
                    .accessibilityIdentifier("jobs-apply-link")
            }
            if let url = job.url, url != job.applyURL {
                Link(AppStrings.jobsSource(job.provider ?? AppStrings.jobsListingSource), destination: url)
                    .font(.omP.weight(.semibold)).foregroundStyle(Color.buttonPrimary)
                    .accessibilityIdentifier("jobs-source-link")
            }
            VStack(alignment: .leading, spacing: .spacing3) {
                fact(AppStrings.jobsSalary, job.salary, id: "jobs-salary")
                fact(AppStrings.jobsEmploymentType, job.employmentType?.replacingOccurrences(of: "_", with: " "))
                fact(AppStrings.jobsCompany, job.company, id: "jobs-company-value")
                fact(AppStrings.jobsLocation, job.location)
                fact(AppStrings.jobsSector, job.sector, id: "jobs-sector-value")
                fact(AppStrings.jobsRole, job.role, id: "jobs-role-value")
                fact(AppStrings.jobsSeniority, job.seniority, id: "jobs-seniority-value")
                fact(AppStrings.jobsOrganizationType, job.organizationType, id: "jobs-organization-type-value")
                fact(AppStrings.jobsPublished, job.publishedLabel)
                fact(AppStrings.jobsValidThrough, job.validThroughLabel)
                fact(AppStrings.jobsWorkArrangement, job.isRemoteLabel,
                     id: job.remote == true ? "jobs-remote-badge" : "jobs-work-arrangement")
            }
            if let impact = job.impact {
                section(AppStrings.jobsImpact, impact, id: "jobs-impact")
            }
            if let description = job.description {
                section(AppStrings.jobsDescription, description, id: "jobs-description")
            }
            if job.detailStatus == "summary" {
                Text(AppStrings.jobsDetailsUnavailable)
                    .font(.omP).foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("jobs-details-warning")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.spacing6)
        .accessibilityIdentifier("jobs-detail-body")
    }

    @ViewBuilder
    private func fact(_ label: String, _ value: String?, id: String? = nil) -> some View {
        if let value {
            HStack(alignment: .firstTextBaseline, spacing: .spacing4) {
                Text(label).font(.omSmall).foregroundStyle(Color.fontSecondary)
                Text(value).font(.omP).foregroundStyle(Color.fontPrimary)
            }
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier(id ?? "jobs-fact-\(label)")
        }
    }

    private func section(_ title: String, _ body: String, id: String) -> some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Text(title).font(.omP.weight(.semibold)).foregroundStyle(Color.fontPrimary)
            Text(body).font(.omP).foregroundStyle(Color.fontPrimary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.top, .spacing4)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(id)
    }
}

private struct JobFactPill: View {
    let label: String
    init(_ label: String) { self.label = label }

    var body: some View {
        Text(label)
            .font(.omXs.weight(.semibold)).foregroundStyle(Color.fontSecondary)
            .lineLimit(1)
            .padding(.horizontal, .spacing4).padding(.vertical, .spacing2)
            .background(Color.grey10, in: Capsule())
    }
}
