# Home app architecture

> **Status**: ⚠️ **NOT YET IMPLEMENTED** - This is planned functionality that is still on the todo list.

## Overview

The Home app helps users manage their smart home devices and create automated routines. It provides centralized control of connected devices like lights, power plugs, thermostats, and other IoT devices.

## Core Features

### Settings and Memories

#### Smart Home Devices (`smart_home_devices`)

A list-based memory that stores information about each smart home device in the user's home. Each device entry includes:

- **Basic Information**:
  - `name`: Device name (required)
  - `device_type`: Type of device (e.g., "light", "power_plug", "thermostat", "door_lock")
  - `location`: Where the device is located (e.g., "Living room", "Kitchen", "Bedroom")
  - `manufacturer`: Device manufacturer
  - `model`: Device model number

- **Connection Details**:
  - `mqtt_topic`: MQTT topic for device control (required)
  - `mqtt_payload_on`: Payload to send when turning device on
  - `mqtt_payload_off`: Payload to send when turning device off
  - `device_id`: Unique identifier for the device

- **Configuration**:
  - `is_active`: Whether the device is currently enabled
  - `supported_commands`: List of supported commands (e.g., "on", "off", "dim", "color")
  - `default_state`: Default state when powered on
  - `notes`: Configuration notes or special instructions

### Device Control

#### MQTT Integration

The Home app uses MQTT protocol to communicate with smart home devices:

- **Lights**: Turn on/off, adjust brightness and color
- **Power Plugs**: Turn on/off to control connected devices
- **Thermostats**: Set temperature and modes
- **Door Locks**: Lock/unlock (with security considerations)

**Implementation Notes:**

- MQTT broker connection details should be configured at the app level
- Device discovery can help identify available devices on the network
- Commands are sent asynchronously with status confirmation when available
- Device status can be queried and displayed to users

### Skills

#### Control Smart Device (`control_smart_device`)

A skill that allows users to control their smart home devices through natural language. Users can say things like "turn off the living room light" or "set bedroom temperature to 72 degrees" and the app will execute the appropriate MQTT commands.

**Capabilities:**

- Turn devices on/off
- Adjust brightness/intensity
- Set temperature or other numeric values
- Create and execute device groups
- Execute custom commands

**Use Cases:**

- Quick device control through chat
- Voice-friendly commands for smart home automation
- Integrating with other apps (e.g., routines, schedules)

## Future Features and Providers

### TaskRabbit Integration

**Consideration**: Implement TaskRabbit API as a provider for a "Find help for task" skill. This would enable:

- **Task Posting**: Create and manage tasks on TaskRabbit
- **Tasker Search**: Find available taskers for specific jobs
- **Booking Management**: View and manage taskrabbit bookings
- **Integration with Home Tasks**: Combine smart home automation with real-world task help

**Potential Skills:**

- "Find help for task" - Search TaskRabbit taskers for available help with household tasks
- "Post a task on TaskRabbit" - Create and manage task postings
- "View my TaskRabbit bookings" - Track upcoming and completed tasks

**API Requirements:**

- OAuth authentication with TaskRabbit
- Task creation and management endpoints
- Tasker search and availability endpoints
- Booking and payment management

**Status:** Concept/Planning - Not yet implemented

## Data Model

Each device is stored as a separate encrypted entry in the `user_app_settings_and_memories` collection, following the standard app settings and memories architecture. The system maintains connection state and tracks device status changes.

## Use Cases

1. **Centralized Device Control**: Manage all smart home devices from one place
2. **Quick Access**: Rapidly control devices through chat interface
3. **Automation Integration**: Use device control in routines and automations
4. **Device Management**: Add, remove, and configure smart home devices
5. **Task Assistance**: Find help for household tasks via TaskRabbit integration
