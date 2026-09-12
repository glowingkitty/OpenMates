import Foundation

/// Web +page.svelte outer shell and ActiveChat.svelte inner split contract.
/// All breakpoints use measured window/container widths, never device families.
struct WorkspacePaneMetrics: Equatable {
    let windowWidth: CGFloat
    let sidebarOpen: Bool
    let settingsOpen: Bool
    let embedOpen: Bool
    let embedHasChatContext: Bool
    let chatHidden: Bool

    var sidebarOverlays: Bool { windowWidth <= 600 }
    var sidebarWidth: CGFloat { sidebarOverlays ? windowWidth : 325 }
    var settingsOverlays: Bool { windowWidth <= 1100 }
    var mainInset: CGFloat { sidebarOverlays ? 0 : sidebarOpen ? 335 : 10 }
    var workspaceGutters: CGFloat { windowWidth <= 600 ? 20 : 30 }
    var settingsReservation: CGFloat { settingsOpen && !settingsOverlays ? 343 : 0 }
    var activeWidth: CGFloat { max(0, windowWidth - mainInset - workspaceGutters - settingsReservation) }
    var splitCapable: Bool { activeWidth >= 1024 && embedOpen && embedHasChatContext }
    var transcriptWidth: CGFloat { splitCapable ? 400 : activeWidth }
    var transcriptVisible: Bool { !embedOpen || (splitCapable && !chatHidden) }
    var embedLeading: CGFloat { splitCapable && !chatHidden ? 410 : 0 }
    var embedWidth: CGFloat { max(0, activeWidth - embedLeading) }
    // Hidden split transcript keeps400pt layout/scroll; only placement/hit testing changes.
    var transcriptOffset: CGFloat { splitCapable && chatHidden ? -410 : 0 }
}
