// Server connection settings for switching OpenMates environments.
// Keeps the Apple app usable for production users and testers without rebuilds.
// Passkey authentication uses the selected web domain as the Origin/RP domain,
// so custom domains must also support Apple webcredentials association.

import SwiftUI

struct SettingsServerConnectionView: View {
    @State private var selectedDomain: String
    @State private var customDomains: [String]
    @State private var isAddingDomain = false
    @State private var newDomain = ""

    init() {
        let configuration = ServerConfiguration.current
        _selectedDomain = State(initialValue: configuration.selectedDomain)
        _customDomains = State(initialValue: configuration.customDomains)
    }

    var body: some View {
        OMSettingsPage(title: "Server", showsHeader: false) {
            OMSettingsSection {
                OMSettingsPickerRow(
                    title: "Server",
                    subtitle: "Choose which OpenMates domain this app connects to.",
                    icon: "server",
                    options: domainOptions,
                    selection: $selectedDomain
                )
                .onChange(of: selectedDomain) { _, _ in save() }

                if isAddingDomain {
                    addDomainForm
                } else {
                    Button {
                        isAddingDomain = true
                    } label: {
                        Label("Add domain", systemImage: "plus")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(OMSecondaryButtonStyle())
                    .padding(.horizontal, .spacing5)
                    .padding(.vertical, .spacing3)
                    .accessibleButton("Add domain")
                }
            }
        }
    }

    private var domainOptions: [OMDropdownOption] {
        activeConfiguration.selectableDomains.map { OMDropdownOption($0, label: $0) }
    }

    private var activeConfiguration: ServerEndpointConfiguration {
        ServerEndpointConfiguration(selectedDomain: selectedDomain, customDomains: customDomains)
    }

    private var addDomainForm: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            TextField("app.dev.openmates.org", text: $newDomain)
                #if os(iOS)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                #endif
                .textFieldStyle(OMTextFieldStyle())
                .accessibleInput("Domain")
                .onSubmit(addDomain)

            HStack(spacing: .spacing4) {
                Button("Cancel") {
                    newDomain = ""
                    isAddingDomain = false
                }
                .buttonStyle(OMSecondaryButtonStyle())

                Button("Add") {
                    addDomain()
                }
                .buttonStyle(OMPrimaryButtonStyle())
                .disabled(newDomain.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(.horizontal, .spacing5)
        .padding(.vertical, .spacing3)
    }

    private func save() {
        ServerConfiguration.current = activeConfiguration
    }

    private func addDomain() {
        let domain = ServerEndpointConfiguration.normalizedDomain(newDomain)
        customDomains = ServerEndpointConfiguration(
            selectedDomain: selectedDomain,
            customDomains: customDomains + [domain]
        ).customDomains
        selectedDomain = domain
        newDomain = ""
        isAddingDomain = false
        save()
    }
}
