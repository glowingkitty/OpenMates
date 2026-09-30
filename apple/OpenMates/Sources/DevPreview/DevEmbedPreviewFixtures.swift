// Debug fixtures for native embed preview galleries.
// Mirrors the deployed Svelte /dev/preview/embeds app showcase sections so
// Xcode simulator screenshots can be compared against app.dev.openmates.org.
// This file is compiled in Debug builds only.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/apps/web_app/src/routes/dev/preview/embeds/[app]/+page.svelte
//          frontend/packages/ui/src/components/embeds/web/*.preview.ts
//          frontend/packages/ui/src/components/embeds/images/*.preview.ts
//          frontend/packages/ui/src/components/embeds/travel/*.preview.ts
//          frontend/packages/ui/src/components/embeds/events/*.preview.ts
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

#if DEBUG
import Foundation

enum DevEmbedPreviewApp: String, CaseIterable, Identifiable {
    case audio
    case business
    case calendar
    case code
    case design
    case diagrams
    case docs
    case electronics
    case fitness
    case finance
    case health
    case home
    case web
    case images
    case mail
    case maps
    case math
    case mindmaps
    case models3d
    case music
    case news
    case nutrition
    case pdf
    case reminder
    case sheets
    case shopping
    case socialMedia = "social_media"
    case tasks
    case travel
    case videos
    case weather
    case events
    case workflows

    var id: String { rawValue }

    var title: String {
        switch self {
        case .audio: return "Audio"
        case .business: return "Business"
        case .calendar: return "Calendar"
        case .code: return "Code"
        case .design: return "Design"
        case .diagrams: return "Diagrams"
        case .docs: return "Docs"
        case .electronics: return "Electronics"
        case .fitness: return "Fitness"
        case .finance: return "Finance"
        case .health: return "Health"
        case .home: return "Home"
        case .web: return "Web"
        case .images: return "Images"
        case .mail: return "Mail"
        case .maps: return "Maps"
        case .math: return "Math"
        case .mindmaps: return "Mind Maps"
        case .models3d: return "3D Models"
        case .music: return "Music"
        case .news: return "News"
        case .nutrition: return "Nutrition"
        case .pdf: return "PDF"
        case .reminder: return "Reminder"
        case .sheets: return "Sheets"
        case .shopping: return "Shopping"
        case .socialMedia: return "Social"
        case .tasks: return "Tasks"
        case .travel: return "Travel"
        case .videos: return "Videos"
        case .weather: return "Weather"
        case .events: return "Events"
        case .workflows: return "Workflows"
        }
    }
}

struct DevEmbedPreviewSkill: Identifiable {
    let id: String
    let label: String
    let primaryEmbed: EmbedRecord
    let childEmbeds: [EmbedRecord]
    let allRecords: [String: EmbedRecord]
}

enum DevEmbedPreviewFixtures {
    static func isolatedEmbedSkill(variant: String) -> DevEmbedPreviewSkill {
        switch variant {
        case "sheet", "sheet-large": return sheet
        case "sheet-wide": return sheetWide
        case "search-long":
            let source = webSearch
            var data = source.primaryEmbed.rawData ?? [:]
            data["query"] = AnyCodable("best restaurants in Berlin with vegetarian options and outdoor seating near Museum Island")
            let parent = record(id: source.primaryEmbed.id, type: source.primaryEmbed.type, appId: "web", skillId: "search", data: data.mapValues(\.value))
            return skill(id: source.id, label: source.label, primary: parent, children: source.childEmbeds)
        case "search-thumbnail":
            let parent = appSkill(id: "preview-search-thumbnail", type: EmbedType.webSearch.rawValue, appId: "web", skillId: "search",
                                  data: ["query": "best restaurants in Berlin", "provider": "Brave Search", "result_count": 1], embedIds: "preview-search-thumbnail-child")
            let child = record(id: "preview-search-thumbnail-child", type: EmbedType.webWebsite.rawValue, appId: "web",
                               data: ["url": "https://example.org", "title": "Synthetic preview", "description": "Synthetic thumbnail reference",
                                      "preview_image_url": "https://app.dev.openmates.org/favicon.svg"], parentEmbedId: parent.id)
            return skill(id: "search-thumbnail", label: "Search", primary: parent, children: [child])
        default: return webSearch
        }
    }

    static var isolatedSearchGroup: [EmbedRecord] {
        (1...3).map { index in
            appSkill(id: "preview-search-group-\(index)", type: EmbedType.webSearch.rawValue, appId: "web", skillId: "search",
                     data: ["query": "Berlin restaurant search \(index)", "provider": "Brave Search", "result_count": 3])
        }
    }
    /// The generated web registry contains 88 keys. `wiki` and
    /// `diagrams-mermaid` remain native-only legacy types and are excluded.
    static var registryKeys: [String] {
        EmbedType.allCases
            .filter { $0 != .wiki && $0 != .diagramsMermaid }
            .map(\.rawValue)
            .sorted()
    }

    static func skill(forRegistryKey registryKey: String) -> DevEmbedPreviewSkill? {
        if registryKey == EmbedType.fileFile.rawValue {
            let embed = record(id: "preview-file-processing", type: EmbedType.fileFile.rawValue,
                               status: .processing, appId: "file", skillId: "file", data: [:])
            return skill(id: "file-file-processing", label: "File", primary: embed)
        }
        if registryKey == EmbedType.webWebsite.rawValue {
            if ProcessInfo.processInfo.arguments.contains("--dev-website-loaded-preview") {
                return websiteImageVariant(
                    imageURL: "https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=200",
                    id: "preview-website-loaded")
            }
            if ProcessInfo.processInfo.arguments.contains("--dev-website-failed-preview") {
                return websiteImageVariant(
                    imageURL: "https://app.dev.openmates.org/images/examples/does-not-exist.jpg",
                    id: "preview-website-failed")
            }
        }
        if ProcessInfo.processInfo.arguments.contains("--dev-audio-finished-preview") {
            switch EmbedType(rawValue: registryKey) {
            case .audioGenerate: return audioGenerateFinished
            case .audioSpeak: return audioSpeakFinished
            default: break
            }
        }
        let allSkills = DevEmbedPreviewApp.allCases.flatMap { skills(for: $0) }
        if let exact = allSkills.first(where: { $0.primaryEmbed.type == registryKey }) {
            return exact
        }
        switch EmbedType(rawValue: registryKey) {
        case .imagesGenerateDraft:
            return allSkills.first { $0.primaryEmbed.type == EmbedType.imagesGenerate.rawValue }
        case .focusModeActivation:
            return focusModeActivation
        default:
            return nil
        }
    }

    static func fullscreenSkill(forRegistryKey registryKey: String) -> DevEmbedPreviewSkill? {
        if registryKey == EmbedType.fileFile.rawValue { return fileArtifact }
        if registryKey == EmbedType.codeCode.rawValue { return codeFullscreen }
        if registryKey == EmbedType.sheetsSheet.rawValue { return sheetFullscreen }
        if registryKey == EmbedType.healthSearch.rawValue { return healthSearchFullscreen }
        if registryKey == EmbedType.healthAppointment.rawValue { return healthAppointmentFullscreen }
        if registryKey == EmbedType.fitnessClass.rawValue { return fitnessClassFullscreen }
        if registryKey == EmbedType.fitnessLocation.rawValue { return fitnessLocationFullscreen }
        if registryKey == EmbedType.electronicsSearch.rawValue { return electronicsSearchFullscreen }
        if registryKey == EmbedType.electronicsComponent.rawValue { return electronicsComponentFullscreen }
        if registryKey == EmbedType.homeSearch.rawValue { return homeSearchFullscreen }
        if registryKey == EmbedType.nutritionSearch.rawValue { return nutritionSearchFullscreen }
        if registryKey == EmbedType.nutritionRecipe.rawValue { return nutritionRecipeFullscreen }
        if registryKey == EmbedType.shoppingSearch.rawValue { return shoppingSearchFullscreen }
        if registryKey == EmbedType.shoppingProduct.rawValue { return shoppingProductFullscreen }
        if registryKey == EmbedType.mailSearch.rawValue { return mailSearchFullscreen }
        if registryKey == EmbedType.mapsSearch.rawValue { return mapsSearchFullscreen }
        if registryKey == EmbedType.tasksCreate.rawValue { return tasksCreateFullscreen }
        if registryKey == EmbedType.tasksSearch.rawValue { return tasksSearchFullscreen }
        if registryKey == EmbedType.workflowsCreateOrModify.rawValue { return workflowsCreateFullscreen }
        if registryKey == EmbedType.workflowsSearch.rawValue { return workflowsSearchFullscreen }
        if registryKey == EmbedType.webRead.rawValue { return webReadFullscreen }
        if registryKey == EmbedType.videosTranscript.rawValue { return videoTranscriptFullscreen }
        if registryKey == EmbedType.videosCreate.rawValue { return videoCreateFullscreen }
        if registryKey == EmbedType.mathCalculate.rawValue {
            let embed = appSkill(id: "preview-math-calculate-fullscreen-1", type: EmbedType.mathCalculate.rawValue,
                                 appId: "math", skillId: "calculate", data: [
                "query": "sin(pi/4) + cos(pi/3)", "subtitle": "Numeric mode",
                "results": [
                    ["expression": "sin(pi/4) + cos(pi/3)", "result": "1.20710678118655", "result_type": "float", "mode": "numeric"],
                    ["expression": "diff(x^3, x)", "result": "3*x**2", "result_type": "symbolic", "mode": "diff"]
                ]
            ])
            return skill(id: "math-calculate-fullscreen", label: "Calculate", primary: embed)
        }
        if registryKey == EmbedType.mathPlot.rawValue {
            let embed = record(id: "preview-math-plot-fullscreen-1", type: EmbedType.mathPlot.rawValue,
                               appId: "math", data: [
                "title": "Trigonometric Functions",
                "plot_spec": "f(x) = sin(x)\nf(x) = cos(x)\nf(x) = tan(x)"
            ])
            return skill(id: "math-plot-fullscreen", label: "Plot", primary: embed)
        }
        if registryKey == EmbedType.electronicsPcbSchematic.rawValue {
            let embed = record(id: "preview-electronics-pcb-fullscreen-1",
                               type: EmbedType.electronicsPcbSchematic.rawValue,
                               appId: "electronics", data: ["filename": "board.ato", "language": "atopile"])
            return skill(id: "electronics-pcb-fullscreen", label: "PCB Schematic", primary: embed)
        }
        if registryKey == EmbedType.mindmapsMindmap.rawValue {
            let nodes: [[String: Any]] = [
                ["id": "launch", "label": "Launch Plan", "description": "Coordinate launch workstreams", "children": ["research", "build", "ship"]],
                ["id": "research", "label": "Audience Research", "children": ["interviews", "survey"]],
                ["id": "interviews", "label": "Customer Interviews"],
                ["id": "survey", "label": "Survey"],
                ["id": "build", "label": "Build", "children": ["copy", "landing"]],
                ["id": "copy", "label": "Messaging"],
                ["id": "landing", "label": "Landing Page"],
                ["id": "ship", "label": "Ship", "children": ["announcement", "followup"]],
                ["id": "announcement", "label": "Announcement"],
                ["id": "followup", "label": "Follow-up"]
            ]
            let model: [String: Any] = [
                "openmatesType": "mindmap", "schemaVersion": 1, "title": "Launch Plan", "rootId": "launch",
                "nodes": nodes,
                "edges": [["source": "research", "target": "copy", "type": "dependency"]],
                "view": ["layout": "radial-tree", "collapsedNodeIds": []]
            ]
            let source = (try? JSONSerialization.data(withJSONObject: model, options: [.sortedKeys]))
                .flatMap { String(data: $0, encoding: .utf8) } ?? ""
            let embed = record(id: "preview-mindmap-fullscreen-1", type: EmbedType.mindmapsMindmap.rawValue,
                               appId: "mindmaps", data: ["source_json": source, "title": "Launch Plan"])
            return skill(id: "mindmap-fullscreen", label: "Mind Map", primary: embed)
        }
        if registryKey == EmbedType.codeGetDocs.rawValue {
            let embed = appSkill(id: "preview-code-get-docs-fullscreen-1", type: EmbedType.codeGetDocs.rawValue,
                                 appId: "code", skillId: "get_docs", data: [
                "library": "svelte", "question": "How to use $state rune in Svelte 5?",
                "results": [["library": ["id": "/sveltejs/svelte", "title": "Svelte",
                                          "description": "Cybernetically enhanced web apps"],
                             "documentation": codeGetDocsFullscreenMarkdown,
                             "source": "context7", "word_count": 180]]
            ])
            return skill(id: "code-get-docs-fullscreen", label: "Get Docs", primary: embed)
        }
        if registryKey == EmbedType.eventsEvent.rawValue {
            let embed = eventRecord(
                id: "preview-event-fullscreen-1",
                title: "AI & Machine Learning Berlin Meetup – Spring Edition",
                dateStart: "2026-03-15T19:00:00+01:00", dateEnd: "2026-03-15T22:00:00+01:00",
                eventType: "PHYSICAL", city: "Berlin", country: "Germany",
                rsvpCount: 142, isPaid: false, feeAmount: nil, imageURL: nil,
                venueName: "Factory Berlin", venueAddress: "Rheinsberger Str. 76-77",
                venueLatitude: 52.5393, venueLongitude: 13.4028, parentId: nil,
                description: "Join us for an evening of talks on large language models, RAG architectures, and deploying AI to production. Speakers from leading Berlin AI companies.\n\nSchedule:\n- 18:30 Doors open\n- 19:00 Talk 1: LLMs in Production\n- 19:45 Talk 2: RAG Architectures\n- 20:30 Networking\n\nThis is a beginner-friendly event — no prior ML experience required. Light refreshments will be provided."
            )
            return skill(id: "events-event-fullscreen", label: "Event", primary: embed)
        }
        if registryKey == EmbedType.pdf.rawValue {
            let embed = record(id: "preview-pdf-fullscreen-1", type: EmbedType.pdf.rawValue,
                               appId: "pdf", data: ["filename": "Q4-2025-Annual-Report.pdf"])
            return skill(id: "pdf-fullscreen", label: "PDF", primary: embed)
        }
        if registryKey == EmbedType.image.rawValue {
            let original: [String: Any] = [
                "s3_key": "ui-test/original-image",
                "aes_nonce": String(repeating: "0", count: 24),
                "format": "jpg"
            ]
            var imageData: [String: Any] = [
                "filename": "golden-gate-sunset.jpg",
                "file_size": 2_411_520,
                "file_type": "image/jpeg"
            ]
            if ProcessInfo.processInfo.arguments.contains("--dev-image-original-header") {
                imageData["aes_key"] = String(repeating: "0", count: 64)
                imageData["files"] = ["original": original]
            }
            let embed = record(id: "preview-image-embed-fullscreen-1", type: EmbedType.image.rawValue,
                               appId: "images", data: imageData)
            return skill(id: "image-fullscreen", label: "Image", primary: embed)
        }
        if registryKey == EmbedType.videosVideo.rawValue {
            let embed = record(id: "preview-videos-video-fullscreen-1",
                               type: EmbedType.videosVideo.rawValue, appId: "videos", data: [
                                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                                "video_id": "dQw4w9WgXcQ",
                                "title": "Understanding Svelte 5 Runes — Complete Tutorial"
                               ])
            return skill(id: "videos-video-fullscreen", label: "Video", primary: embed)
        }
        if registryKey == EmbedType.recording.rawValue {
            let embed = record(id: "preview-audio-1", type: EmbedType.recording.rawValue, appId: "audio", data: [
                "filename": "voice-memo-2026-03-10.webm", "duration": "0:42", "duration_seconds": 42,
                "model": "voxtral-mini-2602",
                "transcript": "This is a test transcription of the recorded audio message. The voice memo discusses the sprint review results and action items for the next week. Key highlights include the completion of the authentication refactor and the new API rate limiting feature."
            ])
            return skill(id: "recording-fullscreen", label: "Recording", primary: embed)
        }
        if !ProcessInfo.processInfo.arguments.contains("--dev-audio-finished-preview") {
            switch EmbedType(rawValue: registryKey) {
            case .audioGenerate, .audioSpeak:
                let type = EmbedType(rawValue: registryKey) ?? .audioGenerate
                let embed = generatedAudioRecord(
                    id: "preview-audio-fullscreen-1", type: type,
                    skillId: "generate", prompt: "", mode: "sound_effect",
                    status: .finished, includePlayableMedia: false
                )
                return skill(id: "audio-fullscreen", label: "Generate SFX", primary: embed)
            default: break
            }
        }
        return skill(forRegistryKey: registryKey)
    }

    private static var focusModeActivation: DevEmbedPreviewSkill {
        let embed = record(
            id: "preview-focus-mode-activation",
            type: EmbedType.focusModeActivation.rawValue,
            appId: "jobs",
            data: [
                "focus_id": "jobs-career_insights",
                "focus_mode_name": "Career Insights",
                "already_active": true
            ]
        )
        return skill(id: "focus-mode-activation", label: "Career Insights", primary: embed)
    }

    static func skills(for app: DevEmbedPreviewApp) -> [DevEmbedPreviewSkill] {
        switch app {
        case .audio:
            return [audioGenerate, audioSpeak, recording]
        case .business:
            return [businessCompanyFinancials, businessFinancialResult]
        case .calendar:
            return [calendarListCalendars, calendarGetEvents, calendarCreateEvent, calendarUpdateEvent, calendarDeleteEvent]
        case .code:
            return [codeEmbed, codeNotebook, fileArtifact, codeRepoSearch, codeRepo, codeApplication, codeGetDocs]
        case .design:
            return [designSearchIcons, designIconResult]
        case .diagrams:
            return [diagramsMermaid]
        case .docs:
            return [docsDocument]
        case .electronics:
            return [electronicsPcbSchematic, electronicsSearch, electronicsComponent]
        case .fitness:
            return [fitnessSearchLocations, fitnessLocation, fitnessSearchClasses, fitnessClass]
        case .finance:
            return [financeCheckAccounts]
        case .health:
            return [healthAppointment, healthSearch]
        case .home:
            return [homeSearch, homeListing]
        case .web:
            return [webSearch, webSearchYouTube, webRead, website]
        case .images:
            return [imageGenerate, imagesSearch, imageResult, imageUpload, imageView]
        case .mail:
            return [mail, mailSearch]
        case .maps:
            return [mapsSearch, mapsLocation]
        case .math:
            return [mathCalculate, mathPlot]
        case .mindmaps:
            return [mindmapsMindmap]
        case .models3d:
            return [models3dSearch, models3dModelResult, models3dGenerate]
        case .music:
            return [musicGenerate]
        case .news:
            return [newsSearch]
        case .nutrition:
            return [nutritionSearch, nutritionRecipe]
        case .pdf:
            return [pdf]
        case .reminder:
            return [reminderSet, reminderList, reminderCancel]
        case .sheets:
            return [sheet]
        case .shopping:
            return [shoppingSearch, shoppingProduct]
        case .socialMedia:
            return [socialMediaGetPosts, socialMediaSearch, socialMediaPost]
        case .tasks:
            return [tasksCreate, tasksSearch, tasksTask]
        case .travel:
            return [travelSearch, travelConnection, travelPriceCalendar, travelFlight, travelStay, travelStays]
        case .videos:
            return [videosSearch, video, videoTranscript, videoGenerate, videoCreate]
        case .weather:
            return [weatherForecast, weatherDay, weatherRainRadar]
        case .events:
            return [eventsSearch, event]
        case .workflows:
            return [workflowsCreate, workflowsSearch, workflowsWorkflow]
        }
    }

    // MARK: - Code

    private static var codeEmbed: DevEmbedPreviewSkill {
        let hydratedIndexRegression = ProcessInfo.processInfo.arguments.contains("--dev-code-hydrated-index")
        let embed = record(
            id: "preview-code-1",
            type: EmbedType.codeCode.rawValue,
            appId: "code",
            skillId: "code",
            data: [
                "type": "code",
                "app_id": "code",
                "skill_id": "code",
                "decodedContent": [
                    "language": hydratedIndexRegression ? "html" : "typescript",
                    "filename": hydratedIndexRegression ? "index.html" : "MyComponent.svelte",
                    "line_count": hydratedIndexRegression ? 8 : 14,
                    "code": hydratedIndexRegression ? """
                    <!doctype html>
                    <html lang="en">
                    <head><title>OpenMates preview</title></head>
                    <body>
                      <main><h1>Rendered index.html</h1></main>
                    </body>
                    </html>
                    """ : codePreviewSource
                ]
            ],
            versionNumber: hydratedIndexRegression ? 3 : nil,
            versionHistory: hydratedIndexRegression ? [
                EmbedVersionMetadata(versionNumber: 1, createdAt: 1760000000, hasSnapshot: true, hasPatch: false, contentHash: "preview-code-v1"),
                EmbedVersionMetadata(versionNumber: 2, createdAt: 1760000100, hasSnapshot: false, hasPatch: true, contentHash: "preview-code-v2"),
                EmbedVersionMetadata(versionNumber: 3, createdAt: 1760000200, hasSnapshot: false, hasPatch: true, contentHash: "preview-code-v3")
            ] : [],
            versionHistoryReadonly: false
        )
        return skill(id: "code-code", label: "Code", primary: embed)
    }

    private static let codePreviewSource = """
    import { onMount } from 'svelte';

    interface Props {
      title: string;
      count?: number;
    }

    let { title, count = 0 }: Props = $props();
    let isLoading = $state(false);
    let displayTitle = $derived(title.toUpperCase());

    onMount(() => {
      console.log('Component mounted');
    });
    """

    private static let codeFullscreenSource = """
    import { onMount } from 'svelte';
    import { browser } from '$app/environment';

    interface Props {
      title: string;
      items: string[];
      onSelect?: (item: string) => void;
    }

    let { title, items, onSelect }: Props = $props();

    let searchQuery = $state('');
    let isExpanded = $state(false);

    let filteredItems = $derived(
      items.filter(item =>
        item.toLowerCase().includes(searchQuery.toLowerCase())
      )
    );

    onMount(() => {
      if (browser) {
        console.log('Component mounted in browser');
      }
    });

    function handleSelect(item: string) {
      onSelect?.(item);
      isExpanded = false;
    }
    """

    private static var codeFullscreen: DevEmbedPreviewSkill {
        let embed = record(id: "preview-code-fullscreen-1", type: EmbedType.codeCode.rawValue,
                           appId: "code", skillId: "code", data: [
                            "decodedContent": [
                                "code": codeFullscreenSource, "language": "typescript",
                                "filename": "SearchableList.svelte", "line_count": 32
                            ]
                           ])
        return skill(id: "code-code-fullscreen", label: "Code", primary: embed)
    }

    private static var codeNotebook: DevEmbedPreviewSkill {
        let embed = record(id: "preview-code-notebook-1", type: EmbedType.codeNotebook.rawValue,
                           appId: "code", skillId: "notebook",
                           data: ["filename": "notebook.ipynb", "notebook": ["nbformat": 4, "cells": []]])
        return skill(id: "code-notebook", label: "Notebook", primary: embed)
    }

    private static var fileArtifact: DevEmbedPreviewSkill {
        let embed = record(
            id: "preview-file-file-1",
            type: EmbedType.fileFile.rawValue,
            appId: "file",
            skillId: "file",
            data: [
                "normalized_path": "artifacts/reports/berlin-weather.csv",
                "filename": "berlin-weather.csv",
                "mime_type": "text/csv",
                "size_bytes": 24_576,
                "download_url": "https://example.invalid/download/berlin-weather.csv",
                "download_expires_at": 1_893_456_000
            ]
        )
        return skill(id: "file-file", label: "File", primary: embed)
    }

    private static var codeGetDocs: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-code-get-docs-1",
            type: EmbedType.codeGetDocs.rawValue,
            appId: "code",
            skillId: "get_docs",
            data: [
                "library": "svelte",
                "question": "How to use $state rune in Svelte 5?",
                "results": [[
                    "library": ["id": "/sveltejs/svelte", "title": "Svelte",
                                "description": "Cybernetically enhanced web apps"],
                    "documentation": "The `$state` rune declares reactive state. When you assign to a `$state` variable, Svelte automatically updates all DOM nodes that depend on it.\n\n## Basic Usage\n\n```svelte\n<script>\nlet count = $state(0);\n</script>\n<button onclick={() => count++}>{count}</button>\n```",
                    "word_count": 48, "source": "context7"
                ]]
            ]
        )
        return skill(id: "code-get-docs", label: "Get Docs", primary: embed)
    }

    private static let codeGetDocsFullscreenMarkdown = #"""
    # $state — Svelte 5 Runes

    The `$state` rune declares reactive state. When you assign to a `$state` variable, Svelte automatically updates all DOM nodes that depend on it.

    ## Basic Usage

    ```svelte
    <script>
    let count = $state(0);
    </script>

    <button onclick={() => count++}>
      Clicks: {count}
    </button>
    ```

    ## Deep Reactivity

    `$state` provides deep reactivity for objects and arrays. Changes to nested properties are tracked automatically.

    ```svelte
    <script>
    let user = $state({ name: 'Alice', age: 30 });
    </script>

    <input bind:value={user.name} />
    <p>Name: {user.name}</p>
    ```

    ## With TypeScript

    ```ts
    let count = $state<number>(0);
    let items = $state<string[]>([]);
    ```

    ## Differences from Svelte 4

    In Svelte 4, reactive variables were declared at the top level of `<script>` and updated reactively. In Svelte 5, you explicitly mark state with `$state()` — this makes reactivity explicit and works inside functions, classes, and modules.

    | Svelte 4 | Svelte 5 |
    |----------|----------|
    | `let count = 0;` (top-level) | `let count = $state(0);` |
    | `$: doubled = count * 2;` | `let doubled = $derived(count * 2);` |
    | `onMount(() => ...)` | Same |

    ## Related

    - [`$derived`](https://svelte.dev/docs/svelte/$derived) — computed values
    - [`$effect`](https://svelte.dev/docs/svelte/$effect) — side effects
    - [`$props`](https://svelte.dev/docs/svelte/$props) — component props
    """#

    // MARK: - Web

    private static var webSearch: DevEmbedPreviewSkill {
        let children = [
            record(
                id: "preview-web-search-result-1",
                type: EmbedType.webWebsite.rawValue,
                appId: "web",
                data: [
                    "url": "https://www.visitberlin.de/en/restaurants",
                    "title": "Top 10 Restaurants in Berlin - Local Guide",
                    "description": "Discover the best dining experiences in Berlin, from traditional German cuisine to international flavors.",
                    "preview_image_url": ProcessInfo.processInfo.arguments.contains("--dev-web-search-loaded-preview")
                        ? "https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=200"
                        : "/images/examples/group1.jpg",
                    "age": "2026-07-25T00:00:00Z",
                    "page_age": "2026-07-25T00:00:00Z",
                    "language": "en",
                    "family_friendly": true
                ],
                parentEmbedId: "preview-web-search-1"
            ),
            record(
                id: "preview-web-search-result-2",
                type: EmbedType.webWebsite.rawValue,
                appId: "web",
                data: [
                    "url": "https://www.timeout.com/berlin/restaurants",
                    "title": "Berlin Food Scene: A Complete Guide",
                    "description": "From street food to Michelin-starred restaurants, explore what makes Berlin one of Europe's top food destinations.",
                    "age": "2026-07-24T00:00:00Z",
                    "page_age": "2026-07-24T00:00:00Z",
                    "language": "en",
                    "family_friendly": true
                ],
                parentEmbedId: "preview-web-search-1"
            ),
            record(
                id: "preview-web-search-result-3",
                type: EmbedType.webWebsite.rawValue,
                appId: "web",
                data: [
                    "url": "https://www.lonelyplanet.com/germany/berlin/restaurants",
                    "title": "Where to Eat in Berlin - Travel Blog",
                    "description": "A curated list of must-visit restaurants, cafes, and food markets in Berlin. Includes budget-friendly options.",
                    "age": "2026-07-23T00:00:00Z",
                    "page_age": "2026-07-23T00:00:00Z",
                    "language": "en",
                    "family_friendly": true
                ],
                parentEmbedId: "preview-web-search-1"
            )
        ]
        let parent = appSkill(
            id: "preview-web-search-1",
            type: EmbedType.webSearch.rawValue,
            appId: "web",
            skillId: "search",
            data: ["query": "best restaurants in Berlin", "provider": "Brave Search", "result_count": children.count],
            embedIds: children.map(\.id).joined(separator: "|")
        )
        return skill(id: "web-search", label: "Search", primary: parent, children: children)
    }

    private static var webSearchYouTube: DevEmbedPreviewSkill {
        let parentId = "preview-web-search-youtube-1"
        let child = record(
            id: "preview-web-search-youtube-result-1",
            type: EmbedType.webWebsite.rawValue,
            appId: "web",
            data: [
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "title": "YouTube search result",
                "description": "A video result inside a web search.",
                "channel_name": "Video creator",
                "duration_formatted": "3:32"
            ],
            parentEmbedId: parentId
        )
        let parent = appSkill(
            id: parentId,
            type: EmbedType.webSearch.rawValue,
            appId: "web",
            skillId: "search",
            data: ["query": "video result", "provider": "Brave Search", "result_count": 1],
            embedIds: child.id
        )
        return skill(id: "web-search-youtube", label: "YouTube Search", primary: parent, children: [child])
    }

    private static var webRead: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-web-read-1",
            type: EmbedType.webRead.rawValue,
            appId: "web",
            skillId: "read",
            data: [
                "url": "https://svelte.dev/blog/svelte-5-migration-guide",
                "title": "Complete Guide to Migrating from Svelte 4 to Svelte 5",
                "provider": "Firecrawl",
                "results": [[
                    "url": "https://svelte.dev/blog/svelte-5-migration-guide",
                    "title": "Complete Guide to Migrating from Svelte 4 to Svelte 5",
                    "content": "Svelte 5 introduces runes, a powerful new reactivity system that replaces the $: reactive statements. This guide walks you through every step of the migration process, from updating your dependencies to converting your components.",
                    "favicon": ""
                ]]
            ]
        )
        return skill(id: "web-read", label: "Read", primary: embed)
    }

    private static var webReadFullscreen: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-web-read-fullscreen-1",
            type: EmbedType.webRead.rawValue, appId: "web", skillId: "read",
            data: [
                "url": "https://svelte.dev/blog/svelte-5-migration-guide",
                "title": "Complete Guide to Migrating from Svelte 4 to Svelte 5",
                "results": [] as [[String: Any]]
            ]
        )
        return skill(id: "web-read-fullscreen", label: "Read", primary: embed)
    }

    private static var website: DevEmbedPreviewSkill {
        let embed = record(
            id: "preview-website-1",
            type: EmbedType.webWebsite.rawValue,
            appId: "web",
            data: [
                "url": "https://svelte.dev",
                "title": "Svelte — Cybernetically enhanced web apps",
                "description": "Svelte is a radical new approach to building user interfaces. Write less code, use no virtual DOM, and create truly reactive apps.",
                "favicon_url": "https://svelte.dev/favicon.png"
            ]
        )
        return skill(id: "web-website", label: "Website", primary: embed)
    }

    private static func websiteImageVariant(imageURL: String, id: String) -> DevEmbedPreviewSkill {
        let embed = record(id: id, type: EmbedType.webWebsite.rawValue,
                           appId: "web", data: [
                            "url": "https://svelte.dev",
                            "title": "Svelte — Cybernetically enhanced web apps",
                            "description": "Svelte is a radical new approach to building user interfaces. Write less code, use no virtual DOM, and create truly reactive apps.",
                            "image_url": imageURL
                           ])
        return skill(id: id, label: "Website image", primary: embed)
    }

    // MARK: - Images

    private static var imageGenerate: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-image-gen-1",
            type: EmbedType.imagesGenerate.rawValue,
            appId: "images",
            skillId: "generate",
            data: [
                "prompt": "A serene mountain landscape at sunset with vibrant orange and purple skies",
                "model": "flux-schnell"
            ]
        )
        return skill(id: "images-generate", label: "Generate", primary: embed)
    }

    private static var imagesSearch: DevEmbedPreviewSkill {
        let results = imageSearchResults(parentId: "preview-images-search-1")
        let parent = appSkill(
            id: "preview-images-search-1",
            type: EmbedType.imagesSearch.rawValue,
            appId: "images",
            skillId: "search",
            data: ["query": "Golden Gate Bridge", "provider": "Brave"],
            embedIds: results.map(\.id).joined(separator: "|")
        )
        return skill(id: "images-search", label: "Search", primary: parent, children: results)
    }

    private static var imageResult: DevEmbedPreviewSkill {
        let embed = imageResultRecord(
            id: "preview-image-result-1",
            title: "Golden Gate Bridge at dusk",
            thumbnail: "https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=200",
            image: "https://images.unsplash.com/photo-1501594907352-04cda38ebc29",
            parentId: nil
        )
        return skill(id: "images-result", label: "Image Result", primary: embed)
    }

    private static var imageUpload: DevEmbedPreviewSkill {
        let embed = record(
            id: "preview-image-embed-1",
            type: EmbedType.image.rawValue,
            appId: "images",
            data: ["filename": "golden-gate-sunset.jpg"]
        )
        return skill(id: "images-upload", label: "Upload", primary: embed)
    }

    private static var imageView: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-image-view-1",
            type: "app:images:view",
            appId: "images",
            skillId: "view",
            data: ["filename": "golden-gate-sunset.jpg"]
        )
        return skill(id: "images-view", label: "View", primary: embed)
    }

    // MARK: - Travel

    private static var travelSearch: DevEmbedPreviewSkill {
        let children = [
            travelConnectionRecord(
                id: "preview-travel-search-result-1",
                price: "189.00",
                destination: "London Heathrow (LHR)",
                departure: "2026-03-15T08:30:00",
                arrival: "2026-03-15T10:00:00",
                duration: "2h 30m",
                stops: 0,
                carrierCodes: ["LH"],
                parentId: "preview-travel-search-1"
            ),
            travelConnectionRecord(
                id: "preview-travel-search-result-2",
                price: "245.50",
                destination: "London Gatwick (LGW)",
                departure: "2026-03-15T14:15:00",
                arrival: "2026-03-15T17:45:00",
                duration: "4h 30m",
                stops: 1,
                carrierCodes: ["BA", "EW"],
                parentId: "preview-travel-search-1"
            )
        ]
        let parent = appSkill(
            id: "preview-travel-search-1",
            type: EmbedType.travelConnections.rawValue,
            appId: "travel",
            skillId: "search_connections",
            data: ["query": "Munich -> London, 2026-03-15", "provider": "Google"],
            embedIds: children.map(\.id).joined(separator: "|")
        )
        return skill(id: "travel-search", label: "Search", primary: parent, children: children)
    }

    private static var travelConnection: DevEmbedPreviewSkill {
        let embed = travelConnectionRecord(
            id: "preview-travel-connection-1",
            price: "189.00",
            destination: "London Heathrow (LHR)",
            departure: "2026-03-15T08:30:00",
            arrival: "2026-03-15T10:00:00",
            duration: "2h 30m",
            stops: 0,
            carrierCodes: ["LH"],
            parentId: nil
        )
        return skill(id: "travel-connection", label: "Connection", primary: embed)
    }

    private static var travelPriceCalendar: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-travel-price-calendar-1",
            type: EmbedType.travelPriceCalendar.rawValue,
            appId: "travel",
            skillId: "price_calendar",
            data: [
                "query": "Munich -> Barcelona, March 2026",
                "origin": "Munich",
                "destination": "Barcelona"
            ]
        )
        return skill(id: "travel-price-calendar", label: "Price Calendar", primary: embed)
    }

    private static var travelFlight: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-travel-flight-1",
            type: EmbedType.travelFlight.rawValue,
            appId: "travel",
            skillId: "get_flight",
            data: [
                "tracks": []
            ]
        )
        return skill(id: "travel-get-flight", label: "Flight", primary: embed)
    }

    private static var travelStay: DevEmbedPreviewSkill {
        let embed = travelStayRecord(
            id: "preview-travel-stay-1",
            name: "Hotel Maximilian",
            hotelClass: 4,
            rating: 4.3,
            reviews: 1248,
            ratePerNight: "129",
            totalRate: "387",
            parentId: nil
        )
        return skill(id: "travel-stay", label: "Stay", primary: embed)
    }

    private static var travelStays: DevEmbedPreviewSkill {
        let children = [
            travelStayRecord(id: "preview-travel-stays-result-1", name: "Hotel Arts Barcelona", hotelClass: 5, rating: 4.7, reviews: 4521, ratePerNight: "320", totalRate: "960", parentId: "preview-travel-stays-1"),
            travelStayRecord(id: "preview-travel-stays-result-2", name: "Casa Camper Barcelona", hotelClass: 4, rating: 4.4, reviews: 1832, ratePerNight: "185", totalRate: "555", parentId: "preview-travel-stays-1"),
            travelStayRecord(id: "preview-travel-stays-result-3", name: "Generator Barcelona", hotelClass: 2, rating: 4.0, reviews: 3200, ratePerNight: "55", totalRate: "165", parentId: "preview-travel-stays-1")
        ]
        let parent = appSkill(
            id: "preview-travel-stays-1",
            type: EmbedType.travelStays.rawValue,
            appId: "travel",
            skillId: "search_stays",
            data: ["query": "Hotels in Barcelona, Mar 15-18", "provider": "Google"],
            embedIds: children.map(\.id).joined(separator: "|")
        )
        return skill(id: "travel-stays", label: "Stays Search", primary: parent, children: children)
    }

    // MARK: - Events

    private static var eventsSearch: DevEmbedPreviewSkill {
        let children = eventResults(parentId: "preview-events-search-1")
        let parent = appSkill(
            id: "preview-events-search-1",
            type: EmbedType.eventsSearch.rawValue,
            appId: "events",
            skillId: "search",
            data: [
                "query": "AI meetups in Berlin",
                "provider": "Meetup",
                "providers": ["meetup"]
            ],
            embedIds: children.map(\.id).joined(separator: "|")
        )
        return skill(id: "events-search", label: "Search", primary: parent, children: children)
    }

    private static var event: DevEmbedPreviewSkill {
        let embed = eventRecord(
            id: "preview-event-1",
            title: "AI & Machine Learning Berlin Meetup – Spring Edition",
            dateStart: "2026-03-15T19:00:00+01:00",
            dateEnd: "2026-03-15T22:00:00+01:00",
            eventType: "PHYSICAL",
            city: "Berlin",
            country: "Germany",
            rsvpCount: 142,
            isPaid: false,
            feeAmount: nil,
            imageURL: nil,
            venueName: "Factory Berlin",
            venueAddress: "Rheinsberger Str. 76-77",
            venueLatitude: 52.5393,
            venueLongitude: 13.4028,
            parentId: nil,
            description: "Join us for an evening of talks on large language models, RAG architectures, and deploying AI to production. Speakers from leading Berlin AI companies.\n\nSchedule:\n- 18:30 Doors open\n- 19:00 Talk 1: LLMs in Production\n- 19:45 Talk 2: RAG Architectures\n- 20:30 Networking"
        )
        return skill(id: "events-event", label: "Event", primary: embed)
    }

    // MARK: - Additional registry coverage

    private static var recording: DevEmbedPreviewSkill {
        let embed = record(id: "preview-audio-1", type: EmbedType.recording.rawValue, appId: "audio", data: [
            "filename": "voice-memo-2026-03-10.webm", "duration": "0:42", "duration_seconds": 42,
            "model": "voxtral-mini-2602",
            "transcript": "This is a test transcription of the recorded audio message. The voice memo discusses the sprint review results and action items for the next week."
        ])
        return skill(id: "recording", label: "Recording", primary: embed)
    }

    private static var audioGenerate: DevEmbedPreviewSkill {
        let embed = generatedAudioRecord(
            id: "preview-audio-generate-1",
            type: .audioGenerate,
            skillId: "generate",
            prompt: "",
            mode: "sound_effect",
            status: .processing
        )
        return skill(id: "audio-generate", label: "Generate audio", primary: embed)
    }

    private static var audioSpeak: DevEmbedPreviewSkill {
        // The deployed registry preview resolves this key to the shared
        // AudioGenerateEmbedPreview default (Generate SFX processing state).
        // The explicit finished fixture below exercises actual speak content.
        let embed = generatedAudioRecord(
            id: "preview-audio-speak-1",
            type: .audioSpeak,
            skillId: "generate",
            prompt: "",
            mode: "sound_effect",
            status: .processing
        )
        return skill(id: "audio-speak", label: "Speak", primary: embed)
    }

    private static var audioGenerateFinished: DevEmbedPreviewSkill {
        let embed = generatedAudioRecord(
            id: "preview-audio-generate-finished-1", type: .audioGenerate,
            skillId: "generate", prompt: "Soft rain on a Berlin courtyard with distant bicycle bells",
            mode: "sound_effect", status: .finished
        )
        return skill(id: "audio-generate-finished", label: "Generate audio", primary: embed)
    }

    private static var audioSpeakFinished: DevEmbedPreviewSkill {
        let embed = generatedAudioRecord(
            id: "preview-audio-speak-finished-1", type: .audioSpeak,
            skillId: "speak", prompt: "Your itinerary is ready for tomorrow morning.",
            mode: "calm", status: .finished
        )
        return skill(id: "audio-speak-finished", label: "Speak", primary: embed)
    }

    private static func generatedAudioRecord(
        id: String,
        type: EmbedType,
        skillId: String,
        prompt: String,
        mode: String,
        status: EmbedStatus,
        includePlayableMedia: Bool = true
    ) -> EmbedRecord {
        appSkill(
            id: id,
            type: type.rawValue,
            appId: "audio",
            skillId: skillId,
            data: [
                "prompt": prompt,
                "text_preview": prompt,
                "mode": mode,
                "voice": mode,
                "preview_audio_url": status == .finished && includePlayableMedia
                    ? "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA="
                    : ""
            ],
            status: status
        )
    }

    private static var calendarListCalendars: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-calendar-list-calendars-1",
            type: EmbedType.calendarListCalendars.rawValue,
            appId: "calendar",
            skillId: "list-calendars",
            data: [:],
            status: .processing
        )
        return skill(id: "calendar-list-calendars", label: "List calendars", primary: embed)
    }

    private static var calendarGetEvents: DevEmbedPreviewSkill {
        calendarAction(id: "calendar-get-events", skillId: "get-events", title: "Upcoming events")
    }

    private static var calendarCreateEvent: DevEmbedPreviewSkill {
        calendarAction(id: "calendar-create-event", skillId: "create-event", title: "Project review")
    }

    private static var calendarUpdateEvent: DevEmbedPreviewSkill {
        calendarAction(id: "calendar-update-event", skillId: "update-event", title: "Updated project review")
    }

    private static var calendarDeleteEvent: DevEmbedPreviewSkill {
        calendarAction(id: "calendar-delete-event", skillId: "delete-event", title: "Cancelled project review")
    }

    private static func calendarAction(id: String, skillId: String, title: String) -> DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-\(id)-1",
            type: "app:calendar:\(skillId)",
            appId: "calendar",
            skillId: skillId,
            data: [:],
            status: .processing
        )
        return skill(id: id, label: title, primary: embed)
    }

    private static var codeRepoSearch: DevEmbedPreviewSkill {
        let repos: [[String: Any]] = [
            ["full_name": "sveltejs/svelte", "url": "https://github.com/sveltejs/svelte"],
            ["full_name": "markedjs/marked", "url": "https://github.com/markedjs/marked"]
        ]
        let children = repos.enumerated().map { index, repo in
            record(id: "preview-code-repo-\(index + 1)", type: EmbedType.codeRepo.rawValue,
                   appId: "code", data: repo, parentEmbedId: "preview-code-repo-search-1")
        }
        let parent = appSkill(id: "preview-code-repo-search-1", type: EmbedType.codeRepoSearch.rawValue,
                              appId: "code", skillId: "search_repos", data: [
            "query": "svelte markdown editor", "provider": "GitHub",
            "results": [["id": 0, "results": repos]], "result_count": 2
        ], embedIds: children.map(\.id).joined(separator: "|"))
        return skill(id: "code-search-repos", label: "Search Repos", primary: parent, children: children)
    }

    private static var codeRepo: DevEmbedPreviewSkill {
        let embed = record(id: "preview-code-repo-direct-1", type: EmbedType.codeRepo.rawValue, appId: "code", data: [
            "url": "https://github.com/lemmingDev/ESP32-BLE-Gamepad",
            "full_name": "lemmingDev/ESP32-BLE-Gamepad",
            "name": "ESP32-BLE-Gamepad",
            "owner_login": "lemmingDev",
            "owner_avatar_url": "https://avatars.githubusercontent.com/u/15526971?v=4",
            "description": "Bluetooth LE Gamepad library for the ESP32",
            "primary_language": "C++",
            "license_name": "MIT License",
            "license_spdx_id": "MIT",
            "stars": 1516,
            "forks": 250,
            "open_issues": 35,
            "updated_at": "2026-05-08T09:02:54Z"
        ])
        return skill(id: "code-repo", label: "Repository", primary: embed)
    }

    private static var codeApplication: DevEmbedPreviewSkill {
        let embed = record(id: "preview-code-application-1", type: EmbedType.codeApplication.rawValue, appId: "code", data: [
            "name": "Recipe Manager", "framework": "Svelte", "runtime": "Node",
            "file_refs": [
                ["path": "package.json", "embed_id": "file-package", "role": "dependency_manifest"],
                ["path": "src/App.svelte", "embed_id": "file-app", "role": "source"],
                ["path": "src/main.ts", "embed_id": "file-main", "role": "source"]
            ],
            "entrypoints": [["name": "frontend", "command": "npm run dev", "port": 5173]]
        ])
        return skill(id: "code-application", label: "Application", primary: embed)
    }

    private static var businessCompanyFinancials: DevEmbedPreviewSkill {
        let results: [[String: Any]] = [
            ["company": "Cal-Maine Foods, Inc.", "ticker": "CALM", "cik": "0000016160", "country": "US", "exchange": "NASDAQ", "period_type": "annual", "fiscal_year": 2025, "period_start": "2024-06-02", "period_end": "2025-05-31", "filed": "2025-07-18", "form": "10-K", "currency": "USD", "revenue": 4_261_885_000, "gross_profit": 1_799_800_000, "operating_income": 1_446_200_000, "net_income": 1_220_048_000, "operating_cash_flow": 1_260_000_000, "assets": 3_451_000_000, "liabilities": 602_000_000, "equity": 2_849_000_000, "source_url": "https://www.sec.gov/ixviewer/doc/action?doc=/Archives/edgar/data/16160/000001616025000050/calm-20250531.htm", "accession_number": "0000016160-25-000050"],
            ["company": "Micron Technology, Inc.", "ticker": "MU", "cik": "0000723125", "country": "US", "exchange": "NASDAQ", "period_type": "annual", "fiscal_year": 2025, "period_start": "2024-08-30", "period_end": "2025-08-28", "filed": "2025-10-03", "form": "10-K", "currency": "USD", "revenue": 37_378_000_000, "gross_profit": 14_212_000_000, "operating_income": 9_411_000_000, "net_income": 8_539_000_000, "operating_cash_flow": 15_840_000_000, "assets": 82_120_000_000, "liabilities": 26_300_000_000, "equity": 55_820_000_000, "source_url": "https://www.sec.gov/ixviewer/doc/action?doc=/Archives/edgar/data/723125/000072312525000120/mu-20250828.htm", "accession_number": "0000723125-25-000120"]
        ]
        let children = results.enumerated().map { index, result in
            record(id: "legacy-business-financial-\(index == 0 ? "calm" : "mu")", type: EmbedType.businessCompanyFinancialResult.rawValue, appId: "business", skillId: "company_financials", data: result, parentEmbedId: "preview-business-financials-1")
        }
        let parent = appSkill(
            id: "preview-business-financials-1",
            type: EmbedType.businessCompanyFinancials.rawValue,
            appId: "business",
            skillId: "company_financials",
            data: [
                "query": "Compare CALM and MU latest annual financials",
                "provider": "SEC EDGAR",
                "period": "latest_annual",
                "metric_group": "summary",
                "result_count": 2,
                "results": results
            ],
            embedIds: children.map(\.id).joined(separator: "|")
        )
        return skill(id: "business-company-financials", label: "Company Financials", primary: parent, children: children)
    }

    private static var businessFinancialResult: DevEmbedPreviewSkill {
        let embed = record(
            id: "preview-business-financial-calm",
            type: EmbedType.businessCompanyFinancialResult.rawValue,
            appId: "business",
            skillId: "company_financials",
            data: [
                "company": "Cal-Maine Foods, Inc.",
                "ticker": "CALM",
                "cik": "0000016160",
                "period_type": "annual",
                "fiscal_year": 2025,
                "form": "10-K",
                "currency": "USD",
                "revenue": 4_261_885_000,
                "net_income": 1_220_048_000,
                "filed": "2025-07-18"
            ]
        )
        return skill(id: "business-financial-result", label: "Financial Result", primary: embed)
    }

    private static var designSearchIcons: DevEmbedPreviewSkill {
        let child = record(
            id: "preview-design-icon-result-1",
            type: EmbedType.designIconResult.rawValue,
            appId: "design",
            data: [
                "display_name": "Calendar Check",
                "collection_name": "Lucide",
                "license_title": "ISC",
                "svg_path": "M8 2v4M16 2v4M3 10h18"
            ],
            parentEmbedId: "preview-design-search-icons-1"
        )
        let parent = appSkill(id: "preview-design-search-icons-1", type: EmbedType.designSearchIcons.rawValue, appId: "design", skillId: "search_icons", data: ["query": "calendar check icon", "provider": "Iconify", "result_count": 1], embedIds: child.id)
        return skill(id: "design-search-icons", label: "Search Icons", primary: parent, children: [child])
    }

    private static var designIconResult: DevEmbedPreviewSkill {
        // The deployed canonical registry supplies no icon record for this
        // standalone surface; the production fallback shows "Icon"/"SVG icon".
        let embed = record(id: "preview-design-icon-result-direct-1", type: EmbedType.designIconResult.rawValue, appId: "design", data: [:])
        return skill(id: "design-icon-result", label: "Icon Result", primary: embed)
    }

    private static var diagramsMermaid: DevEmbedPreviewSkill {
        // Mirrors MermaidDiagramEmbedPreview.preview.ts for native/browser visual comparison.
        let diagramCode = """
        sequenceDiagram
            participant User
            participant App
            participant API
            participant Email
            User->>App: Enter email address
            App->>API: Request verification code
            API->>Email: Send one-time code
            Email-->>User: Deliver code
            User->>App: Submit code
            App->>API: Verify code
            API-->>App: Create account session
            App-->>User: Show welcome screen
        """
        let embed = record(
            id: "preview-diagrams-mermaid-1",
            type: EmbedType.diagramsMermaid.rawValue,
            appId: "diagrams",
            skillId: "mermaid",
            data: [
                "type": "mermaid",
                "app_id": "diagrams",
                "skill_id": "mermaid",
                "title": "Email Signup Sequence",
                "diagram_kind": "sequenceDiagram",
                "diagram_code": diagramCode,
                "line_count": diagramCode.split(separator: "\n").count,
                "status": "finished"
            ],
            versionNumber: 1
        )
        return skill(id: "diagrams-mermaid", label: "Mermaid", primary: embed)
    }

    // Exact synthetic page art used by the deployed Docs preview fixtures.
    private static func docsPreviewPageURL(_ svg: String) -> String {
        let unreserved = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~")
        return "data:image/svg+xml;charset=utf-8," + (svg.addingPercentEncoding(withAllowedCharacters: unreserved) ?? "")
    }

    private static var docsPageOneSVG: String {
        #"""
        <svg xmlns="http://www.w3.org/2000/svg" width="794" height="1123" viewBox="0 0 794 1123">
        <rect width="794" height="1123" fill="#ffffff"/>
        <rect x="76" y="72" width="642" height="979" rx="2" fill="#ffffff" stroke="#e5e7eb"/>
        <text x="112" y="148" font-family="Inter, Arial, sans-serif" font-size="34" font-weight="700" fill="#111827">Project Architecture Overview</text>
        <text x="112" y="206" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">Generated as a real DOCX artifact, then converted server-side to preview pages.</text>
        <rect x="112" y="252" width="570" height="1" fill="#d1d5db"/>
        <text x="112" y="314" font-family="Inter, Arial, sans-serif" font-size="22" font-weight="700" fill="#111827">Frontend</text>
        <text x="112" y="356" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">SvelteKit and Svelte 5 render the encrypted document preview after decrypting</text>
        <text x="112" y="382" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">the generated screenshot artifact in the browser.</text>
        <text x="112" y="456" font-family="Inter, Arial, sans-serif" font-size="22" font-weight="700" fill="#111827">Backend Pipeline</text>
        <text x="112" y="498" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">1. The model emits structured docx_model JSON.</text>
        <text x="112" y="526" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">2. The Docs worker creates a canonical .docx file.</text>
        <text x="112" y="554" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">3. LibreOffice converts it to PDF; PyMuPDF renders page screenshots.</text>
        <text x="112" y="582" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">4. DOCX and screenshots are AES-GCM encrypted before upload.</text>
        <rect x="112" y="660" width="570" height="132" rx="14" fill="#eef2ff" stroke="#c7d2fe"/>
        <text x="142" y="711" font-family="Inter, Arial, sans-serif" font-size="18" font-weight="700" fill="#3730a3">Download</text>
        <text x="142" y="750" font-family="Inter, Arial, sans-serif" font-size="16" fill="#4338ca">The download button returns the real generated DOCX, not browser HTML.</text>
        </svg>
        """#
    }

    private static var docsPageTwoSVG: String {
        #"""
        <svg xmlns="http://www.w3.org/2000/svg" width="794" height="1123" viewBox="0 0 794 1123">
        <rect width="794" height="1123" fill="#ffffff"/>
        <rect x="76" y="72" width="642" height="979" rx="2" fill="#ffffff" stroke="#e5e7eb"/>
        <text x="112" y="148" font-family="Inter, Arial, sans-serif" font-size="30" font-weight="700" fill="#111827">Compatibility</text>
        <text x="112" y="214" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">Existing document_html embeds still render through the legacy HTML fallback.</text>
        <text x="112" y="242" font-family="Inter, Arial, sans-serif" font-size="16" fill="#374151">New embeds use docx_model, encrypted artifacts, and generated preview pages.</text>
        <rect x="112" y="318" width="250" height="130" rx="16" fill="#ecfdf5" stroke="#a7f3d0"/>
        <text x="142" y="372" font-family="Inter, Arial, sans-serif" font-size="18" font-weight="700" fill="#065f46">Legacy HTML</text>
        <text x="142" y="410" font-family="Inter, Arial, sans-serif" font-size="15" fill="#047857">Still viewable and downloadable.</text>
        <rect x="432" y="318" width="250" height="130" rx="16" fill="#fef3c7" stroke="#fde68a"/>
        <text x="462" y="372" font-family="Inter, Arial, sans-serif" font-size="18" font-weight="700" fill="#92400e">DOCX Artifact</text>
        <text x="462" y="410" font-family="Inter, Arial, sans-serif" font-size="15" fill="#b45309">Canonical generated file.</text>
        </svg>
        """#
    }

    private static var docsHTML: String {
        #"""
        <h1>Project Architecture Overview</h1>
        <p>This document outlines the architecture decisions for the OpenMates platform, covering frontend, backend, and infrastructure components.</p>
        <h2>1. Frontend Architecture</h2>
        <p>The frontend is built with <strong>SvelteKit</strong> and uses Svelte 5 runes for reactivity. Key design decisions include:</p>
        <ul>
        <li>Component-based architecture with shared UI package</li>
        <li>CSS custom properties for theming</li>
        <li>IndexedDB for local data persistence</li>
        <li>Client-side encryption for user data</li>
        </ul>
        <h2>2. Backend Architecture</h2>
        <p>The backend uses <strong>FastAPI</strong> with Python, providing RESTful APIs for all services. Core components:</p>
        <ul>
        <li>WebSocket connections for real-time updates</li>
        <li>Redis for caching and task queues</li>
        <li>S3-compatible storage for encrypted files</li>
        </ul>
        <h2>3. Database Layer</h2>
        <p>PostgreSQL serves as the primary data store, managed through <strong>Directus CMS</strong>. The schema is designed for:</p>
        <ul>
        <li>Multi-tenant isolation</li>
        <li>Efficient query patterns for chat history</li>
        <li>JSON columns for flexible metadata storage</li>
        </ul>
        <h2>4. Infrastructure</h2>
        <p>The application is deployed using Docker containers orchestrated with Docker Compose. Each service runs in its own container for isolation and scalability.</p>
        """#
    }

    private static var docsDocument: DevEmbedPreviewSkill {
        let embed = record(id: "preview-docs-1", type: EmbedType.docsDoc.rawValue, appId: "docs", data: [
            "title": "Project Architecture Overview", "filename": "architecture.docx",
            "word_count": 156, "page_count": 2, "html": docsHTML, "html_content": docsHTML,
            "preview_page_urls": ["1": docsPreviewPageURL(docsPageOneSVG), "2": docsPreviewPageURL(docsPageTwoSVG)]
        ])
        return skill(id: "docs-doc", label: "Document", primary: embed)
    }

    private static var electronicsSearch: DevEmbedPreviewSkill {
        electronicsSearchSkill(id: "preview-electronics-search-1",
                               results: electronicsPreviewResults)
    }

    private static var electronicsSearchFullscreen: DevEmbedPreviewSkill {
        electronicsSearchSkill(id: "preview-electronics-search-fullscreen",
                               results: electronicsFullscreenResults)
    }

    private static func electronicsSearchSkill(id: String, results: [[String: Any]]) -> DevEmbedPreviewSkill {
        let children = results.enumerated().map { index, data in
            record(id: "\(id)-component-\(index + 1)",
                   type: EmbedType.electronicsComponent.rawValue,
                   appId: "electronics", data: data, parentEmbedId: id)
        }
        let parent = appSkill(id: id, type: EmbedType.electronicsSearch.rawValue,
                              appId: "electronics", skillId: "search_components",
                              data: ["query": "12V to 3.3V buck converter at 3A",
                                     "provider": "TI WEBENCH", "results": results,
                                     "result_count": results.count],
                              embedIds: children.map(\.id).joined(separator: "|"))
        return skill(id: id, label: "Search Components", primary: parent, children: children)
    }

    private static var electronicsPreviewResults: [[String: Any]] {
        [
            ["type": "power_converter", "provider": "TI WEBENCH",
             "part_number": "TPS564257DRLR", "base_part_number": "TPS564257",
             "title": "TPS564257DRLR Buck converter", "topology": "Buck",
             "package": "SOT-563", "regulator_type": "Converter",
             "product_url": "https://www.ti.com/product/TPS564257",
             "datasheet_url": "https://www.ti.com/lit/gpn/tps564257",
             "bom_cost_usd": 0.47, "bom_count": 11,
             "efficiency_percent": 92.4, "footprint_mm2": 89.6],
            ["type": "power_converter", "provider": "TI WEBENCH",
             "part_number": "TPS563257DRLR", "base_part_number": "TPS563257",
             "title": "TPS563257DRLR Buck converter", "topology": "Buck",
             "package": "SOT-563", "regulator_type": "Converter",
             "product_url": "https://www.ti.com/product/TPS563257",
             "datasheet_url": "https://www.ti.com/lit/gpn/tps563257",
             "bom_cost_usd": 0.43, "bom_count": 10,
             "efficiency_percent": 91.8, "footprint_mm2": 84.2]
        ]
    }

    private static var electronicsFullscreenResults: [[String: Any]] {
        var rows = electronicsPreviewResults
        rows[0]["control_mode"] = "D-CAP3"
        rows[0]["description"] = "Compact synchronous buck converter reference design from TI WEBENCH."
        rows[0]["frequency_hz"] = 650000
        rows[0]["max_output_current_a"] = 4
        rows[0]["input_voltage_min_v"] = 4.5
        rows[0]["input_voltage_max_v"] = 17
        rows[0]["output_voltage_min_v"] = 0.6
        rows[0]["output_voltage_max_v"] = 7
        rows[0]["isolated"] = false
        rows[1]["isolated"] = false
        return rows
    }

    private static var electronicsPcbSchematic: DevEmbedPreviewSkill {
        let embed = record(
            id: "preview-electronics-pcb-1",
            type: EmbedType.electronicsPcbSchematic.rawValue,
            status: .processing,
            appId: "electronics",
            data: ["language": "atopile"]
        )
        return skill(id: "electronics-pcb-schematic", label: "PCB Schematic", primary: embed)
    }

    private static var electronicsComponent: DevEmbedPreviewSkill {
        let embed = record(id: "preview-electronics-component-1",
                           type: EmbedType.electronicsComponent.rawValue,
                           appId: "electronics", data: electronicsPreviewResults[0])
        return skill(id: "electronics-component", label: "Component", primary: embed)
    }

    private static var electronicsComponentFullscreen: DevEmbedPreviewSkill {
        var data = electronicsFullscreenResults[0]
        data["output_ripple_vpp"] = 0.014
        let embed = record(id: "preview-electronics-component-fs-1",
                           type: EmbedType.electronicsComponent.rawValue,
                           appId: "electronics", data: data)
        return skill(id: "electronics-component-fullscreen", label: "Component", primary: embed)
    }

    private static var healthAppointment: DevEmbedPreviewSkill {
        let embed = record(id: "preview-health-appointment-1", type: EmbedType.healthAppointment.rawValue, appId: "health", data: [
            "slot_datetime": "2026-04-03T10:30:00", "name": "Dr. Sophie Müller",
            "speciality": "Ophthalmologist", "address": "Maximilianstraße 12\n80539 Munich",
            "insurance": "public", "telehealth": false
        ])
        return skill(id: "health-appointment", label: "Appointment", primary: embed)
    }

    private static var healthAppointmentFullscreen: DevEmbedPreviewSkill {
        let embed = record(id: "preview-health-appointment-fs-1", type: EmbedType.healthAppointment.rawValue, appId: "health", data: [
            "slot_datetime": "2026-04-03T10:30:00", "name": "Dr. Sophie Müller",
            "speciality": "Ophthalmologist", "address": "Maximilianstraße 12\n80539 Munich",
            "gps_coordinates": ["latitude": 48.1397, "longitude": 11.5784],
            "insurance": "public", "telehealth": false,
            "practice_url": "https://www.doctolib.de/ophtalmologe/munich/sophie-mueller",
            "provider": "Doctolib", "provider_platform": "Doctolib"
        ])
        return skill(id: "health-appointment-fullscreen", label: "Appointment", primary: embed)
    }

    private static var fitnessLocation: DevEmbedPreviewSkill {
        let embed = record(id: "preview-fitness-location-1", type: EmbedType.fitnessLocation.rawValue,
                           appId: "fitness", data: fitnessStandalonePreviewData)
        return skill(id: "fitness-location", label: "Fitness Location", primary: embed)
    }

    private static var fitnessClass: DevEmbedPreviewSkill {
        let embed = record(id: "preview-fitness-class-1", type: EmbedType.fitnessClass.rawValue,
                           appId: "fitness", data: fitnessStandalonePreviewData)
        return skill(id: "fitness-class", label: "Fitness Class", primary: embed)
    }

    private static var fitnessStandalonePreviewData: [String: Any] {
        ["id": "appointment-1", "provider": "Urban Sports Club",
         "appointment_id": "appointment-1", "name": "Morning Yoga Flow",
         "category": "Yoga", "attendance_mode": "onsite", "date": "2026-07-10",
         "time_range": "07:30 - 08:30", "venue_name": "Yoga Studio Kreuzberg",
         "venue_address": "Oranienstr. 1, 10997 Berlin", "distance_km": 0.9,
         "spots_display": "5 spots left", "plans_required": ["Classic", "Premium", "Max"]]
    }

    private static var fitnessClassFullscreen: DevEmbedPreviewSkill {
        let embed = record(id: "preview-fitness-class-fs", type: EmbedType.fitnessClass.rawValue,
                           appId: "fitness", data: [:])
        return skill(id: "fitness-class-fullscreen", label: "Fitness Class", primary: embed)
    }

    private static var fitnessLocationFullscreen: DevEmbedPreviewSkill {
        let embed = record(id: "preview-fitness-location-fs", type: EmbedType.fitnessLocation.rawValue,
                           appId: "fitness", data: [:])
        return skill(id: "fitness-location-fullscreen", label: "Fitness Location", primary: embed)
    }

    private static var fitnessSearchLocations: DevEmbedPreviewSkill {
        fitnessSearchSkill(type: .fitnessSearchLocations, id: "preview-fitness-locations-1", key: "fitness-search-locations")
    }

    private static var fitnessSearchClasses: DevEmbedPreviewSkill {
        fitnessSearchSkill(type: .fitnessSearchClasses, id: "preview-fitness-classes-1", key: "fitness-search-classes")
    }

    private static func fitnessSearchSkill(type: EmbedType, id: String, key: String) -> DevEmbedPreviewSkill {
        let results: [[String: Any]] = [
            ["id": "appointment-1", "provider": "Urban Sports Club", "appointment_id": "appointment-1",
             "name": "Morning Yoga Flow", "category": "Yoga", "attendance_mode": "onsite",
             "date": "2026-07-10", "time_range": "07:30 - 08:30", "venue_name": "Yoga Studio Kreuzberg",
             "venue_address": "Oranienstr. 1, 10997 Berlin", "distance_km": 0.9,
             "spots_display": "5 spots left", "plans_required": ["Classic", "Premium", "Max"],
             "detail_url": "https://urbansportsclub.com/en/class-details/appointment-1"],
            ["id": "appointment-2", "provider": "Urban Sports Club", "appointment_id": "appointment-2",
             "name": "HIIT Strength", "category": "HIIT", "attendance_mode": "onsite",
             "date": "2026-07-10", "time_range": "18:00 - 19:00", "venue_name": "BEAT81 - Paul-Lincke-Ufer",
             "venue_address": "Paul-Lincke-Ufer 19, 10999 Berlin", "distance_km": 0.7,
             "spots_display": "3 spots left", "plans_required": ["Premium", "Max"],
             "detail_url": "https://urbansportsclub.com/en/class-details/appointment-2"]
        ]
        let children = results.enumerated().map { index, result in
            record(id: "\(id)-result-\(index + 1)", type: EmbedType.fitnessClass.rawValue,
                   appId: "fitness", data: result, parentEmbedId: id)
        }
        let parent = appSkill(id: id, type: type.rawValue, appId: "fitness", skillId: "search_classes",
                              data: ["provider": "Urban Sports Club", "results": [[
                                "id": "classes", "provider": "Urban Sports Club", "result_count": 2,
                                "filters": ["query": "yoga", "address": "Sorauer Str. 12, Berlin", "radius_km": 3,
                                            "plan": "all", "attendance_mode": "onsite"],
                                "summary": "Found 2 Urban Sports classes in onsite mode. Searched all Urban Sports plans.",
                                "results": results
                              ]]], embedIds: children.map(\.id).joined(separator: "|"))
        return skill(id: key, label: "Search classes", primary: parent, children: children)
    }

    private static var healthPreviewResults: [[String: Any]] {
        [
            ["type": "appointment", "slot_datetime": "2026-04-03T08:00:00",
             "name": "Dr. Markus Reinholz", "speciality": "Hautarzt / Dermatologe",
             "address": "Frauenplatz 11, 80331 München", "insurance": "", "telehealth": false],
            ["type": "appointment", "slot_datetime": "2026-04-03T10:30:00",
             "name": "Dr. Sophie Müller", "speciality": "Ophthalmologist",
             "address": "Maximilianstraße 12, 80539 Munich", "insurance": "public", "telehealth": false],
            ["type": "appointment", "slot_datetime": "2026-04-05T14:00:00",
             "name": "Prof. Dr. Klaus Weber", "speciality": "Ophthalmologist",
             "address": "Leopoldstraße 45, 80802 Munich", "insurance": "private", "telehealth": true]
        ]
    }

    private static var healthFullscreenResults: [[String: Any]] {
        [
            ["type": "appointment", "slot_datetime": "2026-04-03T08:00:00",
             "name": "Dr. Markus Reinholz", "speciality": "Hautarzt / Dermatologe",
             "address": "Frauenplatz 11, 80331 München",
             "gps_coordinates": ["latitude": 48.1374, "longitude": 11.5733],
             "insurance": "", "telehealth": false, "provider_platform": "Jameda",
             "booking_url": "https://www.jameda.de/booking/datum-auswaehlen/12345/67890/2026-04-03T08:00:00+01:00",
             "rating": 5.0, "rating_count": 125, "price": 120,
             "service_name": "Erstuntersuchung (Neupatient/in)"],
            ["type": "appointment", "slot_datetime": "2026-04-03T10:30:00",
             "name": "Dr. Sophie Müller", "speciality": "Ophthalmologist",
             "address": "Maximilianstraße 12, 80539 Munich",
             "gps_coordinates": ["latitude": 48.1397, "longitude": 11.5784],
             "insurance": "public", "telehealth": false, "provider_platform": "Doctolib",
             "practice_url": "https://www.doctolib.de/ophtalmologe/munich/sophie-mueller"],
            ["type": "appointment", "slot_datetime": "2026-04-03T14:00:00",
             "name": "Prof. Dr. Klaus Weber", "speciality": "Ophthalmologist",
             "address": "Leopoldstraße 45, 80802 Munich",
             "insurance": "private", "telehealth": true, "provider_platform": "Doctolib",
             "practice_url": "https://www.doctolib.de/cardiologue/munich/klaus-weber"],
            ["type": "appointment", "slot_datetime": "2026-04-04T09:30:00",
             "name": "Konrad Witkowski", "speciality": "Zahnarzt",
             "address": "Hoheluftchaussee 2, 20253 Hamburg", "provider_platform": "Jameda",
             "booking_url": "https://www.jameda.de/booking/datum-auswaehlen/44444/55555/2026-04-04T09:30:00+01:00",
             "rating": 4.8, "rating_count": 46, "service_name": "Allgemeine Sprechstunde"],
            ["type": "appointment", "name": "Dr. Anna Schmidt", "speciality": "Ophthalmologist",
             "address": "Sendlinger Straße 8, 80331 Munich",
             "insurance": "public", "telehealth": false, "provider_platform": "Doctolib",
             "practice_url": "https://www.doctolib.de/ophtalmologe/munich/anna-schmidt"]
        ]
    }

    private static var healthSearch: DevEmbedPreviewSkill {
        domainSearch(id: "preview-health-search-1", skillID: "health-search-appointments",
                     label: "Search", type: .healthSearch, childType: .healthAppointment,
                     appID: "health", action: "search_appointments",
                     query: "Ophthalmologist in Munich", provider: "Doctolib, Jameda",
                     results: healthPreviewResults)
    }

    private static var healthSearchFullscreen: DevEmbedPreviewSkill {
        domainSearch(id: "preview-health-search-fs", skillID: "health-search-fullscreen",
                     label: "Search", type: .healthSearch, childType: .healthAppointment,
                     appID: "health", action: "search_appointments",
                     query: "Ophthalmologist in Munich", provider: "Doctolib, Jameda",
                     results: healthFullscreenResults)
    }

    private static var homeListingData: [String: Any] {
        ["title": "Schöne 2-Zimmer-Wohnung in Kreuzberg", "price_label": "850 EUR/month",
         "size_sqm": 55, "rooms": 2, "address": "Bergmannstr. 12, 10961 Berlin",
         "image_url": "", "url": "https://www.immobilienscout24.de/expose/12345",
         "provider": "ImmoScout24", "listing_type": "rent"]
    }

    private static var homeListing: DevEmbedPreviewSkill {
        let embed = record(id: "preview-listing-1", type: EmbedType.homeListing.rawValue,
                           appId: "home", data: homeListingData)
        return skill(id: "home-listing", label: "Listing", primary: embed)
    }

    private static var homePreviewResults: [[String: Any]] {
        [
            ["title": "Schöne 2-Zimmer-Wohnung in Kreuzberg", "price_label": "850 EUR/month",
             "size_sqm": 55, "rooms": 2, "address": "Bergmannstr., 10961 Berlin",
             "image_url": "", "url": "https://www.immobilienscout24.de/expose/12345",
             "provider": "ImmoScout24", "listing_type": "rent"],
            ["title": "WG-Zimmer in Prenzlauer Berg", "price_label": "500 EUR/month",
             "size_sqm": 18, "rooms": 1, "address": "Schönhauser Allee, 10439 Berlin",
             "image_url": "", "url": "https://www.wg-gesucht.de/wg-zimmer-in-Berlin.12345.html",
             "provider": "WG-Gesucht", "listing_type": "rent"],
            ["title": "Helle 3-Zimmer-Altbauwohnung mit Balkon", "price_label": "1.200 EUR/month",
             "size_sqm": 85, "rooms": 3, "address": "Friedrichshain, 10245 Berlin",
             "image_url": "", "url": "https://www.kleinanzeigen.de/s-anzeige/67890",
             "provider": "Kleinanzeigen", "listing_type": "rent"]
        ]
    }

    private static var homeFullscreenResults: [[String: Any]] {
        var rows = homePreviewResults
        rows[1]["title"] = "WG-Zimmer in Prenzlauer Berg — möbliert, ab sofort"
        rows.append(["title": "Großzügiges Loft in Mitte mit Dachterrasse",
                     "price_label": "2.100 EUR/month", "size_sqm": 120, "rooms": 4,
                     "address": "Rosenthaler Str., 10119 Berlin", "image_url": "",
                     "url": "https://www.immobilienscout24.de/expose/99999",
                     "provider": "ImmoScout24", "listing_type": "rent"])
        return rows
    }

    private static var homeSearch: DevEmbedPreviewSkill {
        domainSearch(id: "preview-home-search-1", skillID: "home-search", label: "Search",
                     type: .homeSearch, childType: .homeListing, appID: "home", action: "search",
                     query: "Berlin", provider: "Multi", results: homePreviewResults)
    }

    private static var homeSearchFullscreen: DevEmbedPreviewSkill {
        domainSearch(id: "preview-home-search-fs", skillID: "home-search-fullscreen", label: "Search",
                     type: .homeSearch, childType: .homeListing, appID: "home", action: "search",
                     query: "Berlin", provider: "Multi", results: homeFullscreenResults)
    }

    private static var mail: DevEmbedPreviewSkill {
        let embed = record(id: "preview-mail-email-1", type: EmbedType.mailEmail.rawValue, appId: "mail", data: ["subject": "Project update", "from": "anna@example.com", "snippet": "The latest sprint review went well."])
        return skill(id: "mail-email", label: "Mail", primary: embed)
    }

    private static var mailSearch: DevEmbedPreviewSkill {
        let rows: [[String: Any]] = [
            ["uid": "1", "subject": "Invoice #1042 - OpenMates B.V.",
             "from": "billing@acme.com", "to": "admin@openmates.org",
             "snippet": "Please find attached invoice #1042 for services rendered in February 2026.",
             "date": "Thu, 28 Feb 2026 10:00:00 +0100", "timestamp": 1740733200, "is_unread": true],
            ["uid": "2", "subject": "Server maintenance scheduled",
             "from": "ops@provider.com", "to": "admin@openmates.org",
             "snippet": "Scheduled maintenance window: Saturday 22:00-02:00 UTC.",
             "date": "Wed, 27 Feb 2026 14:30:00 +0100", "timestamp": 1740659400, "is_unread": false],
            ["uid": "3", "subject": "New contributor joined",
             "from": "github-noreply@github.com", "to": "admin@openmates.org",
             "snippet": "A new contributor has opened a pull request in OpenMates/OpenMates.",
             "date": "Mon, 25 Feb 2026 08:00:00 +0100", "timestamp": 1740470400, "is_unread": false]
        ]
        let children = rows.enumerated().map { index, row in
            record(id: "preview-mail-search-result-\(index + 1)", type: EmbedType.mailEmail.rawValue,
                   appId: "mail", data: row, parentEmbedId: "preview-mail-search-1")
        }
        let parent = appSkill(id: "preview-mail-search-1", type: EmbedType.mailSearch.rawValue,
                              appId: "mail", skillId: "search",
                              data: ["query": "invoice", "provider": "Proton Mail",
                                     "results": rows, "result_count": 3],
                              embedIds: children.map(\.id).joined(separator: "|"))
        return skill(id: "mail-search", label: "Search", primary: parent, children: children)
    }

    private static var mailSearchFullscreen: DevEmbedPreviewSkill {
        let parent = appSkill(id: "preview-mail-search-fullscreen", type: EmbedType.mailSearch.rawValue,
                              appId: "mail", skillId: "search",
                              data: ["query": "Recent emails", "title": "Recent emails",
                                     "time_range": "All time", "result_count": 0,
                                     "results": [] as [[String: Any]]])
        return skill(id: "mail-search-fullscreen", label: "Search", primary: parent)
    }

    private static var mapsLocation: DevEmbedPreviewSkill {
        let embed = record(id: "preview-maps-location-1", type: EmbedType.maps.rawValue, appId: "maps", data: ["title": "Berlin Hauptbahnhof", "address": "Europaplatz 1, Berlin", "latitude": 52.5251, "longitude": 13.3694])
        return skill(id: "maps", label: "Location", primary: embed)
    }

    private static var mapsSearch: DevEmbedPreviewSkill {
        let rows: [[String: Any]] = [
            ["name": "Man vs. Machine Coffee Roasters", "address": "Müllerstraße 23, 80469 Munich",
             "rating": 4.7, "reviews": 1832, "type": "Coffee shop", "latitude": 48.1321, "longitude": 11.5718],
            ["name": "Lost Weekend", "address": "Schellingstraße 3, 80799 Munich",
             "rating": 4.5, "reviews": 2456, "type": "Coffee shop & bookstore", "latitude": 48.1523, "longitude": 11.5784],
            ["name": "Café Frischhut", "address": "Prälat-Zistl-Straße 8, 80331 Munich",
             "rating": 4.6, "reviews": 3210, "type": "Traditional café", "latitude": 48.1354, "longitude": 11.5762]
        ]
        let children = rows.enumerated().map { index, row in
            record(id: "preview-maps-place-\(index + 1)", type: EmbedType.mapsPlace.rawValue,
                   appId: "maps", data: row, parentEmbedId: "preview-maps-search-1")
        }
        let parent = appSkill(id: "preview-maps-search-1", type: EmbedType.mapsSearch.rawValue,
                              appId: "maps", skillId: "search",
                              data: ["query": "coffee shops near Marienplatz Munich",
                                     "provider": "Google", "results": rows, "result_count": 3],
                              embedIds: children.map(\.id).joined(separator: "|"))
        return skill(id: "maps-search", label: "Search", primary: parent, children: children)
    }

    private static var mapsSearchFullscreen: DevEmbedPreviewSkill {
        let parent = appSkill(id: "preview-maps-search-fullscreen", type: EmbedType.mapsSearch.rawValue,
                              appId: "maps", skillId: "search",
                              data: ["query": "coffee shops near Marienplatz Munich",
                                     "provider": "Google", "results": [] as [[String: Any]],
                                     "result_count": 0])
        return skill(id: "maps-search-fullscreen", label: "Search", primary: parent)
    }

    private static var mathCalculate: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-math-calculate-1", type: EmbedType.mathCalculate.rawValue, appId: "math", skillId: "calculate", data: [
            "title": "Trigonometry sanity check",
            "query": "sin(pi/4) + cos(pi/3)",
            "results": [["expression": "sin(pi/4) + cos(pi/3)", "result": "1.20710678118655", "result_type": "float", "mode": "numeric"]]
        ])
        return skill(id: "math-calculate", label: "Calculate", primary: embed)
    }

    private static var mathPlot: DevEmbedPreviewSkill {
        let embed = record(id: "preview-math-plot-1", type: EmbedType.mathPlot.rawValue, appId: "math", data: ["plot_spec": "f(x) = sin(x)\nf(x) = cos(x)"])
        return skill(id: "math-plot", label: "Plot", primary: embed)
    }

    private static var musicGenerate: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-music-generate-1", type: EmbedType.musicGenerate.rawValue, appId: "music", skillId: "generate", data: [
            "prompt": "A 30 second ambient synth background loop with soft pads and no drums",
            "mode": "background", "model": "lyria-3-clip-preview", "duration_seconds": 30,
            "generated_at": "2026-05-21T23:30:00Z", "watermarking": "SynthID"
        ])
        return skill(id: "music-generate", label: "Generate", primary: embed)
    }

    private static var mindmapsMindmap: DevEmbedPreviewSkill {
        let embed = record(id: "preview-mindmap-1", type: EmbedType.mindmapsMindmap.rawValue,
                           status: .processing, appId: "mindmaps", data: ["source_json": ""])
        return skill(id: "mindmaps-mindmap", label: "Mind Map", primary: embed)
    }

    private static var models3dSearch: DevEmbedPreviewSkill {
        let child = record(
            id: "preview-models3d-result-1",
            type: EmbedType.models3dModelResult.rawValue,
            appId: "models3d",
            data: ["title": "Low-poly planter", "model_format": "glb", "source_url": "https://example.com/models/planter"],
            parentEmbedId: "preview-models3d-search-1"
        )
        let parent = appSkill(id: "preview-models3d-search-1", type: EmbedType.models3dSearch.rawValue, appId: "models3d", skillId: "search", data: ["query": "low poly planter", "provider": "Sketchfab", "result_count": 1], embedIds: child.id)
        return skill(id: "models3d-search", label: "Search", primary: parent, children: [child])
    }

    private static var models3dModelResult: DevEmbedPreviewSkill {
        let embed = record(id: "preview-models3d-result-direct-1", type: EmbedType.models3dModelResult.rawValue, appId: "models3d", data: ["title": "Low-poly planter", "model_format": "glb", "source_url": "https://example.com/models/planter"])
        return skill(id: "models3d-model-result", label: "Model Result", primary: embed)
    }

    private static var models3dGenerate: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-models3d-generate-1", type: EmbedType.models3dGenerate.rawValue, appId: "models3d", skillId: "generate", data: ["title": "Generated planter", "prompt": "Low-poly balcony herb planter", "status": "finished"])
        return skill(id: "models3d-generate", label: "Generate", primary: embed)
    }

    private static var newsSearch: DevEmbedPreviewSkill {
        let rows: [[String: Any]] = [
            ["title": "AI Advances Continue to Transform Software Development",
             "url": "https://techcrunch.com/2026/ai-advances",
             "description": "New AI-powered development tools are changing how developers write, test, and deploy software.",
             "favicon": "/favicon.png", "thumbnail": ["original": "/images/og-image.jpg"],
             "published_at": "2026-02-15T08:00:00Z"],
            ["title": "WebAssembly 3.0 Specification Finalized",
             "url": "https://theverge.com/2026/wasm-3",
             "description": "The W3C has finalized the WebAssembly 3.0 specification, bringing garbage collection and improved threading.",
             "favicon": "/favicon.png", "thumbnail": ["original": "/images/og-image.jpg"],
             "published_at": "2026-02-10T12:00:00Z"],
            ["title": "European Tech Scene Sees Record Venture Capital Investment",
             "url": "https://bbc.com/news/eu-vc",
             "description": "European startups raised a record €45 billion in venture capital funding in Q4 2025.",
             "favicon": "/favicon.png", "thumbnail": ["original": "/images/og-image.jpg"],
             "published_at": "2026-01-28T09:00:00Z"]
        ]
        let children = rows.enumerated().map { index, row in
            record(id: "preview-news-result-\(index + 1)", type: EmbedType.webWebsite.rawValue,
                   appId: "news", data: row, parentEmbedId: "preview-news-search-1")
        }
        let parent = appSkill(id: "preview-news-search-1", type: EmbedType.newsSearch.rawValue,
                              appId: "news", skillId: "search",
                              data: ["query": "latest technology news 2026",
                                     "provider": "Brave Search", "results": rows,
                                     "result_count": 3],
                              embedIds: children.map(\.id).joined(separator: "|"))
        return skill(id: "news-search", label: "Search", primary: parent, children: children)
    }

    private static var nutritionRecipe: DevEmbedPreviewSkill {
        let embed = record(id: "preview-nutrition-recipe-1", type: EmbedType.nutritionRecipe.rawValue, appId: "nutrition", data: nutritionRecipeData)
        return skill(id: "nutrition-recipe", label: "Recipe", primary: embed)
    }

    private static var nutritionRecipeData: [String: Any] {
        ["title": "Spaghetti Aglio e Olio",
         "description": "Klassisches italienisches Knoblauch-Pasta-Gericht mit Olivenöl und Chili",
         "image_url": "", "total_time_minutes": 25, "difficulty": "einfach",
         "rating": 4.7, "rating_count": 342, "dietary_tags": ["vegetarisch"], "servings": 4]
    }

    private static var nutritionRecipeFullscreen: DevEmbedPreviewSkill {
        var data = nutritionRecipeData
        data["description"] = "Klassisches italienisches Knoblauch-Pasta-Gericht mit Olivenöl, Knoblauch und Chili. Einfach, schnell und unglaublich lecker."
        data["recipe_url"] = "https://www.edamam.com/results/recipes/?search=spaghetti%20aglio%20e%20olio"
        data["prep_time_minutes"] = 10
        data["cook_time_minutes"] = 15
        data["ernaehrwert_score"] = 6
        data["categories"] = ["Hauptspeise", "Pasta", "Italienisch"]
        data["ingredients"] = [
            ["amount": "400", "unit": "g", "name": "Spaghetti"],
            ["amount": "6", "unit": "Zehen", "name": "Knoblauch"],
            ["amount": "100", "unit": "ml", "name": "Olivenöl (extra vergine)"],
            ["amount": "1", "unit": "TL", "name": "Chiliflocken"],
            ["amount": "1", "unit": "Bund", "name": "Petersilie"],
            ["name": "Salz und Pfeffer"]
        ]
        data["instructions"] = [
            ["step": 1, "text": "Spaghetti in einem großen Topf mit reichlich Salzwasser al dente kochen. Etwas Kochwasser aufheben."],
            ["step": 2, "text": "Knoblauch schälen und in dünne Scheiben schneiden. Petersilie fein hacken."],
            ["step": 3, "text": "Olivenöl in einer großen Pfanne bei mittlerer Hitze erwärmen. Knoblauch darin goldbraun anbraten (nicht zu dunkel!)."],
            ["step": 4, "text": "Chiliflocken zum Knoblauch geben und kurz mitrösten."],
            ["step": 5, "text": "Abgetropfte Spaghetti in die Pfanne geben, mit etwas Kochwasser vermengen. Mit Petersilie, Salz und Pfeffer abschmecken."]
        ]
        data["nutrition"] = ["calories_kcal": 520, "protein_g": 14, "fat_g": 22, "carbs_g": 68]
        let embed = record(id: "preview-recipe-fs-001", type: EmbedType.nutritionRecipe.rawValue,
                           appId: "nutrition", data: data)
        return skill(id: "nutrition-recipe-fullscreen", label: "Recipe", primary: embed)
    }

    private static var nutritionPreviewResults: [[String: Any]] {
        [
            ["uid": "edamam-recipe-001", "title": "Spaghetti Aglio e Olio",
             "description": "Klassisches italienisches Knoblauch-Pasta-Gericht",
             "image_url": "", "total_time_minutes": 25, "difficulty": "einfach",
             "rating": 4.7, "rating_count": 342, "dietary_tags": ["vegetarisch"], "servings": 4],
            ["uid": "edamam-recipe-002", "title": "Penne Arrabiata mit frischen Tomaten",
             "description": "Scharfe Tomatensoße mit Penne", "image_url": "",
             "total_time_minutes": 30, "difficulty": "einfach",
             "rating": 4.5, "rating_count": 218, "dietary_tags": ["vegan"], "servings": 4],
            ["uid": "edamam-recipe-003", "title": "Tagliatelle mit Pilzrahmsauce",
             "description": "Cremige Pilzsauce mit frischen Kräutern", "image_url": "",
             "total_time_minutes": 35, "difficulty": "mittel",
             "rating": 4.8, "rating_count": 156, "dietary_tags": ["vegetarisch"], "servings": 2]
        ]
    }

    private static var nutritionFullscreenResults: [[String: Any]] {
        var first = nutritionRecipeFullscreen.primaryEmbed.rawData?.mapValues(\.value) ?? [:]
        first["type"] = "recipe"
        first["uid"] = "recipe-001"
        var second = nutritionPreviewResults[1]
        second["type"] = "recipe"
        second["uid"] = "recipe-002"
        second["title"] = "Penne Arrabiata"
        return [first, second]
    }

    private static var nutritionSearch: DevEmbedPreviewSkill {
        domainSearch(id: "preview-nutrition-search-1", skillID: "nutrition-search-recipes",
                     label: "Search", type: .nutritionSearch, childType: .nutritionRecipe,
                     appID: "nutrition", action: "search_recipes",
                     query: "vegetarische Pasta", provider: "Edamam", results: nutritionPreviewResults)
    }

    private static var nutritionSearchFullscreen: DevEmbedPreviewSkill {
        domainSearch(id: "preview-nutrition-search-fs", skillID: "nutrition-search-fullscreen",
                     label: "Search", type: .nutritionSearch, childType: .nutritionRecipe,
                     appID: "nutrition", action: "search_recipes",
                     query: "vegetarische Pasta", provider: "Edamam", results: nutritionFullscreenResults)
    }

    private static var pdf: DevEmbedPreviewSkill {
        let embed = record(id: "preview-pdf-upload-1", type: EmbedType.pdf.rawValue, appId: "pdf", data: ["filename": "Q4-2025-Annual-Report.pdf", "page_count": 42])
        return skill(id: "pdf", label: "PDF", primary: embed)
    }

    private static var reminderSet: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-reminder-set-1", type: EmbedType.reminderSet.rawValue, appId: "reminder", skillId: "set-reminder", data: reminderDefaultData)
        return skill(id: "reminder-set-reminder", label: "Set", primary: embed)
    }

    private static var reminderDefaultData: [String: Any] {
        [
            "reminder_id": "rem-abc-123", "trigger_at_formatted": "Tomorrow at 9:00 AM",
            "target_type": "new_chat", "is_repeating": false,
            "trigger_at": Int(Date().addingTimeInterval(86_400).timeIntervalSince1970),
            "prompt": "Review the pull request for the new authentication module",
            "message": "Reminder set successfully! I will remind you tomorrow at 9:00 AM."
        ]
    }

    private static var reminderList: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-reminder-list-1", type: EmbedType.reminderList.rawValue, appId: "reminder", skillId: "set-reminder", data: reminderDefaultData)
        return skill(id: "reminder-list-reminders", label: "List", primary: embed)
    }

    private static var reminderCancel: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-reminder-cancel-1", type: EmbedType.reminderCancel.rawValue, appId: "reminder", skillId: "set-reminder", data: reminderDefaultData)
        return skill(id: "reminder-cancel-reminder", label: "Cancel", primary: embed)
    }

    private static var sheet: DevEmbedPreviewSkill {
        let embed = record(
            id: "preview-sheet-1",
            type: EmbedType.sheetsSheet.rawValue,
            appId: "sheets",
            data: [
                "title": "Team Directory", "row_count": 5, "col_count": 4,
                "table": "| Name | Role | Department | Start Date |\n|------|------|------------|------------|\n| Alice Johnson | Senior Engineer | Engineering | 2023-01-15 |\n| Bob Smith | Product Manager | Product | 2022-06-01 |\n| Carol Williams | Designer | Design | 2024-03-10 |\n| David Brown | DevOps Lead | Engineering | 2021-11-20 |\n| Eva Martinez | QA Engineer | Engineering | 2023-08-05 |"
            ]
        )
        return skill(id: "sheets-sheet", label: "Sheet", primary: embed)
    }

    private static var sheetWide: DevEmbedPreviewSkill {
        let table = """
        | Region | Product | Q1 | Q2 | Q3 | Q4 | Total | Growth |
        |--------|---------|----|----|----|----|-------|--------|
        | North | Widget A | 12400 | 15800 | 18200 | 21500 | 67900 | +14% |
        | North | Widget B | 8900 | 9400 | 11200 | 13600 | 43100 | +18% |
        | South | Widget A | 9200 | 10500 | 12800 | 15400 | 47900 | +22% |
        | South | Widget B | 6700 | 7200 | 8900 | 10100 | 32900 | +12% |
        | East | Widget A | 14200 | 16700 | 19400 | 23100 | 73400 | +8% |
        | East | Widget B | 10400 | 11800 | 13200 | 15900 | 51300 | +16% |
        | West | Widget A | 11600 | 13200 | 15700 | 18900 | 59400 | +20% |
        | West | Widget B | 7800 | 8600 | 10200 | 12400 | 39000 | +11% |
        """
        let embed = record(id: "preview-sheet-large", type: EmbedType.sheetsSheet.rawValue, appId: "sheets",
                           data: ["title": "Sales Report Q4 2025", "row_count": 150, "col_count": 8, "table": table])
        return skill(id: "sheets-sheet-wide", label: "Sheet", primary: embed)
    }

    private static var sheetFullscreen: DevEmbedPreviewSkill {
        let table = """
        | Name | Role | Department | Start Date | Location | Salary |
        |------|------|------------|------------|----------|--------|
        | Alice Johnson | Senior Engineer | Engineering | 2023-01-15 | Munich | €85,000 |
        | Bob Smith | Product Manager | Product | 2022-06-01 | Berlin | €92,000 |
        | Carol Williams | Lead Designer | Design | 2024-03-10 | Munich | €78,000 |
        | David Brown | DevOps Lead | Engineering | 2021-11-20 | Remote | €88,000 |
        | Eva Martinez | QA Engineer | Engineering | 2023-08-05 | Barcelona | €72,000 |
        | Frank Lee | Frontend Developer | Engineering | 2024-01-08 | Munich | €76,000 |
        | Grace Kim | Data Analyst | Analytics | 2023-05-22 | Berlin | €68,000 |
        | Henry Davis | Backend Developer | Engineering | 2022-09-15 | Munich | €82,000 |
        """
        let embed = record(id: "preview-sheet-fullscreen-1",
                           type: EmbedType.sheetsSheet.rawValue, appId: "sheets",
                           data: ["title": "Team Directory", "table": table,
                                  "row_count": 8, "col_count": 6])
        return skill(id: "sheets-sheet-fullscreen", label: "Sheet", primary: embed)
    }

    private static var shoppingProduct: DevEmbedPreviewSkill {
        let embed = record(id: "preview-shopping-result-1", type: EmbedType.shoppingProduct.rawValue,
                           appId: "shopping", data: shoppingProductData)
        return skill(id: "shopping-product", label: "Product", primary: embed)
    }

    private static var shoppingProductData: [String: Any] {
        ["product_id": "rewe-12345", "title": "Bio Vollmilch-Joghurt Naturell",
         "brand": "Weihenstephan", "price_cents": 139, "price_eur": "1,39 €",
         "was_price_cents": 179, "grammage": "500g (0,28 €/100g)",
         "image_url": "", "rating": 4.6, "reviews": 832, "prime": false,
         "attributes": ["is_organic": true, "is_vegetarian": true]]
    }

    private static var shoppingProductFullscreen: DevEmbedPreviewSkill {
        var data = shoppingProductData
        data["purchase_url"] = "https://shop.rewe.de/p/weihenstephan-bio-joghurt/12345"
        data["category_path"] = "Molkereiprodukte > Joghurt"
        data["delivery"] = ["Lieferung heute"]
        data["bought_last_month"] = "500+ mal im letzten Monat gekauft"
        data["provider"] = "REWE"
        data["attributes"] = ["is_organic": true, "is_vegetarian": true, "is_regional": true]
        let embed = record(id: "preview-shopping-result-fs-1", type: EmbedType.shoppingProduct.rawValue,
                           appId: "shopping", data: data)
        return skill(id: "shopping-product-fullscreen", label: "Product", primary: embed)
    }

    private static var shoppingPreviewResults: [[String: Any]] {
        [
            ["product_id": "rewe-12345", "title": "Bio Vollmilch-Joghurt Naturell",
             "brand": "Weihenstephan", "price_cents": 139, "price_eur": "1,39 €",
             "grammage": "500g (0,28 €/100g)", "image_url": "",
             "purchase_url": "https://shop.rewe.de/p/weihenstephan-bio-joghurt/12345",
             "attributes": ["is_organic": true]],
            ["product_id": "rewe-12346", "title": "Demeter Bio-Joghurt mild",
             "brand": "Andechser Natur", "price_cents": 249, "price_eur": "2,49 €",
             "grammage": "500g (0,50 €/100g)", "image_url": "",
             "purchase_url": "https://shop.rewe.de/p/andechser-demeter-joghurt/12346",
             "attributes": ["is_organic": true, "is_vegetarian": true]],
            ["product_id": "rewe-12347", "title": "Griechischer Joghurt 10% Fett",
             "brand": "REWE Bio", "price_cents": 189, "price_eur": "1,89 €",
             "grammage": "400g (0,47 €/100g)", "image_url": "",
             "purchase_url": "https://shop.rewe.de/p/rewe-bio-griechischer-joghurt/12347",
             "attributes": ["is_organic": true, "is_vegetarian": true]]
        ]
    }

    private static var shoppingFullscreenResults: [[String: Any]] {
        shoppingPreviewResults + [
            ["product_id": "rewe-12348", "title": "Skyr Natur 0,2% Fett",
             "brand": "REWE Beste Wahl", "price_cents": 99, "price_eur": "0,99 €",
             "grammage": "450g (0,22 €/100g)", "image_url": "",
             "purchase_url": "https://shop.rewe.de/p/rewe-skyr-natur/12348",
             "attributes": ["is_vegetarian": true]]
        ]
    }

    private static var shoppingSearch: DevEmbedPreviewSkill {
        domainSearch(id: "preview-shopping-search-1", skillID: "shopping-search-products",
                     label: "Search", type: .shoppingSearch, childType: .shoppingProduct,
                     appID: "shopping", action: "search_products",
                     query: "bio joghurt", provider: "REWE", results: shoppingPreviewResults)
    }

    private static var shoppingSearchFullscreen: DevEmbedPreviewSkill {
        domainSearch(id: "preview-shopping-search-fs", skillID: "shopping-search-fullscreen",
                     label: "Search", type: .shoppingSearch, childType: .shoppingProduct,
                     appID: "shopping", action: "search_products",
                     query: "bio joghurt", provider: "REWE", results: shoppingFullscreenResults)
    }

    private static var socialMediaPost: DevEmbedPreviewSkill {
        let embed = record(id: "preview-social-media-post-1", type: EmbedType.socialMediaPost.rawValue, appId: "social_media", data: [
            "platform": "bluesky", "page": "search", "title": "Small cafe bar layout notes",
            "body": "A compact espresso bar can still feel calm: warm task lighting, a narrow handoff shelf, and one visible daily special board made this setup feel polished without clutter.",
            "author": "sample.cafe", "author_display_name": "Sample Cafe Journal",
            "published_at": "2026-05-24T10:30:00Z", "like_count": 184, "reply_count": 12, "repost_count": 27,
            "url": "https://bsky.app/profile/sample.cafe/post/example-1"
        ])
        return skill(id: "social-media-post", label: "Post", primary: embed)
    }

    private static var socialMediaGetPosts: DevEmbedPreviewSkill {
        let child = socialMediaPost.primaryEmbed
        let parent = appSkill(id: "preview-social-media-get-posts-1", type: EmbedType.socialMediaGetPosts.rawValue, appId: "social_media", skillId: "get-posts", data: ["query": "@samplegarden.example", "provider": "bluesky_public", "result_count": 1], embedIds: child.id)
        return skill(id: "social-media-get-posts", label: "Get Posts", primary: parent, children: [child])
    }

    private static var socialMediaSearch: DevEmbedPreviewSkill {
        let child = socialMediaPost.primaryEmbed
        let parent = appSkill(id: "preview-social-media-search-1", type: EmbedType.socialMediaSearch.rawValue, appId: "social_media", skillId: "search", data: ["query": "Indie coffee setup inspiration", "provider": "bluesky_public", "result_count": 1], embedIds: child.id)
        return skill(id: "social-media-search", label: "Search", primary: parent, children: [child])
    }

    private static var tasksTask: DevEmbedPreviewSkill {
        let embed = record(id: "preview-task-child", type: EmbedType.tasksTask.rawValue, appId: "tasks",
                           data: ["task_id": "task-garden-1", "short_id": "T-104",
                                  "title": "Buy starter soil and basil seeds",
                                  "description": "Pick up seed trays, starter soil, and basil seeds before Saturday.",
                                  "status": "todo", "assignee": "user"])
        return skill(id: "tasks-task", label: "Task", primary: embed)
    }

    private static var tasksCreate: DevEmbedPreviewSkill {
        let results: [[String: Any]] = [
            ["task_id": "task-garden-1", "short_id": "T-104",
             "title": "Buy starter soil and basil seeds",
             "description": "Pick up seed trays, starter soil, and basil seeds before Saturday.",
             "status": "todo", "assignee": "user"],
            ["task_id": "task-garden-2", "short_id": "T-105",
             "title": "Clear the balcony planter boxes",
             "description": "Remove old roots and rinse the boxes so the spring planting can start.",
             "status": "in_progress", "assignee": "user"]
        ]
        let parent = appSkill(id: "preview-task-create", type: EmbedType.tasksCreate.rawValue,
                              appId: "tasks", skillId: "create",
                              data: ["instruction": "Create a practical checklist for starting a small balcony herb garden",
                                     "preview_results": results, "result_count": 2])
        return skill(id: "tasks-create", label: "Create", primary: parent)
    }

    private static var tasksSearch: DevEmbedPreviewSkill {
        let results: [[String: Any]] = [
            ["task_id": "task-packing-1", "short_id": "T-221",
             "title": "Pack passport and travel documents",
             "description": "Put passport, train ticket, and hotel confirmation in the front backpack pocket.",
             "status": "todo", "assignee": "user"],
            ["task_id": "task-packing-2", "short_id": "T-222",
             "title": "Charge camera batteries",
             "description": "Charge both batteries and put the charger in the electronics pouch.",
             "status": "done", "assignee": "user"]
        ]
        let parent = appSkill(id: "preview-task-search", type: EmbedType.tasksSearch.rawValue,
                              appId: "tasks", skillId: "search",
                              data: ["query": "packing list tasks", "preview_results": results,
                                     "result_count": 2])
        return skill(id: "tasks-search", label: "Search", primary: parent)
    }

    private static var tasksCreateFullscreen: DevEmbedPreviewSkill {
        let parent = appSkill(id: "preview-task-create-fullscreen", type: EmbedType.tasksCreate.rawValue,
                              appId: "tasks", skillId: "create",
                              data: ["title": "Created tasks", "result_count": 0,
                                     "results": [] as [[String: Any]]])
        return skill(id: "tasks-create-fullscreen", label: "Create", primary: parent)
    }

    private static var tasksSearchFullscreen: DevEmbedPreviewSkill {
        let parent = appSkill(id: "preview-task-search-fullscreen", type: EmbedType.tasksSearch.rawValue,
                              appId: "tasks", skillId: "search",
                              data: ["title": "Search tasks", "result_count": 0,
                                     "results": [] as [[String: Any]]])
        return skill(id: "tasks-search-fullscreen", label: "Search", primary: parent)
    }

    private static var video: DevEmbedPreviewSkill {
        // Match VideoEmbedPreview.preview.ts so card chrome and media pixels
        // compare against the rendered /dev/preview registry entry.
        let embed = record(id: "preview-videos-video-1", type: EmbedType.videosVideo.rawValue, appId: "videos", data: [
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "video_id": "dQw4w9WgXcQ",
            "title": "Understanding Svelte 5 Runes — Complete Tutorial",
            "channel": "Svelte Society",
            "duration_seconds": 1028,
            "duration_formatted": "17:08",
            "published_at": "2025-11-15T10:00:00Z"
        ])
        return skill(id: "videos-video", label: "Video", primary: embed)
    }

    private static var videosSearch: DevEmbedPreviewSkill {
        let rows: [[String: Any]] = [
            ["title": "Svelte 5 Runes — Complete Beginner Guide",
             "url": "https://www.youtube.com/watch?v=example1", "thumbnail_url": "",
             "channel_name": "Svelte Society", "duration_formatted": "17:08",
             "view_count": 245000, "published_at": "2025-11-15T10:00:00Z"],
            ["title": "Migrating from Svelte 4 to 5 — Step by Step",
             "url": "https://www.youtube.com/watch?v=example2", "thumbnail_url": "",
             "channel_name": "Frontend Masters", "duration_formatted": "32:15",
             "view_count": 128000, "published_at": "2025-10-20T14:00:00Z"],
            ["title": "Building a Full App with SvelteKit 2",
             "url": "https://www.youtube.com/watch?v=example3", "thumbnail_url": "",
             "channel_name": "Fireship", "duration_formatted": "12:42",
             "view_count": 890000, "published_at": "2025-09-05T08:00:00Z"]
        ]
        let children = rows.enumerated().map { index, row in
            record(id: "preview-videos-search-result-\(index + 1)",
                   type: EmbedType.videosVideo.rawValue, appId: "videos",
                   data: row, parentEmbedId: "preview-videos-search-1")
        }
        let parent = appSkill(id: "preview-videos-search-1", type: EmbedType.videosSearch.rawValue,
                              appId: "videos", skillId: "search",
                              data: ["query": "svelte 5 tutorial", "provider": "Brave Search",
                                     "results": rows, "result_count": 3],
                              embedIds: children.map(\.id).joined(separator: "|"))
        return skill(id: "videos-search", label: "Search", primary: parent, children: children)
    }

    private static var videoTranscript: DevEmbedPreviewSkill {
        let parentID = "preview-video-transcript-1"
        let child = record(
            id: "preview-video-transcript-result-1",
            type: EmbedType.videosVideo.rawValue,
            appId: "videos",
            skillId: "transcript_result",
            data: [
                "type": "transcript_result",
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "title": "Understanding Svelte 5 Runes",
                "transcript": "Today we are going to learn about Svelte 5 runes. Runes are a powerful new reactivity system. The $state rune replaces let declarations for reactive variables. The $derived rune replaces $: for computed values. And the $effect rune replaces $: for side effects.",
                "channel_name": "Svelte Society",
                "duration_formatted": "17:08"
            ],
            parentEmbedId: parentID
        )
        let embed = appSkill(
            id: parentID,
            type: EmbedType.videosTranscript.rawValue,
            appId: "videos",
            skillId: "get_transcript",
            data: [
                "result_count": 1,
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "preview_results": [[
                    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "title": "Understanding Svelte 5 Runes",
                    "transcript": "Today we are going to learn about Svelte 5 runes. Runes are a powerful new reactivity system. The $state rune replaces let declarations for reactive variables. The $derived rune replaces $: for computed values. And the $effect rune replaces $: for side effects.",
                    "channel_name": "Svelte Society", "duration_formatted": "17:08"
                ]]
            ],
            embedIds: child.id
        )
        return skill(id: "videos-get-transcript", label: "Get Transcript", primary: embed, children: [child])
    }

    private static var videoTranscriptFullscreen: DevEmbedPreviewSkill {
        let parentID = "preview-video-transcript-fs"
        let transcript = """
        Today we are going to learn about Svelte 5 runes. Runes are a powerful new reactivity system that replaces the old reactive declarations.

        The $state rune replaces let declarations for reactive variables. When you declare a variable with $state, Svelte automatically tracks all assignments to it.

        The $derived rune replaces $: for computed values. It takes an expression and re-evaluates it whenever its dependencies change.

        And the $effect rune replaces $: for side effects. It runs whenever any of its reactive dependencies change, similar to useEffect in React.
        """
        let result: [String: Any] = [
            "type": "transcript_result", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "title": "Understanding Svelte 5 Runes", "transcript": transcript,
            "channel_name": "Svelte Society", "duration_formatted": "17:08"
        ]
        let child = record(id: "preview-video-transcript-fs-result", type: EmbedType.videosVideo.rawValue,
                           appId: "videos", skillId: "transcript_result", data: result,
                           parentEmbedId: parentID)
        let parent = appSkill(id: parentID, type: EmbedType.videosTranscript.rawValue,
                              appId: "videos", skillId: "get_transcript",
                              data: ["url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                                     "results": [result], "result_count": 1],
                              embedIds: child.id)
        return skill(id: "videos-get-transcript-fullscreen", label: "Get Transcript",
                     primary: parent, children: [child])
    }

    private static var videoGenerate: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-video-generate-1", type: EmbedType.videosGenerate.rawValue,
                             appId: "videos", skillId: "generate", data: ["prompt": ""],
                             status: .processing)
        return skill(id: "videos-generate", label: "Generate", primary: embed)
    }

    private static var videoCreate: DevEmbedPreviewSkill {
        var data = videoCreateData
        data["video_url"] = "/dev-fixtures/video-creation/product-launch.mp4"
        data["thumbnail_url"] = ""
        let embed = appSkill(id: "preview-video-create-1", type: EmbedType.videosCreate.rawValue,
                             appId: "videos", skillId: "create", data: data)
        return skill(id: "videos-create", label: "Create", primary: embed)
    }

    private static var videoCreateFullscreen: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-video-create-fullscreen-1",
                             type: EmbedType.videosCreate.rawValue, appId: "videos",
                             skillId: "create", data: videoCreateData)
        return skill(id: "videos-create-fullscreen", label: "Create", primary: embed)
    }

    private static var videoCreateData: [String: Any] {
        [
            "filename": "ProductLaunch.tsx", "status": "finished",
            "remotion_source": videoCreateSource,
            "current_source_version": 1, "active_render_version": 1,
            "duration_in_frames": 240, "fps": 30,
            "width": 1920, "height": 1080,
            "duration_seconds": 8,
            "render_metadata": ["runtime_seconds": 12, "charged_credits": 0]
        ]
    }

    private static let videoCreateSource = """
    import { Sequence, AbsoluteFill, Audio } from "remotion";

    export const ProductLaunch: React.FC = () => {
      return (
        <AbsoluteFill>
          <Sequence from={0} durationInFrames={240}>
            <GradientBg />
          </Sequence>
          <Sequence from={0} durationInFrames={60}>
            <TitleCard text="Introducing OpenMates" />
          </Sequence>
          <Sequence from={60} durationInFrames={60}>
            <FeatureList />
          </Sequence>
          <Sequence from={120} durationInFrames={60}>
            <ClientEncryptionDemo />
          </Sequence>
          <Sequence from={180} durationInFrames={60}>
            <CallToAction />
          </Sequence>
          <Audio src="/static/music/background.mp3" />
        </AbsoluteFill>
      );
    };

    export const Root = () => (
      <Composition
        id="product-launch"
        component={ProductLaunch}
        durationInFrames={240}
        fps={30}
        width={1920}
        height={1080}
      />
    );
    """

    private static var weatherDay: DevEmbedPreviewSkill {
        let embed = record(id: "preview-weather-day-1", type: EmbedType.weatherDay.rawValue, appId: "weather", data: [
            "date": "2026-06-03", "location_name": "Berlin", "provider": "Deutscher Wetterdienst (DWD)",
            "condition": "rain", "icon": "rain", "temperature_min_c": 14, "temperature_max_c": 19,
            "precipitation_total_mm": 5.8, "precipitation_probability_max_pct": 67, "rain_hours": 13,
            "wind_speed_max_kmh": 24, "cloud_cover_avg_pct": 86, "relative_humidity_avg_pct": 72,
            "hourly": [
                ["time": "06:00", "condition": "cloudy", "icon": "cloudy", "temperature_c": 15, "precipitation_mm": 0.2, "precipitation_probability_pct": 31, "wind_speed_kmh": 12],
                ["time": "07:00", "condition": "rain", "icon": "rain", "temperature_c": 16, "precipitation_mm": 0.4, "precipitation_probability_pct": 48, "wind_speed_kmh": 14],
                ["time": "08:00", "condition": "rain", "icon": "rain", "temperature_c": 16, "precipitation_mm": 0.8, "precipitation_probability_pct": 67, "wind_speed_kmh": 18],
                ["time": "09:00", "condition": "thunderstorm", "icon": "thunderstorms-day-rain", "temperature_c": 17, "precipitation_mm": 1.2, "precipitation_probability_pct": 74, "wind_speed_kmh": 24],
                ["time": "10:00", "condition": "cloudy", "icon": "cloudy", "temperature_c": 18, "precipitation_mm": 0.1, "precipitation_probability_pct": 28, "wind_speed_kmh": 16]
            ]
        ])
        return skill(id: "weather-day", label: "Day", primary: embed)
    }

    private static var weatherForecast: DevEmbedPreviewSkill {
        let previewResults: [[String: Any]] = [
            ["date": "2026-06-02", "condition": "dry", "icon": "clear-day", "temperature_min_c": 15, "temperature_max_c": 26, "precipitation_total_mm": 0, "precipitation_probability_max_pct": 4, "rain_hours": 0],
            ["date": "2026-06-03", "condition": "rain", "icon": "rain", "temperature_min_c": 14, "temperature_max_c": 19, "precipitation_total_mm": 5.8, "precipitation_probability_max_pct": 67, "rain_hours": 13],
            ["date": "2026-06-04", "condition": "cloudy", "icon": "cloudy", "temperature_min_c": 13, "temperature_max_c": 21, "precipitation_total_mm": 4.9, "precipitation_probability_max_pct": 37, "rain_hours": 9],
            ["date": "2026-06-05", "condition": "thunderstorm", "icon": "thunderstorms-day-rain", "temperature_min_c": 16, "temperature_max_c": 22, "precipitation_total_mm": 12.4, "precipitation_probability_max_pct": 82, "rain_hours": 6]
        ]
        let results: [[String: Any]] = [
            ["date": "2026-06-02", "location_name": "Berlin", "provider": "Deutscher Wetterdienst (DWD)", "condition": "dry", "icon": "clear-day", "temperature_min_c": 15, "temperature_max_c": 26, "precipitation_total_mm": 0, "precipitation_probability_max_pct": 4, "rain_hours": 0],
            ["date": "2026-06-03", "location_name": "Berlin", "provider": "Deutscher Wetterdienst (DWD)", "condition": "rain", "icon": "rain", "temperature_min_c": 14, "temperature_max_c": 19, "precipitation_total_mm": 5.8, "precipitation_probability_max_pct": 67, "rain_hours": 13],
            ["date": "2026-06-04", "location_name": "Berlin", "provider": "Deutscher Wetterdienst (DWD)", "condition": "snow", "icon": "snow", "temperature_min_c": -2, "temperature_max_c": 3, "precipitation_total_mm": 4.1, "precipitation_probability_max_pct": 58, "rain_hours": 7]
        ]
        let children = results.enumerated().map { index, day in
            record(id: "preview-weather-forecast-day-\(index + 1)", type: EmbedType.weatherDay.rawValue, appId: "weather", data: day, parentEmbedId: "preview-weather-forecast-1")
        }
        let parent = appSkill(id: "preview-weather-forecast-1", type: EmbedType.weatherForecast.rawValue, appId: "weather", skillId: "forecast", data: [
            "query": "Berlin weather forecast", "provider": "Deutscher Wetterdienst (DWD)",
            "location_name": "Berlin", "location": ["name": "Berlin"],
            "preview_results": previewResults, "results": results
        ], embedIds: children.map(\.id).joined(separator: "|"))
        return skill(id: "weather-forecast", label: "Forecast", primary: parent, children: children)
    }

    private static var weatherRainRadar: DevEmbedPreviewSkill {
        let embed = appSkill(id: "preview-weather-radar-1", type: EmbedType.weatherRainRadar.rawValue, appId: "weather", skillId: "rain_radar", data: ["location_name": "Rostock", "summary": "Heavy rain moving east", "status": "finished"])
        return skill(id: "weather-rain-radar", label: "Rain Radar", primary: embed)
    }

    private static var workflowsWorkflow: DevEmbedPreviewSkill {
        let embed = record(id: "preview-workflow-child", type: EmbedType.workflowsWorkflow.rawValue,
                           appId: "workflows", data: [
                            "workflow_id": "workflow-garden-1", "title": "Weekly balcony garden reminder",
                            "description": "Every Saturday morning, remind me to water herbs and note which plants need trimming.",
                            "status": "ready", "enabled": true,
                            "trigger_summary": "Manual or weekly Saturday reminder"])
        return skill(id: "workflows-workflow", label: "Workflow", primary: embed)
    }

    private static var workflowsCreate: DevEmbedPreviewSkill {
        let parent = appSkill(id: "preview-workflow-create", type: EmbedType.workflowsCreateOrModify.rawValue,
                              appId: "workflows", skillId: "create-or-modify",
                              data: ["instruction": "Create a simple manual workflow for a weekly balcony garden check-in",
                                     "preview_results": [[
                                        "workflow_id": "workflow-garden-1",
                                        "title": "Weekly balcony garden reminder",
                                        "description": "Every Saturday morning, remind me to water herbs and note which plants need trimming.",
                                        "status": "ready", "enabled": true,
                                        "trigger_summary": "Manual or weekly Saturday reminder"
                                     ]], "result_count": 1])
        return skill(id: "workflows-create", label: "Create or Modify", primary: parent)
    }

    private static var workflowsSearch: DevEmbedPreviewSkill {
        let parent = appSkill(id: "preview-workflow-search", type: EmbedType.workflowsSearch.rawValue,
                              appId: "workflows", skillId: "search",
                              data: ["query": "travel packing workflows",
                                     "preview_results": [
                                        ["workflow_id": "workflow-packing-1",
                                         "title": "Trip packing reminder workflow",
                                         "description": "A manual workflow that creates a short packing checklist and reminder before each trip.",
                                         "status": "ready", "enabled": true, "trigger_summary": "Manual trigger"],
                                        ["workflow_id": "workflow-packing-2",
                                         "title": "Departure day weather check",
                                         "description": "Check the forecast on the morning of departure and remind me about rain gear if needed.",
                                         "status": "ready", "enabled": false, "trigger_summary": "Manual trigger"]
                                     ], "result_count": 2])
        return skill(id: "workflows-search", label: "Search", primary: parent)
    }

    private static var workflowsCreateFullscreen: DevEmbedPreviewSkill {
        let parent = appSkill(id: "preview-workflow-create-fullscreen",
                              type: EmbedType.workflowsCreateOrModify.rawValue,
                              appId: "workflows", skillId: "create-or-modify",
                              data: ["title": "Created workflow", "result_count": 0,
                                     "results": [] as [[String: Any]]])
        return skill(id: "workflows-create-fullscreen", label: "Create", primary: parent)
    }

    private static var workflowsSearchFullscreen: DevEmbedPreviewSkill {
        let parent = appSkill(id: "preview-workflow-search-fullscreen",
                              type: EmbedType.workflowsSearch.rawValue,
                              appId: "workflows", skillId: "search",
                              data: ["title": "Search workflows", "result_count": 0,
                                     "results": [] as [[String: Any]]])
        return skill(id: "workflows-search-fullscreen", label: "Search", primary: parent)
    }

    private static var financeCheckAccounts: DevEmbedPreviewSkill {
        let embed = appSkill(
            id: "preview-finance-check-accounts-1",
            type: EmbedType.financeCheckAccounts.rawValue,
            appId: "finance",
            skillId: "check_accounts",
            data: [
                "summary": "Finance overview for 2 accounts and 5 transactions: income 8000, expenses 2291.25.",
                "provider": "Revolut Business",
                "period": "monthly",
                "account_count": 2,
                "transaction_count": 5,
                "overview": [
                    "accounts": [
                        ["account_ref": "acct-main-eur", "source_ref": "revolut_business:connected-account", "display_label": "Operating EUR", "currency": "EUR", "balance": 8450.25, "balance_as_of": "2026-07-15"],
                        ["account_ref": "acct-savings-eur", "source_ref": "revolut_business:connected-account", "display_label": "Savings EUR", "currency": "EUR", "balance": 12500, "balance_as_of": "2026-07-15"]
                    ],
                    "transactions": [
                        ["transaction_ref": "revolut_business:tx-001", "account_ref": "acct-main-eur", "source_ref": "revolut_business:connected-account", "posted_at": "2026-05-05", "amount": 4200, "currency": "EUR", "direction": "income", "category": "revenue", "counterparty_placeholder": "[PAYER_REVENUE_001]", "state": "completed"],
                        ["transaction_ref": "revolut_business:tx-002", "account_ref": "acct-main-eur", "source_ref": "revolut_business:connected-account", "posted_at": "2026-05-08", "amount": -760.8, "currency": "EUR", "direction": "expense", "category": "software", "counterparty_placeholder": "[MERCHANT_SOFTWARE_001]", "state": "completed"],
                        ["transaction_ref": "revolut_business:tx-003", "account_ref": "acct-savings-eur", "source_ref": "revolut_business:connected-account", "posted_at": "2026-06-03", "amount": 3800, "currency": "EUR", "direction": "income", "category": "revenue", "counterparty_placeholder": "[PAYER_REVENUE_002]", "state": "completed"],
                        ["transaction_ref": "revolut_business:tx-004", "account_ref": "acct-main-eur", "source_ref": "revolut_business:connected-account", "posted_at": "2026-06-12", "amount": -1180.45, "currency": "EUR", "direction": "expense", "category": "travel", "counterparty_placeholder": "[MERCHANT_TRAVEL_001]", "state": "completed"],
                        ["transaction_ref": "revolut_business:tx-005", "account_ref": "acct-main-eur", "source_ref": "revolut_business:connected-account", "posted_at": "2026-07-02", "amount": -350, "currency": "EUR", "direction": "expense", "category": "meals", "counterparty_placeholder": "[MERCHANT_MEALS_001]", "state": "completed"]
                    ],
                    "summaries": [
                        "period": "monthly", "income_total": 8000, "expense_total": 2291.25, "net_total": 5708.75,
                        "by_category": [
                            "revenue": ["income": 8000, "expense": 0, "net": 8000],
                            "software": ["income": 0, "expense": 760.8, "net": -760.8],
                            "travel": ["income": 0, "expense": 1180.45, "net": -1180.45],
                            "meals": ["income": 0, "expense": 350, "net": -350]
                        ],
                        "time_series": [
                            ["bucket": "2026-05", "income": 4200, "expense": 760.8, "net": 3439.2, "transaction_count": 2],
                            ["bucket": "2026-06", "income": 3800, "expense": 1180.45, "net": 2619.55, "transaction_count": 2],
                            ["bucket": "2026-07", "income": 0, "expense": 350, "net": -350, "transaction_count": 1]
                        ],
                        "filters_applied": [:] as [String: String]
                    ],
                    "filter_options": [
                        "accounts": ["acct-main-eur", "acct-savings-eur"],
                        "sources": ["revolut_business:connected-account"],
                        "categories": ["meals", "revenue", "software", "travel"],
                        "directions": ["expense", "income"],
                        "states": ["completed"],
                        "placeholders": ["[MERCHANT_MEALS_001]", "[MERCHANT_SOFTWARE_001]", "[MERCHANT_TRAVEL_001]", "[PAYER_REVENUE_001]", "[PAYER_REVENUE_002]"]
                    ]
                ] as [String: Any]
            ]
        )
        return skill(id: "finance-check-accounts", label: "Check accounts", primary: embed)
    }

    // MARK: - Builders

    private static func domainSearch(
        id: String,
        skillID: String,
        label: String,
        type: EmbedType,
        childType: EmbedType,
        appID: String,
        action: String,
        query: String,
        provider: String,
        results: [[String: Any]]
    ) -> DevEmbedPreviewSkill {
        let children = results.enumerated().map { index, source in
            let childID = "\(id)-result-\(index + 1)"
            var data = source
            data["embed_id"] = childID
            return record(id: childID, type: childType.rawValue, appId: appID,
                          data: data, parentEmbedId: id)
        }
        let rows = children.compactMap { child -> [String: Any]? in
            child.rawData?.mapValues(\.value)
        }
        let parent = appSkill(id: id, type: type.rawValue, appId: appID, skillId: action,
                              data: ["query": query, "provider": provider, "results": rows,
                                     "result_count": rows.count],
                              embedIds: children.map(\.id).joined(separator: "|"))
        return skill(id: skillID, label: label, primary: parent, children: children)
    }

    // These surface overrides are expanded below as their canonical payloads
    // are aligned. Keeping the gallery buildable also lets focused UI tests run.

    private static func skill(
        id: String,
        label: String,
        primary: EmbedRecord,
        children: [EmbedRecord] = []
    ) -> DevEmbedPreviewSkill {
        DevEmbedPreviewSkill(
            id: id,
            label: label,
            primaryEmbed: primary,
            childEmbeds: children,
            allRecords: ([primary] + children).reduce(into: [:]) { records, embed in
                records[embed.id] = embed
            }
        )
    }

    private static func appSkill(
        id: String,
        type: String,
        appId: String,
        skillId: String,
        data: [String: Any],
        status: EmbedStatus = .finished,
        embedIds: String? = nil
    ) -> EmbedRecord {
        var raw = data
        raw["type"] = "app_skill_use"
        raw["app_id"] = appId
        raw["skill_id"] = skillId
        return record(id: id, type: type, status: status, appId: appId, skillId: skillId, data: raw, embedIds: embedIds)
    }

    private static func record(
        id: String,
        type: String,
        status: EmbedStatus = .finished,
        appId: String?,
        skillId: String? = nil,
        data: [String: Any],
        parentEmbedId: String? = nil,
        embedIds: String? = nil,
        versionNumber: Int? = nil,
        versionHistory: [EmbedVersionMetadata] = [],
        versionHistoryReadonly: Bool = false
    ) -> EmbedRecord {
        EmbedRecord(
            id: id,
            type: type,
            status: status,
            data: .raw(data.mapValues { AnyCodable($0) }),
            parentEmbedId: parentEmbedId,
            appId: appId,
            skillId: skillId,
            embedIds: embedIds,
            versionNumber: versionNumber,
            versionHistory: versionHistory,
            versionHistoryReadonly: versionHistoryReadonly,
            createdAt: "2026-03-15T08:30:00Z"
        )
    }

    private static func imageSearchResults(parentId: String) -> [EmbedRecord] {
        [
            imageResultRecord(id: "preview-images-search-result-1", title: "Golden Gate Bridge at dusk", thumbnail: "https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=200", image: "https://images.unsplash.com/photo-1501594907352-04cda38ebc29", parentId: parentId),
            imageResultRecord(id: "preview-images-search-result-2", title: "Aerial view of Golden Gate", thumbnail: "https://images.unsplash.com/photo-1506146332389-18140dc7b2fb?w=200", image: "https://images.unsplash.com/photo-1506146332389-18140dc7b2fb", parentId: parentId),
            imageResultRecord(id: "preview-images-search-result-3", title: "Golden Gate Bridge towers in fog", thumbnail: "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=200", image: "https://images.unsplash.com/photo-1558618666-fcd25c85cd64", parentId: parentId)
        ]
    }

    private static func imageResultRecord(id: String, title: String, thumbnail: String, image: String, parentId: String?) -> EmbedRecord {
        return record(
            id: id,
            type: EmbedType.imagesImageResult.rawValue,
            appId: "images",
            data: [
                "title": title,
                "source": "unsplash.com",
                "source_domain": "unsplash.com",
                "thumbnail_url": thumbnail,
                "image_url": image,
                "source_page_url": "https://unsplash.com/photos/Cs99I6PYLlk"
            ],
            parentEmbedId: parentId
        )
    }

    private static func travelConnectionRecord(
        id: String,
        price: String,
        destination: String,
        departure: String,
        arrival: String,
        duration: String,
        stops: Int,
        carrierCodes: [String],
        parentId: String?
    ) -> EmbedRecord {
        let destinationCode = destination.contains("Gatwick") ? "LGW" : "LHR"
        let destinationLatitude = destination.contains("Gatwick") ? 51.1537 : 51.4700
        let destinationLongitude = destination.contains("Gatwick") ? -0.1821 : -0.4543
        return record(
            id: id,
            type: EmbedType.travelConnection.rawValue,
            appId: "travel",
            data: [
                "price": price,
                "total_price": price,
                "currency": "EUR",
                "transport_method": "airplane",
                "trip_type": "one_way",
                "origin": "Munich (MUC)",
                "destination": destination,
                "origin_country_code": "DE",
                "destination_country_code": "GB",
                "departure": departure,
                "arrival": arrival,
                "duration": duration,
                "stops": stops,
                "carrier_codes": carrierCodes,
                "carriers": carrierCodes,
                "booking_url": "https://www.google.com/travel/flights",
                "booking_provider": "Google Flights",
                "legs": [[
                    "leg_index": 0,
                    "origin": "Munich (MUC)",
                    "destination": destination,
                    "departure": departure,
                    "arrival": arrival,
                    "duration": duration,
                    "stops": stops,
                    "segments": [[
                        "carrier": carrierCodes.first ?? "LH",
                        "carrier_code": carrierCodes.first ?? "LH",
                        "number": "\(carrierCodes.first ?? "LH") 123",
                        "departure_station": "MUC",
                        "departure_time": departure,
                        "departure_country_code": "DE",
                        "departure_is_daytime": false,
                        "departure_latitude": 48.3538,
                        "departure_longitude": 11.7861,
                        "arrival_station": destinationCode,
                        "arrival_time": arrival,
                        "arrival_country_code": "GB",
                        "arrival_is_daytime": false,
                        "arrival_latitude": destinationLatitude,
                        "arrival_longitude": destinationLongitude,
                        "duration": duration,
                        "travel_class": "Economy"
                    ]]
                ]]
            ],
            parentEmbedId: parentId
        )
    }

    private static func travelStayRecord(
        id: String,
        name: String,
        hotelClass: Int,
        rating: Double,
        reviews: Int,
        ratePerNight: String,
        totalRate: String,
        parentId: String?
    ) -> EmbedRecord {
        record(
            id: id,
            type: EmbedType.travelStay.rawValue,
            appId: "travel",
            data: [
                "name": name,
                "hotel_class": hotelClass,
                "overall_rating": rating,
                "rating": rating,
                "reviews": reviews,
                "currency": "EUR",
                "rate_per_night": ratePerNight,
                "price_per_night": Double(ratePerNight) ?? 0,
                "total_rate": totalRate,
                "link": "https://www.google.com/travel/hotels",
                "thumbnail": "https://images.unsplash.com/photo-1566073771259-6a8506099945?w=1200",
                "gps_coordinates": [
                    "latitude": 41.3874,
                    "longitude": 2.1686
                ],
                "amenities": ["Free Wi-Fi", "Breakfast included", "Spa", "Fitness center"],
                "free_cancellation": true,
                "eco_certified": true
            ],
            parentEmbedId: parentId
        )
    }

    private static func eventResults(parentId: String) -> [EmbedRecord] {
        [
            eventRecord(
                id: "preview-events-result-1",
                title: "AI & Machine Learning Berlin Meetup – Spring Edition",
                dateStart: "2026-03-15T19:00:00+01:00",
                dateEnd: "2026-03-15T22:00:00+01:00",
                eventType: "PHYSICAL",
                city: "Berlin",
                country: "Germany",
                rsvpCount: 142,
                isPaid: false,
                feeAmount: nil,
                imageURL: nil,
                venueName: "Factory Berlin",
                venueAddress: "Rheinsberger Str. 76-77",
                venueLatitude: 52.5393,
                venueLongitude: 13.4028,
                parentId: parentId,
                description: "Join us for an evening of talks on LLMs, RAG architectures, and production AI."
            ),
            eventRecord(
                id: "preview-events-result-2",
                title: "Web Dev Online: TypeScript Deep Dive",
                dateStart: "2026-03-20T18:00:00Z",
                dateEnd: "2026-03-20T20:00:00Z",
                eventType: "ONLINE",
                city: nil,
                country: nil,
                rsvpCount: 87,
                isPaid: false,
                feeAmount: nil,
                imageURL: nil,
                venueName: nil,
                venueAddress: nil,
                venueLatitude: nil,
                venueLongitude: nil,
                parentId: parentId,
                description: "A live online session covering advanced TypeScript patterns for scalable apps.",
                organizerName: "Web Dev Community"
            ),
            eventRecord(
                id: "preview-events-result-3",
                title: "Product Management Summit – London",
                dateStart: "2026-04-05T09:00:00+01:00",
                dateEnd: "2026-04-06T17:00:00+01:00",
                eventType: "PHYSICAL",
                city: "London",
                country: "United Kingdom",
                rsvpCount: 320,
                isPaid: true,
                feeAmount: 25,
                imageURL: nil,
                venueName: "The Barbican",
                venueAddress: "Silk St",
                venueLatitude: 51.521,
                venueLongitude: -0.093,
                parentId: parentId,
                description: "Two-day conference covering product strategy, user research, and growth tactics.",
                organizerName: "PM London"
            )
        ]
    }

    private static func eventRecord(
        id: String,
        title: String,
        dateStart: String,
        dateEnd: String,
        eventType: String,
        city: String?,
        country: String?,
        rsvpCount: Int,
        isPaid: Bool,
        feeAmount: Double?,
        imageURL: String?,
        venueName: String?,
        venueAddress: String?,
        venueLatitude: Double?,
        venueLongitude: Double?,
        parentId: String?,
        description: String = "Join us for an evening of talks, creative exchange, and community networking.",
        organizerName: String = "AI Berlin Community"
    ) -> EmbedRecord {
        var data: [String: Any] = [
            "type": "event_result",
            "provider": "meetup",
            "title": title,
            "description": description,
            "url": "https://www.meetup.com/example-ai-berlin/events/preview",
            "date_start": dateStart,
            "date_end": dateEnd,
            "timezone": "Europe/Berlin",
            "event_type": eventType,
            "organizer_name": organizerName,
            "organizer": ["name": organizerName],
            "rsvp_count": rsvpCount,
            "is_paid": isPaid,
            "app_id": "events",
            "skill_id": "search"
        ]
        if let imageURL { data["image_url"] = imageURL }
        if let venueName {
            var venue: [String: Any] = ["name": venueName]
            if let venueAddress { venue["address"] = venueAddress }
            if let city { venue["city"] = city }
            if let country { venue["country"] = country }
            if let venueLatitude { venue["lat"] = venueLatitude }
            if let venueLongitude { venue["lon"] = venueLongitude }
            data["venue"] = venue
        }
        if let venueName { data["venue_name"] = venueName }
        if let venueAddress { data["venue_address"] = venueAddress }
        if let venueLatitude { data["venue_lat"] = venueLatitude }
        if let venueLongitude { data["venue_lon"] = venueLongitude }
        if let city { data["venue_city"] = city }
        if let country { data["venue_country"] = country }
        if let feeAmount {
            data["fee_amount"] = feeAmount
            data["fee_currency"] = "GBP"
        }
        return record(
            id: id,
            type: EmbedType.eventsEvent.rawValue,
            appId: "events",
            data: data,
            parentEmbedId: parentId
        )
    }
}
#endif
