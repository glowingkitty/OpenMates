// Native billing address page: optional buyer address printed on invoices.
// Specification: specifications/features/billing/specification.yml
// The server owns storage and validation; this view only edits and submits the form.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/billing/SettingsBillingAddress.svelte
//          frontend/packages/ui/src/services/billingContext.ts (load/save address)
// CSS:     frontend/packages/ui/src/styles/settings.css
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

@MainActor
extension AppStrings {
    static var billingAddress: String { localized("settings.billing.billing_address") }
    static var billingAddressExplainer: String { localized("settings.billing.address_optional_explainer") }
    static var billingAddressAdd: String { localized("settings.billing.add_billing_address") }
    static var billingAddressName: String { localized("settings.billing.address_name") }
    static var billingAddressStreet1: String { localized("settings.billing.address_street_line_1") }
    static var billingAddressStreet2: String { localized("settings.billing.address_street_line_2") }
    static var billingAddressPostalCode: String { localized("settings.billing.address_postal_code") }
    static var billingAddressCity: String { localized("settings.billing.address_city") }
    static var billingAddressRegion: String { localized("settings.billing.address_region") }
    static var billingAddressCountry: String { localized("settings.billing.address_country") }
    static var billingAddressVatId: String { localized("settings.billing.address_vat_id") }
    static var billingAddressValidation: String { localized("settings.billing.address_validation") }
    static var billingAddressLoadError: String { localized("settings.billing.address_load_error") }
    static var billingAddressSaveError: String { localized("settings.billing.address_save_error") }
    static var billingAddressSaved: String { localized("settings.billing.address_saved") }
}

/// Buyer address as exchanged with `/v1/payments/buyer-address`.
struct BillingBuyerAddress: Codable, Equatable {
    var name: String
    var streetLine1: String
    var streetLine2: String?
    var postalCode: String
    var city: String
    var region: String?
    var country: String
    var vatId: String?

    /// Wire body, same snake_case keys as the web client.
    var wireBody: [String: Any] {
        ["name": name, "street_line_1": streetLine1,
         "street_line_2": streetLine2.map { $0 as Any } ?? NSNull(), "postal_code": postalCode, "city": city,
         "region": region.map { $0 as Any } ?? NSNull(), "country": country, "vat_id": vatId.map { $0 as Any } ?? NSNull()]
    }
}

struct BillingBuyerAddressEnvelope: Decodable {
    let buyerAddress: BillingBuyerAddress?
}

/// Mirrors the field handling of `save()` in SettingsBillingAddress.svelte.
struct BillingAddressForm: Equatable {
    var name = ""
    var streetLine1 = ""
    var streetLine2 = ""
    var postalCode = ""
    var city = ""
    var region = ""
    var country = ""
    var vatId = ""

    init() {}

    init(_ address: BillingBuyerAddress?) {
        name = address?.name ?? ""
        streetLine1 = address?.streetLine1 ?? ""
        streetLine2 = address?.streetLine2 ?? ""
        postalCode = address?.postalCode ?? ""
        city = address?.city ?? ""
        region = address?.region ?? ""
        country = address?.country ?? ""
        vatId = address?.vatId ?? ""
    }

    enum Outcome: Equatable {
        case clear
        case invalid
        case address(BillingBuyerAddress)
    }

    /// Every field blank clears the address; otherwise required fields must be set.
    func resolve() -> Outcome {
        let trimmed = [name, streetLine1, streetLine2, postalCode, city, region, country, vatId]
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        guard trimmed.contains(where: { !$0.isEmpty }) else { return .clear }
        let code = trimmed[6]
        let isCountry = code.count == 2 && code.unicodeScalars.allSatisfy { $0.isASCII && CharacterSet.letters.contains($0) }
        guard !trimmed[0].isEmpty, !trimmed[1].isEmpty, !trimmed[3].isEmpty, !trimmed[4].isEmpty, isCountry else { return .invalid }
        return .address(BillingBuyerAddress(
            name: trimmed[0], streetLine1: trimmed[1], streetLine2: trimmed[2].isEmpty ? nil : trimmed[2],
            postalCode: trimmed[3], city: trimmed[4], region: trimmed[5].isEmpty ? nil : trimmed[5],
            country: code.uppercased(), vatId: trimmed[7].isEmpty ? nil : trimmed[7]))
    }
}

struct BillingAddressView: View {
    @State private var form = BillingAddressForm()
    @State private var expanded = false
    @State private var isLoading = true
    @State private var isSaving = false
    @State private var error: String?
    @State private var saved = false

    var body: some View {
        OMSettingsPage(title: AppStrings.billingAddress, showsHeader: false) {
            Color.clear.frame(height: 0).accessibilityIdentifier("billing-address-page")
            Text(AppStrings.billingAddressExplainer)
                .font(.omSmall).foregroundStyle(Color.fontSecondary)
                .padding(.horizontal, .spacing5)
            if isLoading {
                OMSettingsInfoBox(message: AppStrings.loading)
            } else {
                if !expanded {
                    Button(AppStrings.billingAddressAdd) { expanded = true }
                        .buttonStyle(OMSettingsButtonStyle(secondary: true))
                        .padding(.horizontal, .spacing5)
                        .accessibilityIdentifier("billing-address-add")
                } else {
                    formFields
                }
                if let error {
                    OMSettingsInfoBox(kind: .warning, message: error, identifier: "billing-address-error")
                }
                if saved {
                    OMSettingsInfoBox(kind: .success, message: AppStrings.billingAddressSaved, identifier: "billing-address-saved")
                }
            }
        }
        .task { await load() }
    }

    private var formFields: some View {
        VStack(spacing: .spacing4) {
            OMSettingsSectionHeading(title: AppStrings.billingAddress, icon: "location")
            field(AppStrings.billingAddressName, $form.name, "billing-address-name")
            field(AppStrings.billingAddressStreet1, $form.streetLine1, "billing-address-street")
            field(AppStrings.billingAddressStreet2, $form.streetLine2, "billing-address-street-2")
            field(AppStrings.billingAddressPostalCode, $form.postalCode, "billing-address-postal-code")
            field(AppStrings.billingAddressCity, $form.city, "billing-address-city")
            field(AppStrings.billingAddressRegion, $form.region, "billing-address-region")
            field(AppStrings.billingAddressCountry, $form.country, "billing-address-country")
            field(AppStrings.billingAddressVatId, $form.vatId, "billing-address-vat-id")
            Button(AppStrings.save) { Task { await save() } }
                .buttonStyle(OMSettingsButtonStyle())
                .disabled(isSaving)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, .spacing5)
                .accessibilityIdentifier("billing-address-save")
        }
        .accessibilityIdentifier("billing-address-form")
    }

    private func field(_ label: String, _ value: Binding<String>, _ id: String) -> some View {
        OMSettingsTextInput(label: label, placeholder: label, value: value, identifier: id)
    }

    private func load() async {
        do {
            let envelope: BillingBuyerAddressEnvelope = try await APIClient.shared.request(.get, path: "/v1/payments/buyer-address")
            form = BillingAddressForm(envelope.buyerAddress)
            expanded = envelope.buyerAddress != nil
        } catch {
            self.error = AppStrings.billingAddressLoadError
            NativeDiagnostics.warning("Billing address load failed: \(type(of: error))", category: "billing")
        }
        isLoading = false
    }

    private func save() async {
        guard !isSaving else { return }
        error = nil
        saved = false
        let address: BillingBuyerAddress?
        switch form.resolve() {
        case .invalid: error = AppStrings.billingAddressValidation; return
        case .clear: address = nil
        case .address(let value): address = value
        }
        isSaving = true
        defer { isSaving = false }
        do {
            let body: [String: Any] = ["buyer_address": address?.wireBody ?? NSNull()]
            let envelope: BillingBuyerAddressEnvelope = try await APIClient.shared.request(.put, path: "/v1/payments/buyer-address", body: body)
            form = BillingAddressForm(envelope.buyerAddress)
            saved = true
        } catch {
            self.error = AppStrings.billingAddressSaveError
            NativeDiagnostics.warning("Billing address save failed: \(type(of: error))", category: "billing")
        }
    }
}
