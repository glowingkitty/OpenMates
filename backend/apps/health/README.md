# Health App

Everything to improve your health and well being.

## Overview

The Health app provides tools and features to help users manage their health information, prepare for doctor visits, find appointments, and access medication information.

## Features

### Medication Database

The Health app includes a comprehensive medication database that provides users with detailed information about medications.

**Use Cases**:
- **Medication Lookup**: Quickly search and find information about any medication
- **Doctor Visit Preparation**: Review current medications before appointments
- **Medication Safety**: Check for contraindications and interactions
- **Patient Education**: Understand medication purposes and proper usage
- **Prescription Verification**: Verify medication details against prescriptions

## Providers

### European Medicines Agency (EMA)

Integration with the European Medicines Agency (EMA) API to access authoritative medication data.

**Features**:
- Access to approved medications in the European Union
- Real-time medication information including:
  - Active ingredients
  - Therapeutic indications
  - Dosage and administration guidelines
  - Contraindications and warnings
  - Side effects and adverse reactions
  - Marketing authorization details

**Status**: Planning phase

## Previews

### Medication

Embedded medication preview component that displays comprehensive medication details within the chat interface.

**Quick Overview**:
- Displays key medication information at a glance
- Optimized for quick reference during conversations

**Detailed Information**:
- Generic and brand names
- Active pharmaceutical ingredients
- Strength and dosage forms
- Therapeutic category
- Approved indications
- Administration instructions
- Contraindications
- Drug interactions
- Storage requirements
- Manufacturer information

**Visual Elements**:
- Medication packaging images (when available)
- Color-coded safety warnings
- Easy-to-read formatting optimized for readability

**Status**: Planning phase

## Skills

### Search Appointments

Searches for available doctor appointments based on your requirements.

**Status**: Planning phase

**Providers**:
- Jameda
- Doctolib

**Notes**:
- Combines firecrawl API with provider endpoints to find available appointments
- Workarounds required due to complex provider APIs and UI limitations

### Create Report

Create a report for the next doctor visit, including symptoms, medication history, and relevant health data.

## Focuses

### Prepare Doctor Report

Asks clarifying questions to create a comprehensive report for the next doctor appointment.

**Includes**:
- Symptoms overview
- Previous doctor visits
- Previous tests and results (with links, QR codes, and access instructions)
- Data from health/fitness tracking devices (e.g., Apple Watch)
- Current medications from the medication database

### Health Insights

Get general health insights tailored to your questions through interactive dialogue.

**Status**: Planning phase

**Features**:
- Multi-round question and answer sessions
- Personalized health guidance
- Recommendations for which type of doctor to consult

### Prepare Doctor Appointment

Prepare for your next appointment by discussing symptoms, necessary tests, and required documentation.

**Status**: Planning phase

**Process**:
1. Discusses symptoms experienced in recent weeks and months
2. Identifies potential connections between symptoms
3. Reviews what test results and documents to collect
4. Suggests questions to ask the doctor
5. Reviews current medications and potential interactions

## Settings and Memories

The Health app stores encrypted user data for better health management and doctor appointment preparation.

### Appointments
Store health-related appointments including doctor visits, operations, specialist consultations, dental visits, eye care, therapy sessions, and vaccinations. The system automatically identifies upcoming appointments based on the appointment date.

**Data stored**: appointment type, doctor/specialist name, clinic name, date, time, reason, location, contact phone, and notes.

### Medical History
Maintain a personal medical history including past surgeries, chronic conditions, allergies, medications, vaccinations, and injuries. This helps healthcare providers understand your health background.

**Data stored**: condition type, condition name, date, status, details, and attending doctor name.

### Symptoms Log
Log symptoms you experience to help prepare for doctor appointments and identify patterns over time.

**Data stored**: symptom description, onset date, severity level, frequency, and additional notes.

For detailed information, see [Health App Architecture](../../architecture/apps/health.md).

## Data Privacy & Security

All user settings and health memories are encrypted end-to-end using the same security model as financial and authentication data. This ensures sensitive health information remains private and secure.

Encrypted data storage includes:
- Appointments (doctor visits, operations, specialist consultations, etc.)
- Medical History (conditions, allergies, vaccinations, past treatments)
- Symptoms Log (for appointment preparation and pattern analysis)
- Medication information
- Test results and medical documents

## Future Enhancements

- Integration with additional medication databases (FDA, national registries)
- Medication reminder system
- Drug interaction checker with real-time alerts
- Integration with pharmacy APIs for prescription management
- Health tracking device synchronization
- Symptom tracking and analysis
- Lab results integration and interpretation
- Medication adherence monitoring
