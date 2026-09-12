import SwiftUI

// Measured ActionButtons.svelte:176x180 menu,4x41 rows,padding8,radius20.
// Host supplies real actions, including existing fileImporter/security checks.
struct ComposerAttachmentActionRow<Model: View, Speech: View, Record: View, Submit: View>: View {
    let viewportWidth: CGFloat
    let onDrawing: () -> Void
    let onLocation: () -> Void
    let onCamera: () -> Void
    let onFiles: () -> Void
    @ViewBuilder var model: () -> Model
    @ViewBuilder var speech: () -> Speech
    @ViewBuilder var record: () -> Record
    @ViewBuilder var submit: () -> Submit
    @State private var menuOpen = false

    var body: some View {
        HStack(spacing: viewportWidth <= 544 ? 8 : 16) {
            Button { menuOpen.toggle() } label: {
                Icon("add", size: 25)
                    .foregroundStyle(Color.fontPrimary).frame(width: 40, height: 40)
            }.buttonStyle(.plain)
                .accessibilityLabel(AppStrings.attachFiles)
                .accessibilityIdentifier("composer-attachment-toggle")
                .accessibilityValue(menuOpen ? "expanded" : "collapsed")
                .overlay(alignment: .bottomLeading) {
                    if menuOpen {
                        ZStack(alignment: .bottomLeading) {
                            Color.black.opacity(0.001)
                                .frame(width: max(viewportWidth * 3, 1800), height: 2400)
                                .contentShape(Rectangle())
                                .onTapGesture { menuOpen = false }
                                .accessibilityLabel(AppStrings.close)
                                .accessibilityIdentifier("composer-attachment-dismiss")
                            menu.offset(y: -48)
                        }.zIndex(20)
                    }
                }
            model()
            Spacer(minLength: 0)
            speech()
            record()
            submit()
        }.frame(height: 40).padding(.horizontal, 16).padding(.bottom, 16)
    }
    private var menu: some View {
        VStack(spacing: 0) {
            item("whiteboard", AppStrings.sketchAction, "drawing", onDrawing)
            item("maps", AppStrings.shareLocation, "location", onLocation)
            item("camera", AppStrings.takePhoto, "camera", onCamera)
            item("files", AppStrings.attachFiles, "files", onFiles)
        }.padding(8).frame(width: 176, height: 180)
            .background(Color.grey0, in: RoundedRectangle(cornerRadius: 20))
            .shadow(color: .black.opacity(0.15), radius: 16, x: 0, y: 4)
            .accessibilityIdentifier("composer-attachment-menu")
            #if os(macOS)
            .onExitCommand { menuOpen = false }
            #endif
    }
    private func item(_ icon: String, _ title: String, _ id: String, _ action: @escaping () -> Void) -> some View {
        Button {
            menuOpen = false
            action()
        } label: {
            HStack(spacing: 8) {
                Icon(icon, size: 25)
                Text(title).font(.omP).foregroundStyle(Color.fontPrimary)
                Spacer(minLength: 0)
            }.padding(.horizontal, 8).frame(height: 41).contentShape(RoundedRectangle(cornerRadius: 8))
        }.buttonStyle(.plain).accessibilityIdentifier("composer-attachment-" + id)
    }
}
