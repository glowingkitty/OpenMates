# Health app architecture

## Settings and Memories

### Appointments
Users can store health-related appointments including doctor visits, operations, specialist consultations, and other medical appointments. The system automatically filters appointments based on the date field to identify upcoming appointments for reminders and preparation suggestions.

**Schema**:
- `appointment_type` (enum): Type of appointment - doctor_visit, operation, specialist, dental, eye_care, therapy, vaccination, or other
- `doctor_name` (string): Name of the doctor or specialist
- `clinic_name` (string): Name of the clinic or hospital
- `date` (date, YYYY-MM-DD): Appointment date
- `time` (time, HH:MM): Appointment time in 24-hour format
- `reason` (string): Reason for the appointment or procedure
- `location` (string): Address or location of the appointment
- `contact_phone` (string): Phone number of clinic/doctor
- `notes` (string): Additional notes, preparation instructions, or follow-up details

**Required fields**: appointment_type, date

### Medical History
Users can log their personal medical history including past surgeries, chronic conditions, allergies, medications, vaccinations, and injuries. This historical data helps doctors and healthcare providers understand the patient's health background.

**Schema**:
- `condition_type` (enum): Type of medical event - surgery, chronic_condition, allergy, medication, vaccination, injury, or other
- `name` (string): Name of the condition, medication, or surgery
- `date` (date, YYYY-MM-DD): When the condition occurred or started
- `status` (enum): Current status - active, resolved, or ongoing
- `details` (string): Details about the condition or treatment
- `doctor_name` (string): Name of attending doctor or specialist

**Required fields**: condition_type, name, date

### Symptoms Log
Users can maintain a log of symptoms they experience with dates and severity details. This information helps prepare comprehensive reports for doctor appointments and identifies patterns over time.

**Schema**:
- `symptom` (string): Name or description of the symptom
- `date_onset` (date, YYYY-MM-DD): Date when the symptom started
- `severity` (enum): Severity level - mild, moderate, or severe
- `frequency` (enum): How often it occurs - occasional, intermittent, or constant
- `notes` (string): Additional details about the symptom (triggers, duration, associated symptoms, etc.)

**Required fields**: symptom, date_onset

### Sleep Diary
Users can track their sleep patterns, quality, and factors affecting sleep. This data helps identify sleep patterns, improve sleep hygiene, and can be valuable information for healthcare providers when discussing sleep-related health issues.

**Schema**:
- `date` (date, YYYY-MM-DD): Date of the sleep period (typically the date when sleep started)
- `bedtime` (time, HH:MM): Time when the user went to bed in 24-hour format
- `wake_time` (time, HH:MM): Time when the user woke up in 24-hour format
- `sleep_duration_hours` (number): Total hours of sleep (can be calculated from bedtime/wake_time or manually entered)
- `sleep_quality` (enum): Overall sleep quality - poor, fair, good, or excellent
- `notes` (string): Additional notes about the sleep period (dreams, restlessness, specific disturbances, etc.)

**Required fields**: date

## Skills

### Search Appointments
Searches for available doctor appointments based on user requirements.

**Providers**:
- Jameda
- Doctolib

**Status**: Planning phase

**Implementation Notes**:
- Combines firecrawl API with provider endpoints to find available appointments
- Workarounds required due to complex provider APIs and limited API documentation
- May use AI-based browser automation tools for website interaction where direct API access is limited

### Create Report
Creates a comprehensive report for the next doctor visit, including symptoms, medical history, current medications, and relevant health data.

## Focuses

### Prepare Doctor Report
Asks clarifying questions to create a comprehensive report for the next doctor appointment.

**Includes**:
- Symptoms overview from the Symptoms Log
- Previous doctor visits from Medical History
- Previous tests and results with access links and instructions
- Data from health/fitness tracking devices (e.g., Apple Watch)
- Current medications from the Medication Database
- Relevant notes from Medical History

### Health Insights
Get general health insights tailored to your questions through interactive dialogue.

**Features**:
- Multi-round question and answer sessions
- Personalized health guidance
- Recommendations for which type of doctor to consult

**Status**: Planning phase

### Prepare Doctor Appointment
Prepare for your next appointment by discussing symptoms, necessary tests, and required documentation.

**Process**:
1. Reviews upcoming appointments from the Appointments list
2. Discusses symptoms experienced in recent weeks and months
3. Identifies potential connections between symptoms
4. Reviews what test results and documents to collect
5. Suggests questions to ask the doctor
6. References current medications and potential interactions
7. Prepares discussion points based on Medical History

**Status**: Planning phase

## Providers

### European Medicines Agency (EMA)

Integration with the European Medicines Agency (EMA) API to access authoritative medication information.

**Features**:
- Access to approved medications in the European Union
- Real-time medication information including active ingredients, indications, dosages, contraindications, and warnings

**Status**: Planning phase

### Jameda

Used for searching available doctor and specialist appointments in Germany.

**Status**: Planning phase

### Doctolib

Used for searching available doctor and specialist appointments across Europe.

**Status**: Planning phase

## Data Privacy & Security

All user settings and health memories are encrypted end-to-end before storage in Directus. This ensures sensitive health information remains private and secure.

**Encrypted storage** includes:
- Appointments
- Medical History
- Symptoms Log
- Sleep Diary
- Medication lists
- Test results
